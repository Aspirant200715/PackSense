"""TEST_ONLY reports verify frontend states; they are not training data."""

import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.catalogue_leads import find_supplier_application_leads
from packsense.frontend_contract import (
    CONTRACT_VERSION, project_frontend_decisions,
)
from packsense.recommendation_output import EXPECTED_BATCH_VERSION
from packsense.recommendation_batch import build_batch_recommendations
from tests.test_recommendation_batch import _scenario, _sources


def _report():
    candidate = {
        "structure_id": "TEST_ONLY_REVIEWED_PACKAGE",
        "pack_format": "TEST_ONLY pouch",
        "status": "eligible_for_shortlist",
        "reason_codes": [],
        "layers": [{"grade_id": "TEST_ONLY_GRADE", "thickness_um": 80.0,
                    "role": "sealant", "is_food_contact": True}],
        "protection_rank": 1,
        "service_temperature_min_c": 0.0,
        "service_temperature_max_c": 10.0,
    }
    return {
        "batch_version": EXPECTED_BATCH_VERSION,
        "package_feasible": False,
        "shelf_life_predicted": False,
        "scenario_sha256": "a" * 64,
        "food_master_sha256": "b" * 64,
        "material_master_sha256": "c" * 64,
        "rows": [
            {"row_number": 2, "record_id": "TEST_ONLY_INVALID", "status": "exception",
             "issues": [{"field": "pH", "code": "missing_value", "message": "required"}],
             "requirement_card": None, "recommendation": None},
            {"row_number": 3, "record_id": "TEST_ONLY_GAP", "status": "not_ready",
             "issues": [],
             "requirement_card": {
                 "gaps": ["oxygen_limit_missing"],
                 "target_shelf_life_days": 30.0,
                 "exposures": [{"phase": "storage", "temperature_c": 4.0,
                                "relative_humidity_pct": 80.0}],
             },
             "recommendation": {
                 "record_id": "TEST_ONLY_GAP", "food_reference_id": "TEST_ONLY_FOOD",
                 "status": "not_ready", "package_feasible": False,
                 "shelf_life_predicted": False, "reason_codes": ["food_needs_missing"],
                 "warnings": [], "candidates": [],
                 "preliminary_preferred_structure_id": None,
             }},
            {"row_number": 4, "record_id": "TEST_ONLY_SHORTLIST",
             "status": "preliminary_shortlist", "issues": [],
             "requirement_card": {
                 "gaps": ["light_sensitivity_unassessed"],
                 "target_shelf_life_days": 30.0,
                 "exposures": [{"phase": "storage", "temperature_c": 4.0,
                                "relative_humidity_pct": 80.0}],
             },
             "recommendation": {
                 "record_id": "TEST_ONLY_SHORTLIST", "food_reference_id": "TEST_ONLY_FOOD",
                 "status": "preliminary_shortlist", "package_feasible": False,
                 "shelf_life_predicted": False, "reason_codes": [],
                 "warnings": ["light_sensitivity_unassessed"],
                 "candidates": [candidate],
                 "preliminary_preferred_structure_id": "TEST_ONLY_REVIEWED_PACKAGE",
             }},
        ],
    }


class FrontendContractTests(unittest.TestCase):
    def test_projects_real_source_linked_supplier_application_as_research_only(self):
        catalogue_path = (Path(__file__).resolve().parents[1] / "data" /
                          "public_catalogue_candidates.v1.json")
        catalogue, digest = load_candidate_catalogue(catalogue_path)
        scenario = replace(
            _scenario("TEST_ONLY_GAP"), commodity_type="edamame",
            net_pack_quantity=300.0, transport_duration_hours=8.0,
            transport_temperature_c=8.0, transport_max_temperature_c=25.0,
        )
        batch = _report()
        batch["public_candidate_catalogue_sha256"] = digest
        batch["rows"][1]["supplier_application_lookup"] = (
            find_supplier_application_leads(scenario, catalogue)
        )
        # The catalogue is supplied to the whole batch, including other valid rows.
        batch["rows"][2]["supplier_application_lookup"] = (
            find_supplier_application_leads(
                replace(scenario, record_id="TEST_ONLY_SHORTLIST",
                        commodity_type="TEST_ONLY_OTHER_FOOD"), catalogue,
            )
        )
        projected = project_frontend_decisions(batch)
        lookup = projected["rows"][1]["supplier_application_lookup"]
        self.assertEqual("SUMITOMO-PPLUS-EY7K7", lookup["leads"][0]["candidate_id"])
        self.assertEqual("published_food_quantity_temperature_match_unverified",
                         lookup["leads"][0]["application_status"])
        self.assertEqual("pending", lookup["leads"][0]["source_rights_review_status"])
        self.assertEqual(0, lookup["approved_structure_count"])
        self.assertIsNone(projected["rows"][1]["material_prediction"])
        self.assertEqual("not_ready", projected["rows"][1]["status"])
        self.assertIsNone(projected["rows"][0]["supplier_application_lookup"])
        self.assertEqual("no_published_food_application_match",
                         projected["rows"][2]["supplier_application_lookup"]["status"])
        tampered = copy.deepcopy(batch)
        tampered["rows"][1]["supplier_application_lookup"]["leads"][0][
            "source_url"] = "javascript:alert(1)"
        with self.assertRaisesRegex(ValueError, "invalid source URL"):
            project_frontend_decisions(tampered)

    def test_rejects_supplier_lead_promoted_without_evidence(self):
        batch = _report()
        batch["public_candidate_catalogue_sha256"] = "d" * 64
        batch["rows"][1]["supplier_application_lookup"] = {
            "lookup_version": "supplier-application-lookup-v1",
            "record_id": "TEST_ONLY_GAP", "catalogue_id": "TEST_ONLY_CATALOGUE",
            "status": "no_published_food_application_match", "leads": [],
            "approved_structure_count": 1,
            "recommended_structure_id": "TEST_ONLY_PACKAGE",
            "model_prediction_available": True,
        }
        with self.assertRaisesRegex(ValueError, "cannot claim package approval"):
            project_frontend_decisions(batch)
        batch["rows"][1]["supplier_application_lookup"] = None
        with self.assertRaisesRegex(ValueError, "no row lookup"):
            project_frontend_decisions(batch)

    def test_projects_real_batch_contract_without_source_evidence(self):
        batch = build_batch_recommendations(*_sources(_scenario()))
        result = project_frontend_decisions(batch)
        self.assertEqual("not_ready", result["rows"][0]["status"])
        self.assertEqual("TEST_ONLY_FOOD", result["rows"][0]["scenario"]["commodity_type"])
        self.assertEqual(100.0, result["rows"][0]["scenario"]["net_pack_quantity"])
        self.assertEqual("unclassified", result["rows"][0]["produce_route_status"])
        self.assertFalse(result["rows"][0]["candidate_screening_allowed"])
        self.assertEqual(batch["scenario_sha256"], result["trace"]["scenario_sha256"])
        self.assertIsNone(result["rows"][0]["material_prediction"])

    def test_projects_all_states_without_releasing_prediction(self):
        result = project_frontend_decisions(_report())
        self.assertEqual(CONTRACT_VERSION, result["contract_version"])
        self.assertEqual(3, result["total_rows"])
        self.assertEqual("not_deployed", result["model"]["status"])
        self.assertFalse(result["model"]["prediction_available"])
        self.assertEqual("withheld", result["recommendation_release_status"])
        invalid, gap, shortlist = result["rows"]
        self.assertEqual("exception", invalid["status"])
        self.assertIsNone(invalid["scenario"])
        self.assertIsNone(invalid["produce_route_status"])
        self.assertEqual("pH", invalid["input_issues"][0]["field"])
        self.assertEqual([], invalid["screened_candidates"])
        self.assertEqual("not_ready", gap["status"])
        self.assertEqual(["oxygen_limit_missing"], gap["requirement_gaps"])
        self.assertEqual("preliminary_shortlist", shortlist["status"])
        self.assertEqual("TEST_ONLY_REVIEWED_PACKAGE",
                         shortlist["preliminary_preferred_structure_id"])
        self.assertEqual("eligible_for_shortlist",
                         shortlist["screened_candidates"][0]["status"])
        for row in result["rows"]:
            self.assertIsNone(row["recommended_structure_id"])
            self.assertIsNone(row["material_prediction"])
            self.assertIsNone(row["predicted_shelf_life_days"])
            self.assertFalse(row["package_feasible"])
        json.dumps(result, allow_nan=False)

    def test_rejects_any_claim_of_package_feasibility(self):
        report = _report()
        report["package_feasible"] = True
        with self.assertRaisesRegex(ValueError, "cannot claim package feasibility"):
            project_frontend_decisions(report)
        report = _report()
        report["rows"][2]["recommendation"]["package_feasible"] = True
        with self.assertRaisesRegex(ValueError, "contradicts preliminary"):
            project_frontend_decisions(report)

    def test_rejects_fake_shortlist_or_preference(self):
        report = _report()
        report["rows"][2]["recommendation"]["candidates"] = []
        with self.assertRaisesRegex(ValueError, "shortlist status contradicts"):
            project_frontend_decisions(report)
        report = _report()
        report["rows"][2]["recommendation"][
            "preliminary_preferred_structure_id"] = "TEST_ONLY_UNKNOWN"
        with self.assertRaisesRegex(ValueError, "preliminary preference"):
            project_frontend_decisions(report)

    def test_rejects_mismatched_record_and_input_exception_with_output(self):
        report = _report()
        report["rows"][1]["recommendation"]["record_id"] = "TEST_ONLY_OTHER"
        with self.assertRaisesRegex(ValueError, "record ID mismatch"):
            project_frontend_decisions(report)
        report = _report()
        report["rows"][0]["recommendation"] = copy.deepcopy(
            report["rows"][1]["recommendation"])
        with self.assertRaisesRegex(ValueError, "input exception cannot carry"):
            project_frontend_decisions(report)

    def test_rejects_invalid_route_projection_fields(self):
        report = _report()
        report["rows"][1]["requirement_card"]["produce_route_status"] = "approved_produce"
        with self.assertRaisesRegex(ValueError, "unsupported produce route"):
            project_frontend_decisions(report)
        report = _report()
        report["rows"][1]["requirement_card"]["candidate_screening_allowed"] = "yes"
        with self.assertRaisesRegex(ValueError, "invalid screening permission"):
            project_frontend_decisions(report)


if __name__ == "__main__":
    unittest.main()
