"""TEST_ONLY batch objects verify the pipeline; they are not training records."""

import json
import unittest
from dataclasses import replace

from packsense.candidate_transfer import FinishedPackageTransferEvidence
from packsense.contracts import (
    EvidenceBasis, FoodReference, HandlingSeverity, PackageStructure,
    ScenarioInput, StorageType, StructureLayer,
)
from packsense.enrichment import enrich_scenarios
from packsense.ingestion import IngestionIssue, ParsedScenarioRow, ScenarioAudit
from packsense.masters import FoodMasterEntry, MasterAudit
from packsense.produce_route import ProduceRoute, RouteEvidence
from packsense.recommendation_batch import build_batch_recommendations
from packsense.recommendation_output import summarize_batch
from packsense.requirements import (
    AssessmentDecision, ProtectionAssessment, ProtectionMechanism,
    derive_requirement_card, scenario_fingerprint,
)
from packsense.structure_review import (
    CHECK_KINDS, EvidenceCheck, ReviewAttestedStructure, StructureReviewAudit,
)


FOOD_HASH = "a" * 64
MATERIAL_HASH = "b" * 64
CATALOGUE_HASH = "c" * 64
REVIEW_HASH = "d" * 64


def _scenario(record_id="TEST_ONLY_CASE"):
    return ScenarioInput(
        record_id=record_id, commodity_type="TEST_ONLY_FOOD",
        moisture_content_pct=5.0, oil_fat_content_pct=3.0, pH=6.0,
        desired_shelf_life_days=14.0, storage_type=StorageType.CHILLED,
        storage_temperature_c=4.0, storage_relative_humidity_pct=80.0,
        transport_mode="TEST_ONLY_MODE", transport_duration_hours=12.0,
        transport_temperature_c=6.0, transport_max_temperature_c=9.0,
        transport_handling_severity=HandlingSeverity.HIGH,
        net_pack_quantity=100.0, net_pack_quantity_unit="g",
        food_reference_id="TEST_ONLY_FOOD_ID",
    )


def _sources(*scenarios):
    rows = tuple(ParsedScenarioRow(
        index, {"record_id": scenario.record_id}, scenario, (),
    ) for index, scenario in enumerate(scenarios, start=2))
    scenario_audit = ScenarioAudit("TEST_ONLY.csv", "e" * 64, None, (), rows)
    food = FoodReference(
        "TEST_ONLY_FOOD_ID", "TEST_ONLY_FOOD", None, 5.0, 3.0, 6.0,
        "TEST_ONLY_REFERENCE", None, None, None, "TEST_ONLY_SOURCE",
    )
    foods = MasterAudit(
        "TEST_ONLY_food.xlsx", FOOD_HASH, "Food inputs", 1,
        (FoodMasterEntry(2, food, "reported_reference"),), (),
    )
    # The batch function uses the audited material hash. Grade parsing is
    # tested separately by the material importer.
    materials = MasterAudit("TEST_ONLY_material.xlsx", MATERIAL_HASH,
                            "Materials", 1, (object(),), ())
    return scenario_audit, foods, materials


def _route():
    return RouteEvidence(
        "TEST_ONLY_FOOD_ID", ProduceRoute.NON_RESPIRING,
        "TEST_ONLY_ROUTE_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_ROUTE_REVIEW",
    )


def _assessments():
    result = []
    for mechanism, limit in (
        (ProtectionMechanism.OXYGEN_INGRESS, 20.0),
        (ProtectionMechanism.MOISTURE_GAIN, 12.0),
        (ProtectionMechanism.MOISTURE_LOSS, None),
    ):
        result.append(ProtectionAssessment(
            food_reference_id="TEST_ONLY_FOOD_ID", mechanism=mechanism,
            decision=(AssessmentDecision.LIMIT if limit is not None
                      else AssessmentDecision.NOT_REQUIRED),
            max_cumulative_transfer=limit,
            transfer_unit=("mmol_o2_per_pack" if mechanism is ProtectionMechanism.OXYGEN_INGRESS
                           else "g_h2o_per_pack") if limit is not None else None,
            pack_quantity=100.0, pack_quantity_unit="g",
            valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
            valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
            assessment_rationale="TEST_ONLY reviewed mechanism",
            source_id=f"TEST_ONLY_{mechanism.value}", source_locator="TEST_ONLY_LOCATOR",
            approval_id=f"TEST_ONLY_APPROVAL_{mechanism.value}",
            evidence_basis=EvidenceBasis.MEASURED,
        ))
    return tuple(result)


def _review():
    structure = PackageStructure(
        "TEST_ONLY_STRUCTURE", "TEST_ONLY pouch",
        (StructureLayer("TEST_ONLY_GRADE", 20.0, "sealant", True),),
        "TEST_ONLY_GRADE", "TEST_ONLY_CONSTRUCTION", "TEST_ONLY_CONTACT",
        ("TEST_ONLY_FOOD",), 0.0, 10.0,
    )
    checks = tuple(EvidenceCheck(
        kind, (structure.structure_source_id if kind == "construction" else
               structure.food_contact_evidence_id if kind == "food_contact" else
               f"TEST_ONLY_{kind.upper()}_SOURCE"),
        "TEST_ONLY_LOCATOR", "e" * 64, "TEST_ONLY_REVIEW",
        "TEST_ONLY_RIGHTS", "pass",
    ) for kind in sorted(CHECK_KINDS))
    reviewed = ReviewAttestedStructure(
        structure, CATALOGUE_HASH, MATERIAL_HASH, REVIEW_HASH,
        "TEST_ONLY_REVIEW", tuple(check.review_id for check in checks), (), checks,
    )
    return StructureReviewAudit(
        "review_attested", CATALOGUE_HASH, REVIEW_HASH, (reviewed,), (),
    )


def _transfer(card, mechanism, amount):
    unit = ("mmol_o2_per_pack" if mechanism is ProtectionMechanism.OXYGEN_INGRESS
            else "g_h2o_per_pack")
    return FinishedPackageTransferEvidence(
        card.record_id, card.food_reference_id, "TEST_ONLY_STRUCTURE",
        CATALOGUE_HASH, scenario_fingerprint(card), mechanism, amount, unit,
        card.target_shelf_life_days, card.net_pack_quantity,
        card.net_pack_quantity_unit, 0.0, 10.0, 0.0, 100.0,
        f"TEST_ONLY_TRANSFER_{mechanism.value}", "TEST_ONLY_LOCATOR",
        "TEST_ONLY_TRANSFER_REVIEW", EvidenceBasis.MEASURED, None, None,
    )


class BatchRecommendationTests(unittest.TestCase):
    def test_no_external_registers_reports_not_ready(self):
        report = build_batch_recommendations(*_sources(_scenario()))
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(report["not_ready_rows"], 1)
        self.assertEqual(report["preliminary_shortlist_rows"], 0)
        self.assertEqual(report["rows"][0]["status"], "not_ready")
        self.assertIn("food_requirements_or_produce_route_incomplete",
                      report["rows"][0]["recommendation"]["reason_codes"])
        self.assertFalse(report["package_feasible"])
        self.assertFalse(report["shelf_life_predicted"])

    def test_complete_food_card_still_requires_structure_review(self):
        report = build_batch_recommendations(
            *_sources(_scenario()), routes=(_route(),), route_register_sha256="1" * 64,
            assessments=_assessments(), assessment_register_sha256="2" * 64,
        )
        self.assertEqual(report["rows"][0]["recommendation"]["reason_codes"],
                         ["complete_structure_review_missing"])
        self.assertEqual(report["structure_review_status"], "missing")

    def test_batch_joins_exact_scenario_and_preserves_input_exception(self):
        first, second = _scenario(), _scenario("TEST_ONLY_OTHER_CASE")
        scenarios, foods, materials = _sources(first, second)
        issue = IngestionIssue(4, "TEST_ONLY_INVALID", "pH", "missing_value", "required")
        scenarios = replace(scenarios, rows=(*scenarios.rows, ParsedScenarioRow(
            4, {"record_id": "TEST_ONLY_INVALID"}, None, (issue,),
        )))
        assessments = _assessments()
        enriched = enrich_scenarios(scenarios, foods, (_route(),), "1" * 64)
        first_card = derive_requirement_card(enriched.rows[0].enriched, assessments)
        transfers = (
            _transfer(first_card, ProtectionMechanism.OXYGEN_INGRESS, 5.0),
            _transfer(first_card, ProtectionMechanism.MOISTURE_GAIN, 6.0),
        )
        report = build_batch_recommendations(
            scenarios, foods, materials,
            routes=(_route(),), route_register_sha256="1" * 64,
            assessments=assessments, assessment_register_sha256="2" * 64,
            structure_review=_review(), transfer_evidence=transfers,
            transfer_register_sha256="3" * 64,
        )
        self.assertEqual(report["total_rows"], 3)
        self.assertEqual(report["preliminary_shortlist_rows"], 1)
        self.assertEqual(report["not_ready_rows"], 1)
        self.assertEqual(report["exception_rows"], 1)
        self.assertEqual(report["preliminary_preferred_rows"], 1)
        self.assertEqual(report["rows"][0]["recommendation"]
                         ["preliminary_preferred_structure_id"], "TEST_ONLY_STRUCTURE")
        self.assertEqual(report["rows"][0]["food_reference_row"], 2)
        self.assertEqual(report["rows"][1]["recommendation"]["candidates"][0]
                         ["reason_codes"], ["finished_package_transfer_missing"])
        self.assertIsNone(report["rows"][2]["recommendation"])
        self.assertEqual(report["rows"][2]["issues"][0]["code"], "missing_value")
        self.assertEqual(report["transfer_register_sha256"], "3" * 64)
        json.dumps(report, allow_nan=False)
        summary = summarize_batch(report)
        self.assertEqual([row["status"] for row in summary],
                         ["preliminary_shortlist", "not_ready", "exception"])
        self.assertEqual(summary[0]["preliminary_preferred_total_thickness_um"], 20.0)

    def test_rejected_master_rows_and_unversioned_evidence_are_refused(self):
        scenarios, foods, materials = _sources(_scenario())
        with self.assertRaisesRegex(ValueError, "no rejected rows"):
            build_batch_recommendations(
                scenarios, replace(foods, issues=(object(),)), materials,
            )
        with self.assertRaisesRegex(ValueError, "register hash"):
            build_batch_recommendations(
                scenarios, foods, materials, routes=(_route(),),
            )


if __name__ == "__main__":
    unittest.main()
