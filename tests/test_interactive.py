"""TEST_ONLY form intake fixtures; never material-model training data."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packsense.contracts import FoodReference
from packsense.interactive import IntakeError, scenario_row_from_submission, search_foods
from packsense.masters import FoodMasterEntry, MasterAudit
from packsense.web_server import AppSources, run_interactive_scenario


FOOD_HASH = "a" * 64


def food_audit() -> MasterAudit[FoodMasterEntry]:
    def entry(food_id, name, ph):
        return FoodMasterEntry(2, FoodReference(
            food_id=food_id, commodity_type=name, food_group="TEST_ONLY_GROUP",
            moisture_content_pct=90, oil_fat_content_pct=1, pH=ph,
            pH_basis="Reported reference value; not product measurement" if ph is not None else None,
            respiration_rate=270, respiration_rate_unit="mg CO2/kg/h",
            respiration_reference_temperature_c=20,
            source_citations="TEST_ONLY https://example.invalid/food",
        ), "reported_reference" if ph is not None else "missing")
    return MasterAudit("TEST_ONLY_food.xlsx", FOOD_HASH, "Food inputs", 2, (
        entry("TEST_ONLY_READY", "Asparagus, green, raw", 6.2),
        entry("TEST_ONLY_INCOMPLETE", "Asparagus, other, raw", None),
    ), ())


def submission() -> dict:
    return {
        "food_reference_id": "TEST_ONLY_READY", "food_master_sha256": FOOD_HASH,
        "desired_shelf_life_days": 5, "storage_type": "chilled",
        "storage_temperature_c": 4, "storage_relative_humidity_pct": 90,
        "transport_mode": "road", "transport_duration_hours": 8,
        "transport_temperature_c": 5, "transport_max_temperature_c": 9,
        "transport_handling_severity": "medium", "net_pack_quantity": 150,
        "net_pack_quantity_unit": "g",
    }


class InteractiveTests(unittest.TestCase):
    def test_search_returns_exact_master_profile_with_missingness(self):
        result = search_foods(food_audit(), " asparagus ")
        self.assertEqual("food-lookup-v1", result["contract_version"])
        self.assertEqual(2, result["total_matches"])
        self.assertEqual(1, result["form_ready_matches"])
        self.assertEqual("TEST_ONLY_READY", result["foods"][0]["food_reference_id"])
        self.assertEqual("reported_reference", result["foods"][0]["pH_evidence"])
        self.assertEqual(["pH"], result["foods"][1]["missing_reference_properties"])

    def test_submission_uses_reference_properties_and_does_not_accept_overrides(self):
        row, profile = scenario_row_from_submission(submission(), food_audit())
        self.assertEqual(6.2, row["pH"])
        self.assertEqual(270, row["respiration_rate"])
        self.assertEqual("TEST_ONLY_READY", row["food_reference_id"])
        self.assertEqual("TEST_ONLY https://example.invalid/food", profile["source_citations"])
        changed = submission() | {"pH": 2.0}
        with self.assertRaisesRegex(IntakeError, "Unsupported input field: pH"):
            scenario_row_from_submission(changed, food_audit())

    def test_stale_missing_and_invalid_values_are_rejected(self):
        for changed, field in (
            ({"food_master_sha256": "b" * 64}, "food_reference_id"),
            ({"food_reference_id": "TEST_ONLY_INCOMPLETE"}, "food_reference_id"),
            ({"net_pack_quantity": True}, "net_pack_quantity"),
            ({"transport_mode": []}, "transport_mode"),
            ({"transport_max_temperature_c": 3}, "transport_max_temperature_c"),
            ({"storage_relative_humidity_pct": 110}, "storage_relative_humidity_pct"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(IntakeError) as error:
                    scenario_row_from_submission(submission() | changed, food_audit())
                self.assertEqual(field, error.exception.field)

    def test_interactive_run_passes_one_real_input_row_to_existing_batch_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = AppSources(food_master=root / "TEST_ONLY_food.xlsx", material_master=root / "TEST_ONLY_material.xlsx")

            def backend(configured):
                with configured.scenarios.open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(1, len(rows))
                self.assertEqual("6.2", rows[0]["pH"])
                self.assertEqual("150", rows[0]["net_pack_quantity"])
                self.assertEqual("TEST_ONLY_READY", rows[0]["food_reference_id"])
                return {"trace": {"food_master_sha256": FOOD_HASH}, "rows": [{"status": "not_ready"}]}

            with patch("packsense.web_server.run_configured_batch", side_effect=backend):
                result = run_interactive_scenario(sources, food_audit(), submission())
            self.assertEqual("browser_submitted", result["input_origin"])
            self.assertEqual("not_ready", result["report"]["rows"][0]["status"])


if __name__ == "__main__":
    unittest.main()
