"""Test-only constructed records exercise training gates, never model data."""

import csv
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from packsense.contracts import TrialOutcome
from packsense.shelf_life_model import (
    TrainingConfig,
    _feature_row,
    train_shelf_life,
)
from packsense.splits import (
    ReviewRegister,
    SplitPlan,
    TrialReview,
    parse_review_register,
    trial_digest,
)
from packsense.trials import (
    TRIAL_REQUIRED_COLUMNS,
    TrialAudit,
    TrialEntry,
    audit_trial_outcomes,
)
from packsense.shelf_life_model import main as training_main


def _entry(index: int, *, censored: bool = False, threshold: str = "test-only threshold") -> TrialEntry:
    group = f"TEST-GROUP-{index:02d}"
    structure = "TEST-STRUCTURE-A" if index % 2 == 0 else "TEST-STRUCTURE-B"
    outcome = TrialOutcome(
        trial_id=f"TEST-TRIAL-{index:02d}-{'C' if censored else 'E'}",
        trial_group_id=group,
        batch_id=f"TEST-BATCH-{index:02d}-{'C' if censored else 'E'}",
        source_id=f"TEST-SOURCE-{index:02d}",
        food_id="TEST-FOOD",
        structure_id=structure,
        fill_mass_g=100.0,
        package_area_m2=0.1,
        headspace_ml=50.0,
        storage_temperature_c=20.0,
        storage_relative_humidity_pct=50.0,
        observed_days=(5.0 if censored else 10.0 if index % 2 == 0 else 20.0),
        failure_observed=not censored,
        failure_criterion="test-only sensory endpoint",
        failure_threshold=threshold,
        structure_catalogue_version="TEST-CATALOGUE-V1",
    )
    return TrialEntry(index + 2, outcome, f"test-only-locator-{index:02d}")


def _review(entry: TrialEntry) -> TrialReview:
    return TrialReview(
        trial_id=entry.outcome.trial_id,
        trial_digest=trial_digest(entry),
        independence_group_id=entry.outcome.trial_group_id,
        evidence_review_id="TEST-ONLY-EVIDENCE",
        rights_review_id="TEST-ONLY-RIGHTS",
        endpoint_review_id="TEST-ONLY-ENDPOINT",
        structure_review_id="TEST-ONLY-STRUCTURE",
        independence_review_id="TEST-ONLY-INDEPENDENCE",
    )


def _reviewed_case(*, mixed_endpoint: bool = False, add_test_censor: bool = False,
                   neutral_validation: bool = False):
    entries = [_entry(index, threshold=(
        "different test-only threshold" if mixed_endpoint and index == 11
        else "test-only threshold"
    )) for index in range(12)]
    if neutral_validation:
        for index in (8, 9):
            outcome = replace(
                entries[index].outcome,
                structure_id="TEST-UNSEEN-VALIDATION-STRUCTURE",
                observed_days=15.0,
            )
            entries[index] = replace(entries[index], outcome=outcome)
    if add_test_censor:
        entries.append(_entry(10, censored=True))
    entries = tuple(entries)
    reviews = tuple(_review(entry) for entry in entries)
    audit = TrialAudit("TEST_ONLY", "a" * 64, None, len(entries), entries, ())
    register = ReviewRegister("a" * 64, "b" * 64, reviews)
    groups = tuple(f"TEST-GROUP-{index:02d}" for index in range(12))
    plan = SplitPlan(
        "TEST-ONLY-PLAN", "a" * 64, "b" * 64, "c" * 64,
        groups[:8], groups[8:10], groups[10:],
    )
    return audit, register, plan


class ShelfLifeTrainingTests(unittest.TestCase):
    def test_fit_uses_reviewed_split_and_keeps_result_research_only(self) -> None:
        audit, register, plan = _reviewed_case(add_test_censor=True)
        result = train_shelf_life(
            audit, register, plan,
            TrainingConfig(max_iterations=40, early_stopping_patience=5,
                           min_samples_leaf=1, random_seed=7),
        )
        self.assertIsNotNone(result.estimator)
        self.assertEqual(result.report["status"], "exploratory_test_evaluated")
        self.assertFalse(result.report["model_validated"])
        self.assertEqual(result.report["test"]["right_censored_rows"], 1)
        self.assertEqual(result.report["test"]["censored_lower_bound_rows"], 1)
        self.assertTrue(result.report["test"]["opened_after_validation_selection"])
        self.assertEqual(
            result.report["censoring_policy"].split(";")[0],
            "right-censored rows are excluded from regression fitting and error metrics",
        )

    def test_mixed_failure_endpoints_stop_before_fitting(self) -> None:
        audit, register, plan = _reviewed_case(mixed_endpoint=True)
        result = train_shelf_life(audit, register, plan)
        self.assertIsNone(result.estimator)
        self.assertEqual(result.report["status"], "not_ready")
        self.assertIn(
            "failure_endpoint_or_threshold_is_not_uniform",
            result.report["readiness_reasons"],
        )

    def test_validation_nonimprovement_does_not_open_test_partition(self) -> None:
        audit, register, plan = _reviewed_case(neutral_validation=True)
        result = train_shelf_life(
            audit, register, plan,
            TrainingConfig(max_iterations=30, early_stopping_patience=5,
                           min_samples_leaf=1, random_seed=7),
        )
        self.assertIsNone(result.estimator)
        self.assertEqual(result.report["status"], "candidate_not_better_on_validation")
        self.assertNotIn("test", result.report)
        self.assertFalse(result.report["model_validated"])

    def test_unready_split_never_fits(self) -> None:
        audit, register, plan = _reviewed_case()
        unassigned = replace(plan, test_groups=())
        result = train_shelf_life(audit, register, unassigned)
        self.assertIsNone(result.estimator)
        self.assertFalse(result.report["model_trained"])
        self.assertEqual(result.report["status"], "not_ready")

    def test_features_exclude_outcome_and_leakage_identifiers(self) -> None:
        outcome = _entry(0).outcome
        features = _feature_row(outcome)
        for forbidden in (
            "observed_days", "failure_observed", "failure_criterion",
            "failure_threshold", "failure_mechanism", "trial_id", "trial_group_id",
            "batch_id", "source_id",
        ):
            self.assertNotIn(forbidden, features)
        self.assertEqual(features["food_id"], "TEST-FOOD")
        self.assertEqual(features["structure_id"], "TEST-STRUCTURE-A")

    def test_cli_writes_hash_bound_artifact_only_after_validation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trials_path = root / "test-only-trials.csv"
            entries = [_entry(index) for index in range(12)]
            with trials_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=TRIAL_REQUIRED_COLUMNS)
                writer.writeheader()
                for entry in entries:
                    row = {
                        field: getattr(entry.outcome, field, None)
                        for field in TRIAL_REQUIRED_COLUMNS
                    }
                    row.update({
                        "source_locator": entry.source_locator,
                        "evidence_basis": "measured_trial",
                    })
                    writer.writerow(row)

            audit = audit_trial_outcomes(trials_path)
            self.assertFalse(audit.issues)
            self.assertEqual(len(audit.entries), 12)
            register_bytes = json.dumps({
                "schema_version": 1,
                "trial_source_sha256": audit.source_sha256,
                "reviews": [
                    {
                        "trial_id": review.trial_id,
                        "trial_digest": review.trial_digest,
                        "independence_group_id": review.independence_group_id,
                        "evidence_review_id": review.evidence_review_id,
                        "rights_review_id": review.rights_review_id,
                        "endpoint_review_id": review.endpoint_review_id,
                        "structure_review_id": review.structure_review_id,
                        "independence_review_id": review.independence_review_id,
                    }
                    for review in (_review(entry) for entry in audit.entries)
                ],
            }).encode("utf-8")
            register = parse_review_register(register_bytes)
            reviews_path = root / "test-only-reviews.json"
            reviews_path.write_bytes(register_bytes)
            groups = [f"TEST-GROUP-{index:02d}" for index in range(12)]
            plan_path = root / "test-only-plan.json"
            plan_path.write_text(json.dumps({
                "schema_version": 1,
                "plan_id": "TEST-ONLY-PLAN",
                "trial_source_sha256": audit.source_sha256,
                "review_register_sha256": register.register_sha256,
                "train_groups": groups[:8],
                "validation_groups": groups[8:10],
                "test_groups": groups[10:],
            }), encoding="utf-8")
            report_path = root / "new-report.json"
            model_path = root / "new-model.joblib"
            args = [
                "packsense.shelf_life_model", str(trials_path),
                "--reviews", str(reviews_path), "--plan", str(plan_path),
                "--report", str(report_path), "--model", str(model_path),
                "--max-iterations", "40", "--patience", "5", "--seed", "7",
            ]
            with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                self.assertEqual(training_main(), 0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "exploratory_test_evaluated")
            self.assertEqual(
                report["model_artifact_sha256"],
                hashlib.sha256(model_path.read_bytes()).hexdigest(),
            )
            self.assertTrue(report["test"]["opened_after_validation_selection"])
            self.assertFalse(report["model_validated"])


if __name__ == "__main__":
    unittest.main()
