"""TEST_ONLY grade comparisons; no fixture is a training or suitability label."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.contracts import (
    BarrierObservation, EvidenceBasis, FoodReference, HandlingSeverity,
    MaterialGrade, ScenarioInput, StorageType,
)
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.grade_reference import compare_grade_barriers
from packsense.ingestion import ParsedScenarioRow, ScenarioAudit
from packsense.masters import MaterialMasterEntry, MasterAudit, FoodMasterEntry
from packsense.recommendation_batch import build_batch_recommendations
from packsense.requirements import (
    AssessmentDecision, ProtectionAssessment, ProtectionMechanism,
    derive_requirement_card,
)
from packsense.units import MATERIAL_RATE_UNITS


def _scenario() -> ScenarioInput:
    return ScenarioInput(
        record_id="TEST_ONLY_CASE", commodity_type="TEST_ONLY_FOOD",
        moisture_content_pct=5.0, oil_fat_content_pct=10.0, pH=6.0,
        desired_shelf_life_days=20.0, storage_type=StorageType.CHILLED,
        storage_temperature_c=4.0, storage_relative_humidity_pct=80.0,
        transport_mode="TEST_ONLY_MODE", transport_duration_hours=12.0,
        transport_temperature_c=6.0, transport_max_temperature_c=9.0,
        transport_handling_severity=HandlingSeverity.MEDIUM,
        net_pack_quantity=100.0, net_pack_quantity_unit="g",
        food_reference_id="TEST_ONLY_FOOD_ID",
    )


def _food() -> FoodReference:
    return FoodReference(
        "TEST_ONLY_FOOD_ID", "TEST_ONLY_FOOD", None, 5.0, 10.0, 6.0,
        "TEST_ONLY_REFERENCE", None, None, None, "TEST_ONLY_SOURCE",
    )


def _assessments(*, oxygen=True, moisture=True):
    result = []
    for mechanism, limited in (
        (ProtectionMechanism.OXYGEN_INGRESS, oxygen),
        (ProtectionMechanism.MOISTURE_GAIN, moisture),
        (ProtectionMechanism.MOISTURE_LOSS, False),
    ):
        result.append(ProtectionAssessment(
            food_reference_id="TEST_ONLY_FOOD_ID", mechanism=mechanism,
            decision=(AssessmentDecision.LIMIT if limited
                      else AssessmentDecision.NOT_REQUIRED),
            max_cumulative_transfer=10.0 if limited else None,
            transfer_unit=("mmol_o2_per_pack" if mechanism is ProtectionMechanism.OXYGEN_INGRESS
                           else "g_h2o_per_pack") if limited else None,
            pack_quantity=100.0, pack_quantity_unit="g",
            valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
            valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
            assessment_rationale="TEST_ONLY reviewed limit",
            source_id="TEST_ONLY_SOURCE", source_locator="TEST_ONLY_LOCATOR",
            approval_id="TEST_ONLY_APPROVAL", evidence_basis=EvidenceBasis.MEASURED,
        ))
    return tuple(result)


def _card(*, route="confirmed_non_respiring", assessments=None):
    scenario = _scenario()
    enriched = EnrichedScenario(
        scenario, _food(), 2, "a" * 64, "reported_reference", route,
        exposure_profile(scenario),
        "TEST_ONLY_ROUTE_SOURCE" if route == "confirmed_non_respiring" else None,
        "TEST_ONLY_ROUTE_APPROVAL" if route == "confirmed_non_respiring" else None,
    )
    return derive_requirement_card(enriched, _assessments() if assessments is None else assessments)


def _observation(value, kind, *, temperature=None, humidity=None,
                 basis=EvidenceBasis.SUPPLIER_REPORTED, method=None):
    return BarrierObservation(
        value=value, unit=MATERIAL_RATE_UNITS[
            "otr_cm3_m2_day" if kind == "otr" else "wvtr_g_m2_day"
        ],
        test_temperature_c=23.0 if temperature is None else temperature,
        test_relative_humidity_pct=(humidity if humidity is not None else
                                    0.0 if kind == "otr" else 90.0),
        test_method=method or ("ASTM D3985" if kind == "otr" else "ASTM F1249"),
        basis=basis, source_url="https://example.com/TEST_ONLY_supplier-sheet",
    )


def _material(material_id, otr, wvtr, *, otr_temperature=23.0,
              wvtr_temperature=38.0, basis=EvidenceBasis.SUPPLIER_REPORTED):
    grade = MaterialGrade(
        material_id=material_id, manufacturer="TEST_ONLY_MANUFACTURER",
        grade=material_id, material_family="TEST_ONLY_FAMILY",
        film_structure="TEST_ONLY_FILM", film_role="TEST_ONLY_ROLE",
        thickness_um=30.0,
        otr=_observation(otr, "otr", temperature=otr_temperature, basis=basis),
        co2tr=None,
        wvtr=_observation(wvtr, "wvtr", temperature=wvtr_temperature, basis=basis),
        co2_training_label=False,
        seal_status="TEST_ONLY_UNVERIFIED",
        food_contact_statement="TEST_ONLY_UNVERIFIED",
        model_use_status="TEST_ONLY_REFERENCE",
        source_url="https://example.com/TEST_ONLY_supplier-sheet",
    )
    return MaterialMasterEntry(
        2, grade, None, "TEST_ONLY_supplier", "TEST_ONLY_unknown", None, None,
    )


def _materials(*entries):
    return MasterAudit(
        "TEST_ONLY_material.xlsx", "b" * 64, "TEST_ONLY_SHEET",
        len(entries), tuple(entries), (),
    )


class GradeReferenceTests(unittest.TestCase):
    def test_pareto_front_is_only_within_identical_test_conditions(self):
        materials = _materials(
            _material("A", 1.0, 5.0),
            _material("B", 2.0, 4.0),
            _material("C", 3.0, 6.0),
            _material("D", 0.5, 0.5, otr_temperature=22.0),
        )
        result = compare_grade_barriers(_card(), materials)
        self.assertEqual(result["status"], "reference_comparison")
        self.assertEqual(result["objectives"], ["otr", "wvtr"])
        self.assertEqual(len(result["reference_cohorts"]), 1)
        cohort = result["reference_cohorts"][0]
        self.assertEqual(cohort["compared_grade_count"], 3)
        self.assertEqual([x["material_id"] for x in cohort["frontier_grades"]],
                         ["A", "B"])
        self.assertEqual(cohort["dominated_grade_ids"], ["C"])
        self.assertEqual(result["grades_in_singleton_cohorts"], ["D"])
        self.assertEqual(cohort["test_conditions"][0]["temperature_c"], 23.0)
        self.assertEqual(cohort["test_conditions"][1]["temperature_c"], 38.0)
        self.assertFalse(result["scenario_condition_performance_verified"])
        self.assertFalse(result["material_suitability_established"])
        self.assertIsNone(result["preferred_material_id"])
        json.dumps(result, allow_nan=False)

    def test_missing_estimated_and_incomplete_observations_are_excluded(self):
        good = _material("A", 1.0, 5.0)
        incomplete = _material("B", 2.0, 6.0)
        incomplete = replace(incomplete, grade=replace(
            incomplete.grade, wvtr=replace(incomplete.grade.wvtr, test_method=None),
        ))
        materials = _materials(
            good, incomplete,
            _material("C", 0.1, 0.1, basis=EvidenceBasis.ESTIMATED),
        )
        result = compare_grade_barriers(_card(), materials)
        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["reason_codes"], ["no_multi_grade_comparable_test_cohort"])
        self.assertEqual(result["grades_missing_comparable_evidence"], ["B", "C"])
        self.assertEqual(result["grades_in_singleton_cohorts"], ["A"])

    def test_only_source_limited_objectives_are_compared(self):
        card = _card(assessments=_assessments(oxygen=True, moisture=False))
        materials = _materials(_material("A", 1.0, 9.0), _material("B", 2.0, 1.0))
        result = compare_grade_barriers(card, materials)
        self.assertEqual(result["objectives"], ["otr"])
        self.assertEqual([x["material_id"] for x in
                          result["reference_cohorts"][0]["frontier_grades"]], ["A"])

    def test_unreviewed_route_or_food_needs_cannot_start_comparison(self):
        materials = _materials(_material("A", 1.0, 5.0), _material("B", 2.0, 6.0))
        self.assertEqual(compare_grade_barriers(
            _card(route="unclassified"), materials,
        )["reason_codes"], ["non_respiring_route_not_confirmed",
                            "food_protection_assessments_incomplete"])
        self.assertEqual(compare_grade_barriers(
            _card(assessments=()), materials,
        )["reason_codes"], ["food_protection_assessments_incomplete"])
        self.assertEqual(compare_grade_barriers(
            _card(assessments=_assessments(oxygen=False, moisture=False)), materials,
        )["reason_codes"], ["no_source_limited_barrier_objective"])

    def test_batch_comparison_cannot_change_package_recommendation_status(self):
        scenario = _scenario()
        scenarios = ScenarioAudit(
            "TEST_ONLY_scenarios.csv", "c" * 64, None, (),
            (ParsedScenarioRow(2, {"record_id": scenario.record_id}, scenario, ()),),
        )
        foods = MasterAudit(
            "TEST_ONLY_food.xlsx", "a" * 64, "TEST_ONLY_SHEET", 1,
            (FoodMasterEntry(2, _food(), "reported_reference"),), (),
        )
        materials = _materials(_material("A", 1.0, 5.0), _material("B", 2.0, 6.0))
        # The comparison runs only after the ordinary scenario/food/route gate.
        from packsense.produce_route import ProduceRoute, RouteEvidence
        route = RouteEvidence(
            "TEST_ONLY_FOOD_ID", ProduceRoute.NON_RESPIRING,
            "TEST_ONLY_ROUTE_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_APPROVAL",
        )
        candidates, candidate_hash = load_candidate_catalogue(
            Path(__file__).resolve().parents[1] / "data" /
            "public_catalogue_candidates.v1.json"
        )
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="d" * 64,
            assessments=_assessments(), assessment_register_sha256="e" * 64,
            include_grade_reference_comparison=True,
            public_candidates=candidates,
            public_candidate_catalogue_sha256=candidate_hash,
        )
        row = report["rows"][0]
        self.assertEqual(row["status"], "not_ready")
        self.assertEqual(row["grade_reference_comparison"]["status"],
                         "reference_comparison")
        self.assertIsNone(row["recommendation"]["preliminary_preferred_structure_id"])
        self.assertEqual(report["grade_reference_frontier_rows"], 1)
        self.assertEqual(report["supplier_application_lookup_rows"], 1)
        self.assertEqual(report["supplier_application_lead_count"], 0)
        self.assertFalse(report["package_feasible"])
        self.assertFalse(report["shelf_life_predicted"])


if __name__ == "__main__":
    unittest.main()
