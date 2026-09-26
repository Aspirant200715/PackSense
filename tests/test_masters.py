"""Master import structure/evidence tests; no fabricated source records."""

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from packsense.contracts import EvidenceBasis
from packsense.masters import (
    FOOD_NUMBER_COLUMNS,
    FOOD_TEXT_COLUMNS,
    MATERIAL_COLUMNS,
    _co2_basis,
    _number,
    _supplier_basis,
    load_food_references,
    load_material_grades,
)


class MasterImportTests(unittest.TestCase):
    def test_header_only_workbooks_have_no_source_records(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for kind, columns, loader in (
                ("food", set(FOOD_NUMBER_COLUMNS.values()) | set(FOOD_TEXT_COLUMNS.values()),
                 load_food_references),
                ("material", set(MATERIAL_COLUMNS), load_material_grades),
            ):
                with self.subTest(kind=kind):
                    path = Path(folder, f"{kind}.xlsx")
                    workbook = Workbook()
                    workbook.active.append(sorted(columns))
                    workbook.save(path)
                    audit = loader(path)
                    self.assertEqual(audit.total_rows, 0)
                    self.assertEqual(audit.entries, ())
                    self.assertEqual(audit.issues, ())
                    self.assertEqual(len(audit.source_sha256), 64)

    def test_source_status_does_not_promote_estimates_to_measurements(self) -> None:
        self.assertIs(_co2_basis("estimated; JICA family ratio"), EvidenceBasis.ESTIMATED)
        self.assertIs(_co2_basis("supplier measured typical value"), EvidenceBasis.MEASURED)
        self.assertIs(_supplier_basis("supplier-calculated guideline"), EvidenceBasis.ESTIMATED)
        self.assertIs(_supplier_basis("supplier typical value"), EvidenceBasis.SUPPLIER_REPORTED)

    def test_missing_source_markers_are_not_numeric_zero(self) -> None:
        self.assertIsNone(_number({"co2tr_cm3_m2_day": "not_reported"}, "co2tr_cm3_m2_day"))
        self.assertIsNone(_number({"seal_min_c": "not_applicable"}, "seal_min_c"))


if __name__ == "__main__":
    unittest.main()
