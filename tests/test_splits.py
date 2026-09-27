"""Split-contract test doubles are not food/package training observations."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from packsense.contracts import TrialOutcome
from packsense.splits import (
    ReviewRegister, SplitPlan, TrialReview, build_split_manifest,
    main, parse_review_register, parse_split_plan, trial_digest,
)
from packsense.trials import TrialAudit, TrialEntry, TrialIssue


def _trial(index, *, source_id=None, trial_group_id=None, food_id="TEST-FOOD",
           failure_observed=True):
    name = f"{index:02d}"
    outcome = TrialOutcome(
        trial_id=f"TEST-TRIAL-{name}", trial_group_id=trial_group_id or f"TEST-GROUP-{name}",
        batch_id=f"TEST-BATCH-{name}", source_id=source_id or f"TEST-SOURCE-{name}",
        food_id=food_id, structure_id="TEST-STRUCTURE", fill_mass_g=100.0,
        package_area_m2=0.1, headspace_ml=50.0, storage_temperature_c=20.0,
        storage_relative_humidity_pct=50.0, observed_days=10.0,
        failure_observed=failure_observed, failure_criterion="test-only endpoint",
        failure_threshold="test-only threshold", structure_catalogue_version="TEST-CATALOGUE",
    )
    return TrialEntry(index + 2, outcome, f"test-only-locator-{name}")


def _review(entry, *, group=None):
    return TrialReview(
        trial_id=entry.outcome.trial_id, trial_digest=trial_digest(entry),
        independence_group_id=group or entry.outcome.trial_group_id,
        evidence_review_id="TEST-EVIDENCE-REVIEW", rights_review_id="TEST-RIGHTS-REVIEW",
        endpoint_review_id="TEST-ENDPOINT-REVIEW",
        structure_review_id="TEST-STRUCTURE-REVIEW",
        independence_review_id="TEST-INDEPENDENCE-REVIEW",
    )


def _cases(*, entries=None, reviews=None, plan=None):
    entries = tuple(_trial(index) for index in range(12)) if entries is None else tuple(entries)
    reviews = tuple(_review(entry) for entry in entries) if reviews is None else tuple(reviews)
    audit = TrialAudit("test-only-path", "a" * 64, None, len(entries), entries, ())
    register = ReviewRegister("a" * 64, "b" * 64, reviews)
    groups = tuple(f"TEST-GROUP-{index:02d}" for index in range(12))
    default_plan = SplitPlan(
        "TEST-PLAN", "a" * 64, "b" * 64, "c" * 64,
        groups[:8], groups[8:10], groups[10:],
    )
    return audit, register, default_plan if plan is None else plan


class SplitManifestTests(unittest.TestCase):
    def test_disjoint_source_groups_make_reproducible_allocation(self):
        audit, reviews, plan = _cases()
        first = build_split_manifest(audit, reviews, plan)
        self.assertEqual(first.status, "allocation_prepared")
        self.assertEqual(first.reasons, ())
        self.assertEqual(first.manifest["summaries"]["train"]["independent_groups"], 8)
        self.assertEqual(first.manifest["summaries"]["validation"]["independent_groups"], 2)
        self.assertEqual(first.manifest["summaries"]["test"]["independent_groups"], 2)
        self.assertEqual(
            first.diagnostics["target_split"],
            "80_percent_development_20_percent_untouched_test",
        )
        self.assertAlmostEqual(first.diagnostics["development_group_fraction"], 10 / 12)
        self.assertAlmostEqual(
            first.diagnostics["validation_fraction_within_development"], 0.20,
        )
        self.assertEqual(len(first.manifest["assignments"]), 12)
        self.assertEqual(first.manifest["supported_food_ids"], ["TEST-FOOD"])
        self.assertFalse(first.report()["model_trained"])
        reordered = replace(audit, entries=tuple(reversed(audit.entries)))
        self.assertEqual(
            first.manifest["manifest_sha256"],
            build_split_manifest(reordered, reviews, plan).manifest["manifest_sha256"],
        )

    def test_related_replicates_stay_in_one_partition(self):
        entries = [_trial(index) for index in range(12)]
        entries.append(_trial(12, source_id="TEST-SOURCE-00",
                              trial_group_id="TEST-GROUP-00"))
        reviews = tuple(_review(entry) for entry in entries)
        audit, register, plan = _cases(entries=entries, reviews=reviews)
        result = build_split_manifest(audit, register, plan)
        self.assertIsNotNone(result.manifest)
        by_trial = {item["trial_id"]: item["partition"]
                    for item in result.manifest["assignments"]}
        self.assertEqual(by_trial["TEST-TRIAL-00"], by_trial["TEST-TRIAL-12"])
        self.assertEqual(result.manifest["summaries"]["train"]["rows"], 9)
        self.assertEqual(result.manifest["summaries"]["train"]["independent_groups"], 8)
        self.assertAlmostEqual(result.manifest["summaries"]["train"]["row_fraction"], 9 / 13)

    def test_overlap_and_unassigned_groups_refuse_manifest(self):
        audit, reviews, plan = _cases()
        overlap = replace(plan, test_groups=(plan.validation_groups[0], plan.test_groups[1]))
        result = build_split_manifest(audit, reviews, overlap)
        self.assertIsNone(result.manifest)
        self.assertTrue(any(reason.startswith("group_crosses_partitions")
                            for reason in result.reasons))
        self.assertIn("unassigned_independence_groups", result.reasons)

    def test_source_and_trial_group_may_not_cross_partitions(self):
        for change, expected in (
            ({"source_id": "TEST-SOURCE-00"}, "source_crosses_independence_groups"),
            ({"trial_group_id": "TEST-GROUP-00"}, "trial_group_crosses_independence_groups"),
        ):
            with self.subTest(change=change):
                entries = [_trial(index) for index in range(12)]
                entries[10] = _trial(10, **change)
                reviews = tuple(_review(entry, group=f"TEST-GROUP-{index:02d}")
                                for index, entry in enumerate(entries))
                audit, reviews, plan = _cases(entries=entries, reviews=reviews)
                result = build_split_manifest(audit, reviews, plan)
                self.assertIsNone(result.manifest)
                self.assertTrue(any(reason.startswith(expected) for reason in result.reasons))

    def test_stale_source_review_or_plan_hash_blocks(self):
        audit, reviews, plan = _cases()
        cases = (
            (audit, replace(reviews, trial_source_sha256="d" * 64), plan,
             "trial_source_hash_mismatch"),
            (audit, reviews, replace(plan, review_register_sha256="d" * 64),
             "review_register_hash_mismatch"),
            (audit, replace(reviews, reviews=(replace(reviews.reviews[0],
                                                     trial_digest="e" * 64),)
                                         + reviews.reviews[1:]), plan,
             "trial_review_digest_mismatch"),
        )
        for source, register, selected, expected in cases:
            with self.subTest(expected=expected):
                result = build_split_manifest(source, register, selected)
                self.assertIsNone(result.manifest)
                self.assertTrue(any(reason.startswith(expected) for reason in result.reasons))

    def test_no_source_approval_or_rejected_rows_block(self):
        audit, reviews, plan = _cases()
        missing = build_split_manifest(audit, replace(reviews, reviews=reviews.reviews[1:]), plan)
        self.assertIsNone(missing.manifest)
        self.assertTrue(any(reason.startswith("missing_trial_reviews") for reason in missing.reasons))
        issue = TrialIssue(2, "TEST-TRIAL-00", "row", "invalid_value", "test-only")
        rejected = build_split_manifest(replace(audit, issues=(issue,)), reviews, plan)
        self.assertIn("trial_intake_has_rejected_rows", rejected.reasons)

    def test_censored_rows_are_not_failure_labels(self):
        entries = [_trial(index, failure_observed=index < 8) for index in range(12)]
        audit, reviews, plan = _cases(entries=entries)
        result = build_split_manifest(audit, reviews, plan)
        self.assertIsNone(result.manifest)
        self.assertIn("too_few_observed_failure_groups:validation", result.reasons)
        self.assertIn("too_few_observed_failure_groups:test", result.reasons)
        self.assertEqual(result.diagnostics["partitions"]["test"]["right_censored"], 2)

    def test_no_common_food_event_coverage_blocks_generalization_claim(self):
        entries = [_trial(index, food_id="TEST-FOOD-B" if index >= 10 else "TEST-FOOD-A")
                   for index in range(12)]
        audit, reviews, plan = _cases(entries=entries)
        result = build_split_manifest(audit, reviews, plan)
        self.assertIn("no_food_with_observed_failures_in_all_partitions", result.reasons)

    def test_small_or_lopsided_group_plan_is_not_a_train_test_split(self):
        audit, reviews, plan = _cases()
        too_small = replace(plan, train_groups=plan.train_groups[:7],
                            validation_groups=plan.validation_groups + (plan.train_groups[7],))
        result = build_split_manifest(audit, reviews, too_small)
        self.assertIn("too_few_independent_groups:train", result.reasons)
        lopsided = replace(plan, train_groups=plan.train_groups + plan.validation_groups,
                            validation_groups=())
        result = build_split_manifest(audit, reviews, lopsided)
        self.assertIn("group_split_outside_predeclared_80_20_holdout_tolerance", result.reasons)

    def test_empty_trial_audit_refuses_allocation(self):
        audit, reviews, plan = _cases()
        result = build_split_manifest(replace(audit, total_rows=0, entries=()),
                                      replace(reviews, reviews=()), plan)
        self.assertIn("no_schema_valid_trials", result.reasons)
        self.assertIsNone(result.manifest)


class SplitRegisterTests(unittest.TestCase):
    def test_strict_review_and_plan_parsers(self):
        audit, reviews, _ = _cases()
        register_bytes = json.dumps({
            "schema_version": 1,
            "trial_source_sha256": audit.source_sha256,
            "reviews": [asdict(review) for review in reviews.reviews],
        }).encode()
        register = parse_review_register(register_bytes)
        self.assertEqual(len(register.reviews), 12)
        plan_bytes = json.dumps({
            "schema_version": 1, "plan_id": "TEST-PLAN",
            "trial_source_sha256": audit.source_sha256,
            "review_register_sha256": register.register_sha256,
            "train_groups": [f"TEST-GROUP-{i:02d}" for i in range(8)],
            "validation_groups": ["TEST-GROUP-08", "TEST-GROUP-09"],
            "test_groups": ["TEST-GROUP-10", "TEST-GROUP-11"],
        }).encode()
        plan = parse_split_plan(plan_bytes)
        self.assertEqual(plan.review_register_sha256, register.register_sha256)
        self.assertIsNotNone(build_split_manifest(audit, register, plan).manifest)

    def test_duplicate_or_unscoped_reviews_and_plans_rejected(self):
        entry = _trial(0)
        review = asdict(_review(entry))
        base = {"schema_version": 1, "trial_source_sha256": "a" * 64,
                "reviews": [review]}
        for payload in (
            {**base, "reviews": [review, review]},
            {**base, "reviews": [{**review, "rights_review_id": ""}]},
            {**base, "reviews": [{**review, "extra": "not allowed"}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_review_register(json.dumps(payload).encode())
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_review_register(b'{"schema_version":1,"schema_version":1,"trial_source_sha256":"x","reviews":[]}')
        plan = {"schema_version": 1, "plan_id": "TEST-PLAN",
                "trial_source_sha256": "a" * 64, "review_register_sha256": "b" * 64,
                "train_groups": ["G"], "validation_groups": ["G"], "test_groups": []}
        self.assertIsNone(build_split_manifest(*_cases(plan=parse_split_plan(json.dumps(plan).encode()))).manifest)

    def test_cli_refuses_conflicting_outputs_before_writing_report(self):
        audit, reviews, plan = _cases()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review_file = root / "review.json"
            plan_file = root / "plan.json"
            review_file.write_text("test-only", encoding="utf-8")
            plan_file.write_text("test-only", encoding="utf-8")
            report_file = root / "audit.json"
            manifest_file = root / "manifest.json"
            for report, manifest in ((report_file, report_file),
                                     (report_file, manifest_file)):
                if manifest == manifest_file:
                    manifest_file.write_text("preserve", encoding="utf-8")
                argv = ["packsense.splits", str(root / "trials.csv"),
                        "--reviews", str(review_file), "--plan", str(plan_file),
                        "--report", str(report), "--manifest", str(manifest)]
                with self.subTest(manifest=manifest), \
                        patch.object(sys, "argv", argv), \
                        patch("packsense.splits.audit_trial_outcomes", return_value=audit), \
                        patch("packsense.splits.parse_review_register", return_value=reviews), \
                        patch("packsense.splits.parse_split_plan", return_value=plan), \
                        redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as caught:
                    main()
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse(report_file.exists())
            self.assertEqual(manifest_file.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
