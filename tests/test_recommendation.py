"""TEST_ONLY gates for the preliminary recommendation shortlist."""

import unittest
from dataclasses import replace

from packsense.candidate_transfer import FinishedPackageTransferEvidence
from packsense.contracts import (
    EvidenceBasis, HandlingSeverity, PackageStructure, StorageType, StructureLayer,
)
from packsense.enrichment import ExposureCondition
from packsense.requirements import (
    AppliedAssessment, AssessmentDecision, ProtectionMechanism, RequirementCard,
    TransferBudget, scenario_fingerprint,
)
from packsense.recommendation import (
    CandidateStatus, RecommendationStatus, screen_package_candidates,
)
from packsense.structure_review import (
    CHECK_KINDS, EvidenceCheck, ReviewAttestedStructure, StructureReviewAudit,
)


CATALOGUE_HASH = "a" * 64
MATERIAL_HASH = "b" * 64


def _card(*, screenable=True):
    return RequirementCard(
        record_id="TEST_ONLY_SCENARIO", food_reference_id="TEST_ONLY_FOOD",
        food_master_sha256="c" * 64, rule_set_version="TEST_ONLY",
        target_shelf_life_days=14.0, storage_type=StorageType.CHILLED,
        transport_mode="TEST_ONLY_MODE",
        exposures=(
            ExposureCondition("storage", 4.0, 80.0, None, False),
            ExposureCondition("transport", 6.0, None, 12.0, False),
            ExposureCondition("transport_max_excursion", 9.0, None, None, True),
        ),
        service_temperature_min_c=4.0, service_temperature_max_c=9.0,
        storage_relative_humidity_pct=80.0, transport_relative_humidity_pct=None,
        transport_duration_hours=12.0, transport_excursion_duration_hours=None,
        handling_severity=HandlingSeverity.HIGH, net_pack_quantity=100.0,
        net_pack_quantity_unit="g", produce_route_status="confirmed_non_respiring",
        route_source_id="TEST_ONLY_ROUTE_SOURCE", route_approval_id="TEST_ONLY_ROUTE",
        mechanism_status=(
            (ProtectionMechanism.OXYGEN_INGRESS, "source_limit"),
            (ProtectionMechanism.MOISTURE_GAIN, "source_limit"),
            (ProtectionMechanism.MOISTURE_LOSS, "source_assessed_not_required"),
        ),
        transfer_budgets=(
            TransferBudget(ProtectionMechanism.OXYGEN_INGRESS, 20.0,
                           "mmol_o2_per_pack", 20.0 / 14.0,
                           "TEST_ONLY_FOOD_O2", "TEST_ONLY_APPROVAL_O2"),
            TransferBudget(ProtectionMechanism.MOISTURE_GAIN, 12.0,
                           "g_h2o_per_pack", 12.0 / 14.0,
                           "TEST_ONLY_FOOD_WATER", "TEST_ONLY_APPROVAL_WATER"),
        ),
        applied_assessments=(AppliedAssessment(
            ProtectionMechanism.MOISTURE_LOSS, AssessmentDecision.NOT_REQUIRED,
            "TEST_ONLY_FOOD_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_APPROVAL",
            EvidenceBasis.MEASURED,
        ),),
        gaps=(
            "light_sensitivity_unassessed", "seal_integrity_pending_structure",
            "mechanical_verification_pending_structure", "food_contact_pending_structure",
        ),
        candidate_screening_allowed=screenable,
    )


def _reviewed(structure_id, *, scope="Dry snack", low=-5.0, high=35.0):
    structure = PackageStructure(
        structure_id=structure_id, pack_format="TEST_ONLY pouch",
        layers=(StructureLayer("TEST_ONLY_GRADE", 20.0, "sealant", True),),
        sealant_grade_id="TEST_ONLY_GRADE",
        structure_source_id="TEST_ONLY_CONSTRUCTION_SOURCE",
        food_contact_evidence_id="TEST_ONLY_CONTACT_SOURCE",
        compatible_food_scope=(scope,), service_temperature_min_c=low,
        service_temperature_max_c=high,
    )
    checks = tuple(EvidenceCheck(
        kind, (structure.structure_source_id if kind == "construction" else
               structure.food_contact_evidence_id if kind == "food_contact" else
               f"TEST_ONLY_{kind.upper()}_SOURCE"),
        "TEST_ONLY_LOCATOR", "e" * 64, "TEST_ONLY_REVIEW",
        "TEST_ONLY_RIGHTS", "pass",
    ) for kind in sorted(CHECK_KINDS))
    return ReviewAttestedStructure(
        structure, CATALOGUE_HASH, MATERIAL_HASH, "d" * 64,
        "TEST_ONLY_REVIEW", tuple(check.review_id for check in checks), (), checks,
    )


def _audit(*structures):
    return StructureReviewAudit(
        "review_attested", CATALOGUE_HASH, "d" * 64, tuple(structures), (),
    )


def _evidence(card, structure_id, mechanism, observed):
    if mechanism is ProtectionMechanism.OXYGEN_INGRESS:
        unit = "mmol_o2_per_pack"
    else:
        unit = "g_h2o_per_pack"
    return FinishedPackageTransferEvidence(
        record_id=card.record_id, food_reference_id=card.food_reference_id,
        structure_id=structure_id, structure_catalogue_sha256=CATALOGUE_HASH,
        scenario_fingerprint=scenario_fingerprint(card), mechanism=mechanism,
        cumulative_transfer=observed, transfer_unit=unit,
        target_days=card.target_shelf_life_days,
        pack_quantity=card.net_pack_quantity,
        pack_quantity_unit=card.net_pack_quantity_unit,
        valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
        valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
        source_id=f"TEST_ONLY_PACKAGE_{structure_id}_{mechanism.value}",
        source_locator="TEST_ONLY_LOCATOR",
        approval_id=f"TEST_ONLY_APPROVAL_{structure_id}_{mechanism.value}",
        evidence_basis=EvidenceBasis.MEASURED,
        correction_model_id=None, correction_model_version=None,
    )


class BasicRecommendationTests(unittest.TestCase):
    def test_in_memory_review_missing_checks_fails_closed(self):
        card = _card()
        reviewed = replace(_reviewed("TEST_ONLY_A"), evidence_checks=(),
                           evidence_check_ids=())
        evidence = (
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.OXYGEN_INGRESS, 5.0),
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.MOISTURE_GAIN, 6.0),
        )
        result = screen_package_candidates(
            card, "Dry snack", _audit(reviewed), evidence,
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.NOT_READY)
        self.assertIsNone(result.preferred_structure_id)
        self.assertEqual(result.candidates, ())
        self.assertIn("structure_review_required_checks_incomplete", result.reason_codes)

    def test_in_memory_review_broken_bindings_fail_closed(self):
        card = _card()
        reviewed = _reviewed("TEST_ONLY_A")
        cases = (
            (_audit(replace(reviewed, catalogue_sha256="f" * 64)),
             "structure_review_version_binding_invalid"),
            (_audit(replace(reviewed, evidence_check_ids=())),
             "structure_review_check_decision_or_identity_invalid"),
            (_audit(replace(reviewed, evidence_checks=(
                replace(reviewed.evidence_checks[0], decision="fail"),
                *reviewed.evidence_checks[1:],
            ))), "structure_review_check_decision_or_identity_invalid"),
            (_audit(replace(reviewed, evidence_checks=(
                replace(reviewed.evidence_checks[0], source_id="TEST_ONLY_WRONG"),
                *reviewed.evidence_checks[1:],
            ))), "structure_review_source_binding_invalid"),
            (_audit(reviewed, reviewed), "structure_review_duplicate_structure_id"),
            (_audit(replace(reviewed, structure=replace(
                reviewed.structure, layers=(),
            ))), "structure_review_structure_invalid"),
            (replace(_audit(reviewed), review_register_sha256="f" * 64),
             "structure_review_version_binding_invalid"),
        )
        for audit, expected in cases:
            with self.subTest(expected=expected):
                result = screen_package_candidates(
                    card, "Dry snack", audit, (),
                    current_material_master_sha256=MATERIAL_HASH,
                )
                self.assertEqual(result.status, RecommendationStatus.NOT_READY)
                self.assertEqual(result.candidates, ())
                self.assertIn(expected, result.reason_codes)

    def test_unique_best_protection_margin_is_preferred_not_certified(self):
        card = _card()
        first, second = _reviewed("TEST_ONLY_A"), _reviewed("TEST_ONLY_B")
        evidence = (
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.OXYGEN_INGRESS, 5.0),
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.MOISTURE_GAIN, 6.0),
            _evidence(card, "TEST_ONLY_B", ProtectionMechanism.OXYGEN_INGRESS, 8.0),
            _evidence(card, "TEST_ONLY_B", ProtectionMechanism.MOISTURE_GAIN, 3.0),
        )
        evidence = (*evidence, replace(
            evidence[0], record_id="TEST_ONLY_OTHER_SCENARIO",
            scenario_fingerprint="f" * 64,
        ))
        result = screen_package_candidates(
            card, "Dry snack", _audit(first, second), evidence,
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.PRELIMINARY_SHORTLIST)
        self.assertEqual(result.preferred_structure_id, "TEST_ONLY_B")
        self.assertEqual(result.ranking_basis,
                         "lowest_worst_case_transfer_budget_utilization")
        self.assertEqual(result.candidates[0].protection_rank, 2)
        self.assertEqual(result.candidates[1].protection_rank, 1)
        self.assertEqual(result.candidates[0].worst_case_budget_utilization, 0.5)
        report = result.report()
        self.assertFalse(report["package_feasible"])
        self.assertFalse(report["shelf_life_predicted"])
        self.assertFalse(report["cost_ranked"])
        self.assertIn("light_sensitivity_unassessed", report["warnings"])
        self.assertEqual(report["food_master_sha256"], "c" * 64)
        self.assertEqual(report["scenario_fingerprint"], scenario_fingerprint(card))
        self.assertEqual(
            report["candidates"][1]["provided_transfer_evidence"][0]["source_locator"],
            "TEST_ONLY_LOCATOR",
        )
        self.assertEqual(
            report["candidates"][1]["provided_transfer_evidence"][0]["comparison_decision"],
            "within_budget",
        )
        self.assertIn("structure_review", report["candidates"][1])

    def test_missing_trial_grade_data_never_becomes_a_material_recommendation(self):
        card = _card()
        result = screen_package_candidates(
            card, "Dry snack", _audit(_reviewed("TEST_ONLY_A")), (),
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.NOT_READY)
        self.assertIsNone(result.preferred_structure_id)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, CandidateStatus.UNRESOLVED)
        self.assertIn("finished_package_transfer_missing", candidate.reason_codes)

    def test_transfer_above_food_limit_excludes_package(self):
        card = _card()
        evidence = (
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.OXYGEN_INGRESS, 20.01),
            _evidence(card, "TEST_ONLY_A", ProtectionMechanism.MOISTURE_GAIN, 6.0),
        )
        result = screen_package_candidates(
            card, "Dry snack", _audit(_reviewed("TEST_ONLY_A")), evidence,
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.NOT_READY)
        self.assertIsNone(result.preferred_structure_id)
        self.assertEqual(result.candidates[0].status, CandidateStatus.EXCLUDED)
        self.assertIn("oxygen_ingress_exceeds_food_budget",
                      result.candidates[0].reason_codes)

    def test_food_scope_and_temperature_mismatches_are_excluded(self):
        card = _card()
        wrong_food = _reviewed("TEST_ONLY_FOOD", scope="Tomato")
        wrong_temperature = _reviewed("TEST_ONLY_TEMP", low=5.0, high=8.0)
        result = screen_package_candidates(
            card, "Dry snack", _audit(wrong_food, wrong_temperature), (),
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.NOT_READY)
        self.assertEqual(result.candidates[0].reason_codes, ("food_scope_mismatch",))
        self.assertEqual(result.candidates[1].reason_codes,
                         ("service_temperature_out_of_scope",))

    def test_incomplete_food_requirements_and_unapproved_review_fail_closed(self):
        card = _card(screenable=False)
        result = screen_package_candidates(
            card, "Dry snack", _audit(_reviewed("TEST_ONLY_A")), (),
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.reason_codes,
                         ("food_requirements_or_produce_route_incomplete",))
        invalid_audit = StructureReviewAudit(
            "not_approved", CATALOGUE_HASH, "d" * 64, (), (),
        )
        ready_card = _card()
        result = screen_package_candidates(
            ready_card, "Dry snack", invalid_audit, (),
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.reason_codes,
                         ("complete_structure_review_not_approved",))

    def test_equal_margin_keeps_a_shortlist_without_arbitrary_preference(self):
        card = _card()
        first, second = _reviewed("TEST_ONLY_A"), _reviewed("TEST_ONLY_B")
        evidence = tuple(
            _evidence(card, structure_id, mechanism, value)
            for structure_id in ("TEST_ONLY_A", "TEST_ONLY_B")
            for mechanism, value in (
                (ProtectionMechanism.OXYGEN_INGRESS, 5.0),
                (ProtectionMechanism.MOISTURE_GAIN, 6.0),
            )
        )
        result = screen_package_candidates(
            card, "Dry snack", _audit(first, second), evidence,
            current_material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(result.status, RecommendationStatus.PRELIMINARY_SHORTLIST)
        self.assertIsNone(result.preferred_structure_id)
        self.assertIsNone(result.ranking_basis)
        self.assertEqual([item.protection_rank for item in result.candidates], [1, 1])


if __name__ == "__main__":
    unittest.main()
