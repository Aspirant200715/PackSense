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

from packsense.contracts import (
    FoodReference, MaterialGrade, StructureLayer, TrialOutcome,
)
from packsense.masters import FoodMasterEntry, MasterAudit, MaterialMasterEntry
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
from packsense.structure_review import (
    CHECK_KINDS, EvidenceCheck, StructureReview, StructureReviewRegister,
    audit_structure_reviews, draft_digest,
)
from packsense.structures import StructureCatalogueAudit, StructureDraft


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


def _linked_sources():
    food = FoodReference(
        "TEST-FOOD", "TEST-FOOD", None, 5.0, 3.0, 6.0,
        "reported reference", None, None, None, "TEST-ONLY-SOURCE",
    )
    foods = MasterAudit(
        "TEST-ONLY-FOOD", "f" * 64, "TEST-ONLY-SHEET", 1,
        (FoodMasterEntry(2, food, "reported_reference"),), (),
    )
    grade = MaterialGrade(
        "TEST-GRADE", "TEST-ONLY-MAKER", None, "TEST-ONLY-POLYMER",
        "TEST-ONLY-FILM", "sealant", 20.0, None, None, None, False,
        "TEST-ONLY-SEAL", "TEST-ONLY-CONTACT", "TEST-ONLY-USE",
        "TEST-ONLY-URL",
    )
    materials = MasterAudit(
        "TEST-ONLY-MATERIAL", "b" * 64, "TEST-ONLY-SHEET", 1,
        (MaterialMasterEntry(2, grade, None, "TEST-ONLY", "TEST-ONLY", None, None),), (),
    )
    drafts = tuple(StructureDraft(
        structure_id=f"TEST-STRUCTURE-{suffix}",
        pack_format="TEST-ONLY-POUCH",
        layers=(StructureLayer("TEST-GRADE", 20.0, "sealant", True),),
        sealant_grade_id="TEST-GRADE", converter="TEST-ONLY-CONVERTER",
        forming_method="TEST-ONLY-FORMING", closure_type="TEST-ONLY-HEAT-SEAL",
        structure_source_id=f"TEST-CONSTRUCTION-{suffix}",
        structure_source_locator="TEST-ONLY-LOCATOR",
        food_contact_evidence_id=f"TEST-CONTACT-{suffix}",
        food_contact_evidence_locator="TEST-ONLY-LOCATOR",
        compatible_food_scope=("TEST-FOOD",),
        service_temperature_min_c=0.0, service_temperature_max_c=40.0,
        estimated_barrier_grade_ids=(),
    ) for suffix in ("A", "B"))
    catalogue = StructureCatalogueAudit(
        "TEST-ONLY-CATALOGUE", "c" * 64, "TEST-CATALOGUE-V1",
        materials.source_sha256, len(drafts), drafts, (),
    )
    structure_decisions = []
    for draft in drafts:
        checks = tuple(EvidenceCheck(
            kind, (draft.structure_source_id if kind == "construction" else
                   draft.food_contact_evidence_id if kind == "food_contact" else
                   f"TEST-ONLY-{kind.upper()}"),
            "TEST-ONLY-LOCATOR", "e" * 64, "TEST-ONLY-STRUCTURE",
            "TEST-ONLY-RIGHTS", "pass",
        ) for kind in sorted(CHECK_KINDS))
        structure_decisions.append(StructureReview(
            draft.structure_id, draft_digest(draft), "TEST-ONLY-STRUCTURE",
            "TEST-ONLY-REVIEWER", ("TEST-FOOD",), 0.0, 40.0, checks,
        ))
    structure_register = StructureReviewRegister(
        catalogue.source_sha256, materials.source_sha256,
        catalogue.catalogue_version, "d" * 64, tuple(structure_decisions),
    )
    structure_audit = audit_structure_reviews(catalogue, structure_register)
    assert structure_audit.status == "review_attested"
    return foods, materials, catalogue, structure_audit


class ShelfLifeTrainingTests(unittest.TestCase):
    def test_unlinked_trial_or_reference_never_reaches_split_or_fit(self) -> None:
        audit, register, plan = _reviewed_case()
        foods, materials, catalogue, structure_audit = _linked_sources()
        first = audit.entries[0]
        cases = (
            (
                replace(audit, entries=(replace(first, outcome=replace(
                    first.outcome, food_id="TEST-UNKNOWN-FOOD",
                )), *audit.entries[1:])),
                register, foods, materials, catalogue, structure_audit,
                "trial_food_id_not_in_master",
            ),
            (
                replace(audit, entries=(replace(first, outcome=replace(
                    first.outcome, structure_id="TEST-UNKNOWN-STRUCTURE",
                )), *audit.entries[1:])),
                register, foods, materials, catalogue, structure_audit,
                "trial_structure_id_not_reviewed",
            ),
            (
                replace(audit, entries=(replace(first, outcome=replace(
                    first.outcome, structure_catalogue_version="TEST-OLD-CATALOGUE",
                )), *audit.entries[1:])),
                register, foods, materials, catalogue, structure_audit,
                "trial_catalogue_version_mismatch",
            ),
            (
                audit, replace(register, reviews=(replace(
                    register.reviews[0], structure_review_id="TEST-WRONG-REVIEW",
                ), *register.reviews[1:])),
                foods, materials, catalogue, structure_audit,
                "trial_structure_review_id_mismatch",
            ),
            (
                audit, register, foods, replace(materials, source_sha256="0" * 64),
                catalogue, structure_audit,
                "catalogue_material_master_hash_mismatch",
            ),
            (
                audit, register, foods, materials, catalogue, replace(
                    structure_audit, reviewed=tuple(replace(
                        reviewed, material_master_sha256="0" * 64,
                    ) for reviewed in structure_audit.reviewed),
                ),
                "structure_review_material_master_hash_mismatch",
            ),
            (
                audit, register, foods, materials, replace(
                    catalogue, entries=(replace(
                        catalogue.entries[0], pack_format="TEST-WRONG-FORMAT",
                    ), *catalogue.entries[1:]),
                ), structure_audit,
                "trial_structure_draft_binding_mismatch",
            ),
            (
                audit, register, foods, replace(materials, entries=(replace(
                    materials.entries[0], grade=replace(
                        materials.entries[0].grade, thickness_um=21.0,
                    ),
                ),)), catalogue, structure_audit,
                "trial_structure_gauge_not_in_material_master",
            ),
            (
                audit, register, replace(foods, entries=(replace(
                    foods.entries[0], reference=replace(
                        foods.entries[0].reference, commodity_type="TEST-OTHER-FOOD",
                    ),
                ),)), materials, catalogue, structure_audit,
                "trial_structure_food_scope_mismatch",
            ),
            (
                audit, register, foods, materials, catalogue, replace(
                    structure_audit, reviewed=tuple(replace(
                        reviewed, structure=replace(
                            reviewed.structure, service_temperature_max_c=15.0,
                        ),
                    ) for reviewed in structure_audit.reviewed),
                ),
                "trial_structure_temperature_out_of_scope",
            ),
        )
        for changed_audit, changed_register, changed_foods, changed_materials, changed_catalogue, changed_structures, expected in cases:
            with self.subTest(expected=expected):
                result = train_shelf_life(
                    changed_audit, changed_register, plan,
                    changed_foods, changed_materials, changed_catalogue,
                    changed_structures,
                )
                self.assertIsNone(result.estimator)
                self.assertEqual(result.report["status"], "not_ready")
                self.assertIsNone(result.report["split_audit"])
                issue_codes = {
                    issue["code"] for issue in result.report["trial_reference_links"]["issues"]
                }
                self.assertIn(expected, issue_codes)

    def test_fit_uses_reviewed_split_and_keeps_result_research_only(self) -> None:
        audit, register, plan = _reviewed_case(add_test_censor=True)
        result = train_shelf_life(
            audit, register, plan, *_linked_sources(),
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
        result = train_shelf_life(audit, register, plan, *_linked_sources())
        self.assertIsNone(result.estimator)
        self.assertEqual(result.report["status"], "not_ready")
        self.assertIn(
            "failure_endpoint_or_threshold_is_not_uniform",
            result.report["readiness_reasons"],
        )

    def test_validation_nonimprovement_does_not_open_test_partition(self) -> None:
        audit, register, plan = _reviewed_case(neutral_validation=True)
        result = train_shelf_life(
            audit, register, plan, *_linked_sources(),
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
        result = train_shelf_life(audit, register, unassigned, *_linked_sources())
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
            structure_reviews_path = root / "test-only-structure-reviews.json"
            structure_reviews_path.write_text("{}", encoding="utf-8")
            foods, materials, catalogue, structure_audit = _linked_sources()
            args = [
                "packsense.shelf_life_model", str(trials_path),
                "--reviews", str(reviews_path), "--plan", str(plan_path),
                "--food-master", str(root / "test-only-food.xlsx"),
                "--material-master", str(root / "test-only-material.xlsx"),
                "--structures", str(root / "test-only-structures.json"),
                "--structure-reviews", str(structure_reviews_path),
                "--report", str(report_path), "--model", str(model_path),
                "--max-iterations", "40", "--patience", "5", "--seed", "7",
            ]
            with (patch("sys.argv", args),
                  patch("packsense.shelf_life_model.load_food_references", return_value=foods),
                  patch("packsense.shelf_life_model.load_material_grades", return_value=materials),
                  patch("packsense.shelf_life_model.audit_structure_catalogue", return_value=catalogue),
                  patch("packsense.shelf_life_model.parse_structure_review_register", return_value=object()),
                  patch("packsense.shelf_life_model.audit_structure_reviews", return_value=structure_audit),
                  redirect_stdout(io.StringIO())):
                self.assertEqual(training_main(), 0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "exploratory_test_evaluated")
            self.assertEqual(
                report["model_artifact_sha256"],
                hashlib.sha256(model_path.read_bytes()).hexdigest(),
            )
            self.assertTrue(report["test"]["opened_after_validation_selection"])
            self.assertFalse(report["model_validated"])
            self.assertEqual(report["trial_reference_links"]["status"], "ready_for_split")


if __name__ == "__main__":
    unittest.main()
