"""TEST_ONLY output rows verify that summaries preserve evidence gates."""

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packsense import recommendation_batch
from packsense.recommendation_output import summarize_batch, write_summary_csv


def _report():
    return {
        "batch_version": "basic-recommendation-batch-v1",
        "scenario_sha256": "a" * 64,
        "food_master_sha256": "b" * 64,
        "material_master_sha256": "c" * 64,
        "package_feasible": False,
        "shelf_life_predicted": False,
        "total_rows": 3,
        "exception_rows": 1,
        "rows": [
            {
                "row_number": 2, "record_id": "TEST_ONLY_BAD",
                "food_reference_row": None, "status": "exception",
                "issues": [{"field": "pH", "code": "missing_value", "message": "required"}],
                "requirement_card": None, "recommendation": None,
            },
            {
                "row_number": 3, "record_id": "TEST_ONLY_UNREADY",
                "food_reference_row": 12, "status": "not_ready", "issues": [],
                "requirement_card": {
                    "target_shelf_life_days": 14.0,
                    "gaps": ["oxygen_ingress_unassessed"],
                    "exposures": [
                        {"phase": "storage", "temperature_c": 4.0},
                        {"phase": "transport", "temperature_c": 6.0},
                        {"phase": "transport_max_excursion", "temperature_c": 9.0},
                    ],
                },
                "recommendation": {
                    "status": "not_ready", "food_reference_id": "TEST_ONLY_FOOD",
                    "package_feasible": False, "shelf_life_predicted": False,
                    "candidates": [], "preliminary_preferred_structure_id": None,
                    "reason_codes": ["food_requirements_or_produce_route_incomplete"],
                    "warnings": ["cost_and_sustainability_not_ranked"],
                },
            },
            {
                "row_number": 4, "record_id": "TEST_ONLY_SHORTLIST",
                "food_reference_row": 12, "status": "preliminary_shortlist", "issues": [],
                "requirement_card": {
                    "target_shelf_life_days": 14.0, "gaps": [],
                    "exposures": [
                        {"phase": "storage", "temperature_c": 4.0},
                        {"phase": "transport", "temperature_c": 6.0},
                        {"phase": "transport_max_excursion", "temperature_c": 9.0},
                    ],
                },
                "recommendation": {
                    "status": "preliminary_shortlist",
                    "food_reference_id": "TEST_ONLY_FOOD",
                    "package_feasible": False, "shelf_life_predicted": False,
                    "candidates": [
                        {
                            "structure_id": "TEST_ONLY_A", "status": "eligible_for_shortlist",
                            "pack_format": "TEST_ONLY pouch",
                            "layers": [{"thickness_um": 20.0}, {"thickness_um": 12.5}],
                        },
                        {
                            "structure_id": "TEST_ONLY_B", "status": "excluded",
                            "pack_format": "TEST_ONLY tray", "layers": [],
                        },
                    ],
                    "preliminary_preferred_structure_id": "TEST_ONLY_A",
                    "reason_codes": [], "warnings": ["cost_and_sustainability_not_ranked"],
                },
            },
        ],
    }


class SummaryOutputTests(unittest.TestCase):
    def test_one_row_per_input_and_no_unearned_claims(self):
        summary = summarize_batch(_report())
        self.assertEqual([row["status"] for row in summary],
                         ["exception", "not_ready", "preliminary_shortlist"])
        self.assertEqual(summary[0]["input_issue_codes"], "pH:missing_value")
        self.assertEqual(summary[0]["storage_temperature_c"], "")
        self.assertEqual(summary[1]["requirement_gap_codes"],
                         "oxygen_ingress_unassessed")
        self.assertEqual(summary[1]["preliminary_preferred_structure_id"], "")
        self.assertEqual(summary[2]["eligible_structure_ids"], "TEST_ONLY_A")
        self.assertEqual(summary[2]["preliminary_preferred_total_thickness_um"], 32.5)
        self.assertEqual(summary[2]["transport_max_temperature_c"], 9.0)
        self.assertTrue(all(row["package_feasible"] == "false" for row in summary))
        self.assertTrue(all(row["shelf_life_predicted"] == "false" for row in summary))

    def test_csv_is_one_sheet_equivalent_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, "TEST_ONLY_summary.csv")
            report = _report()
            report["rows"][0]["record_id"] = "=TEST_ONLY_FORMULA"
            report["rows"][2]["recommendation"]["candidates"][0]["pack_format"] = "@TEST_ONLY"
            self.assertEqual(write_summary_csv(report, target), 3)
            with target.open("r", encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[2]["preliminary_preferred_structure_id"], "TEST_ONLY_A")
            self.assertEqual(rows[0]["record_id"], "'=TEST_ONLY_FORMULA")
            self.assertEqual(rows[2]["preliminary_preferred_pack_format"], "'@TEST_ONLY")
            with self.assertRaises(FileExistsError):
                write_summary_csv(report, target)

    def test_invalid_claims_and_mismatched_preference_are_refused(self):
        report = _report()
        report["rows"][2]["recommendation"]["package_feasible"] = True
        with self.assertRaisesRegex(ValueError, "inconsistent recommendation claims"):
            summarize_batch(report)
        report = _report()
        report["rows"][2]["recommendation"]["preliminary_preferred_structure_id"] = "TEST_ONLY_B"
        with self.assertRaisesRegex(ValueError, "not an eligible candidate"):
            summarize_batch(report)
        report = _report()
        report["rows"][1]["requirement_card"]["exposures"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete exposure profile"):
            summarize_batch(report)
        report = _report()
        report["rows"][2]["recommendation"]["candidates"] = []
        with self.assertRaisesRegex(ValueError, "no eligible structure"):
            summarize_batch(report)

    def test_cli_writes_json_and_optional_csv_for_same_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            json_path = Path(folder, "TEST_ONLY_report.json")
            csv_path = Path(folder, "TEST_ONLY_summary.csv")
            argv = [
                "recommendation_batch", "TEST_ONLY_scenarios.csv",
                "--food-master", "TEST_ONLY_food.xlsx",
                "--material-master", "TEST_ONLY_material.xlsx",
                "--report", str(json_path), "--summary-csv", str(csv_path),
            ]
            with (patch.object(sys, "argv", argv),
                  patch.object(recommendation_batch, "audit_scenarios", return_value=object()),
                  patch.object(recommendation_batch, "load_food_references",
                               return_value=SimpleNamespace(issues=())),
                  patch.object(recommendation_batch, "load_material_grades",
                               return_value=SimpleNamespace(issues=())),
                  patch.object(recommendation_batch, "build_batch_recommendations",
                               return_value=_report()),
                  redirect_stdout(io.StringIO())):
                self.assertEqual(recommendation_batch.main(), 1)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["total_rows"], 3)
            with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 3)


if __name__ == "__main__":
    unittest.main()
