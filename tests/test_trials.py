"""Guard trial intake without inventing a valid training observation."""

import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from packsense.ingestion import InputSchemaError
from packsense.trials import (
    TRIAL_REQUIRED_COLUMNS,
    _failure_observed,
    _header,
    _number,
    audit_trial_outcomes,
)


class TrialIntakeTests(unittest.TestCase):
    def test_header_only_file_has_no_training_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(TRIAL_REQUIRED_COLUMNS)
            report = audit_trial_outcomes(path).report()
        self.assertEqual(report["total_rows"], 0)
        self.assertEqual(report["schema_valid_rows"], 0)
        self.assertEqual(report["observed_failure_rows"], 0)
        self.assertEqual(report["right_censored_rows"], 0)
        self.assertEqual(report["training_readiness"], "no_valid_trials")
        self.assertEqual(len(report["source_sha256"]), 64)

    def test_desired_shelf_life_cannot_enter_trial_table(self):
        with self.assertRaisesRegex(InputSchemaError, "unexpected trial columns: desired_shelf_life_days"):
            _header(TRIAL_REQUIRED_COLUMNS + ("desired_shelf_life_days",))

    def test_duplicate_and_partial_transport_headers_are_rejected(self):
        with self.assertRaisesRegex(InputSchemaError, "duplicate trial columns"):
            _header(TRIAL_REQUIRED_COLUMNS + ("trial_id",))
        with self.assertRaisesRegex(InputSchemaError, "all three transport columns"):
            _header(TRIAL_REQUIRED_COLUMNS + ("transport_temperature_c",))

    def test_blank_invalid_row_is_rejected_not_imputed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(TRIAL_REQUIRED_COLUMNS)
                writer.writerow(["unusable-source-row"] + [""] * (len(TRIAL_REQUIRED_COLUMNS) - 1))
            report = audit_trial_outcomes(path).report()
        self.assertEqual(report["schema_valid_rows"], 0)
        self.assertEqual(report["rejected_rows"], 1)
        self.assertIn("source_locator", {issue["field"] for issue in report["issues"]})
        self.assertIn("observed_days", {issue["field"] for issue in report["issues"]})

    def test_duplicate_ids_reject_all_occurrences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(TRIAL_REQUIRED_COLUMNS)
                blank = ["repeated-invalid-row"] + [""] * (len(TRIAL_REQUIRED_COLUMNS) - 1)
                writer.writerow(blank)
                writer.writerow(blank)
            report = audit_trial_outcomes(path).report()
        self.assertEqual(report["rejected_rows"], 2)
        self.assertEqual(sum(issue["code"] == "duplicate_id" for issue in report["issues"]), 2)

    def test_formula_cell_is_never_source_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(TRIAL_REQUIRED_COLUMNS)
            sheet.append(["invalid-formula-row"] + [None] * (len(TRIAL_REQUIRED_COLUMNS) - 1))
            sheet.cell(2, TRIAL_REQUIRED_COLUMNS.index("observed_days") + 1, "=1+1")
            workbook.save(path)
            workbook.close()
            report = audit_trial_outcomes(path).report()
        self.assertEqual(report["schema_valid_rows"], 0)
        self.assertIn("formula_cell", {issue["code"] for issue in report["issues"]})

    def test_same_source_batch_cannot_cross_split_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(TRIAL_REQUIRED_COLUMNS)
                for identifier, group in (("bad-a", "group-a"), ("bad-b", "group-b")):
                    row = dict.fromkeys(TRIAL_REQUIRED_COLUMNS, "")
                    row.update(trial_id=identifier, source_id="same-source",
                               batch_id="same-batch", trial_group_id=group)
                    writer.writerow([row[field] for field in TRIAL_REQUIRED_COLUMNS])
            report = audit_trial_outcomes(path).report()
        self.assertEqual(sum(issue["code"] == "batch_group_conflict"
                             for issue in report["issues"]), 2)

    def test_event_flag_does_not_turn_censoring_into_failure(self):
        self.assertFalse(_failure_observed("false"))
        self.assertFalse(_failure_observed(0))
        self.assertTrue(_failure_observed("true"))
        with self.assertRaises(ValueError):
            _failure_observed("not sure")

    def test_physical_ranges_and_finite_values(self):
        for value, field in ((0, "observed_days"), (-1, "package_area_m2"),
                             (101, "storage_relative_humidity_pct"),
                             (-274, "storage_temperature_c"),
                             ("nan", "fill_mass_g")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                _number(value, field, required=True)


if __name__ == "__main__":
    unittest.main()
