"""TEST_ONLY scenarios exercise supplier lookup; they are not training data."""

import unittest
from dataclasses import replace
from pathlib import Path

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.catalogue_leads import find_supplier_application_leads
from packsense.contracts import HandlingSeverity, ScenarioInput, StorageType


CATALOGUE = Path(__file__).resolve().parents[1] / "data" / "public_catalogue_candidates.v1.json"


def _scenario(**changes):
    base = ScenarioInput(
        record_id="TEST_ONLY_EDAMAME", commodity_type="edamame",
        moisture_content_pct=75.0, oil_fat_content_pct=3.0, pH=6.0,
        desired_shelf_life_days=7.0, storage_type=StorageType.CHILLED,
        storage_temperature_c=4.0, storage_relative_humidity_pct=90.0,
        transport_mode="road", transport_duration_hours=8.0,
        transport_temperature_c=8.0, transport_max_temperature_c=25.0,
        transport_handling_severity=HandlingSeverity.MEDIUM,
        net_pack_quantity=300.0, net_pack_quantity_unit="g",
    )
    return replace(base, **changes)


class SupplierApplicationLeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue, _ = load_candidate_catalogue(CATALOGUE)

    def _lead(self, scenario):
        report = find_supplier_application_leads(scenario, self.catalogue)
        self.assertFalse(report["model_prediction_available"])
        self.assertEqual(0, report["approved_structure_count"])
        self.assertIsNone(report["recommended_structure_id"])
        return report

    def test_exact_supplier_food_quantity_temperature_use_is_still_unapproved(self):
        report = self._lead(_scenario())
        self.assertEqual("published_food_application_found", report["status"])
        self.assertEqual(1, len(report["leads"]))
        lead = report["leads"][0]
        self.assertEqual("SUMITOMO-PPLUS-EY7K7", lead["candidate_id"])
        self.assertEqual("exact_name", lead["food_name_match"])
        self.assertEqual("published_food_quantity_temperature_match_unverified",
                         lead["application_status"])
        self.assertEqual([], lead["reason_codes"])
        self.assertIn("food_package_suitability_unverified", lead["approval_blockers"])

    def test_equivalent_mass_units_are_compared_without_guessing(self):
        report = self._lead(_scenario(net_pack_quantity=0.3,
                                      net_pack_quantity_unit="kg"))
        self.assertEqual([], report["leads"][0]["reason_codes"])

    def test_warm_excursion_longer_than_supplier_allowance_is_unresolved(self):
        report = self._lead(_scenario(transport_duration_hours=9.0))
        self.assertIn("transport_exposure_outside_published_use",
                      report["leads"][0]["reason_codes"])

    def test_quantity_and_storage_mismatch_remain_visible(self):
        report = self._lead(_scenario(net_pack_quantity=500,
                                      storage_temperature_c=11))
        reasons = report["leads"][0]["reason_codes"]
        self.assertIn("pack_quantity_outside_published_use", reasons)
        self.assertIn("storage_temperature_outside_published_use", reasons)

    def test_raw_name_variant_is_not_approved_as_exact_food(self):
        report = self._lead(_scenario(commodity_type="Broccoli, raw",
                                      net_pack_quantity=400))
        self.assertEqual("raw_name_variant_unreviewed",
                         report["leads"][0]["food_name_match"])
        self.assertIn("food_identity_requires_review",
                      report["leads"][0]["reason_codes"])

    def test_processed_food_does_not_inherit_fresh_food_application(self):
        report = self._lead(_scenario(commodity_type="Broccoli, cooked"))
        self.assertEqual("no_published_food_application_match", report["status"])
        self.assertEqual([], report["leads"])

    def test_inner_liner_cannot_be_treated_as_complete_bag(self):
        report = self._lead(_scenario(commodity_type="apple",
                                      net_pack_quantity=10,
                                      net_pack_quantity_unit="kg",
                                      transport_temperature_c=4,
                                      transport_max_temperature_c=9))
        self.assertEqual("SUMITOMO-PPLUS-PK601", report["leads"][0]["candidate_id"])
        self.assertIn("outer_package_not_specified", report["leads"][0]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
