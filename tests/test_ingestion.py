"""Input validation tests; no fabricated food or package observations."""

import tempfile
import unittest
from pathlib import Path

from packsense.ingestion import (
    InputSchemaError,
    _canonical_quantity,
    _header,
    _number,
    _parse_row,
    audit_scenarios,
)
from packsense.units import SCENARIO_REQUIRED_COLUMNS, SCENARIO_RESPIRATION_COLUMNS


class ColumnTests(unittest.TestCase):
    def test_header_checks_required_fields_and_duplicates(self) -> None:
        _header(SCENARIO_REQUIRED_COLUMNS)
        with self.assertRaisesRegex(InputSchemaError, "missing required columns"):
            _header(SCENARIO_REQUIRED_COLUMNS[:-1])
        with self.assertRaisesRegex(InputSchemaError, "duplicate header"):
            _header(SCENARIO_REQUIRED_COLUMNS + ("record_id",))

    def test_respiration_headers_are_all_or_none(self) -> None:
        _header(SCENARIO_REQUIRED_COLUMNS + SCENARIO_RESPIRATION_COLUMNS)
        with self.assertRaisesRegex(InputSchemaError, "respiration columns"):
            _header(SCENARIO_REQUIRED_COLUMNS + SCENARIO_RESPIRATION_COLUMNS[:1])

    def test_header_only_csv_has_no_scenario_records(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "columns.csv")
            path.write_text(",".join(SCENARIO_REQUIRED_COLUMNS) + "\n", encoding="utf-8")
            audit = audit_scenarios(path)
        self.assertEqual(audit.report()["total_rows"], 0)
        self.assertEqual(audit.report()["schema_valid_rows"], 0)
        self.assertEqual(len(audit.source_sha256), 64)


class ValueTests(unittest.TestCase):
    def test_percentage_ph_and_positive_quantities(self) -> None:
        self.assertEqual(_number("75.5", "moisture_content_pct"), 75.5)
        for field, value in (
            ("moisture_content_pct", 101),
            ("pH", 15),
            ("desired_shelf_life_days", 0),
            ("transport_duration_hours", -1),
            ("storage_temperature_c", -274),
            ("pH", float("nan")),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    _number(value, field)

    def test_pack_quantity_conversion_does_not_mix_dimensions(self) -> None:
        self.assertEqual(_canonical_quantity(1, "kg"), (1000, "g"))
        self.assertEqual(_canonical_quantity(1, "L"), (1000, "mL"))
        self.assertEqual(_canonical_quantity(1, "mL"), (1, "mL"))
        with self.assertRaises(ValueError):
            _canonical_quantity(1, "oz")

    def test_missing_values_are_exceptions_not_estimates(self) -> None:
        parsed = _parse_row({}, 2, False, set())
        self.assertIsNone(parsed.scenario)
        self.assertEqual(
            {issue.field for issue in parsed.issues}, set(SCENARIO_REQUIRED_COLUMNS)
        )

    def test_partial_respiration_is_not_accepted(self) -> None:
        parsed = _parse_row({"respiration_rate": 1}, 2, False, set())
        codes = {(issue.field, issue.code) for issue in parsed.issues}
        self.assertIn(("respiration_rate_unit", "incomplete_respiration"), codes)
        self.assertIn(("respiration_reference_temperature_c", "incomplete_respiration"), codes)

    def test_cross_field_and_formula_checks(self) -> None:
        parsed = _parse_row(
            {
                "storage_type": "frozen",
                "storage_temperature_c": 5,
                "transport_temperature_c": 10,
                "transport_max_temperature_c": 8,
            },
            2,
            False,
            {"storage_temperature_c"},
        )
        codes = {(issue.field, issue.code) for issue in parsed.issues}
        self.assertIn(("storage_temperature_c", "formula_cell"), codes)
        self.assertIn(("transport_max_temperature_c", "inconsistent_temperature"), codes)

        parsed = _parse_row({"storage_type": "frozen", "storage_temperature_c": 5}, 2, True, set())
        codes = {(issue.field, issue.code) for issue in parsed.issues}
        self.assertIn(("record_id", "duplicate_id"), codes)
        self.assertIn(("storage_temperature_c", "inconsistent_temperature"), codes)


if __name__ == "__main__":
    unittest.main()
