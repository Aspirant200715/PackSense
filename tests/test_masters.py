"""Master import structure/evidence tests; no fabricated source records."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from packsense.contracts import BarrierObservation, EvidenceBasis
from packsense.masters import (
    FOOD_NUMBER_COLUMNS,
    FOOD_TEXT_COLUMNS,
    MATERIAL_COLUMNS,
    _barrier_evidence_report,
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

    def test_barrier_evidence_summary_keeps_supplier_and_estimated_values_distinct(self) -> None:
        # TEST_ONLY domain objects exercise evidence counting; they are never model-fit rows.
        def observation(basis, *, complete=True):
            return BarrierObservation(
                value=1.0, unit="test-unit",
                test_temperature_c=23.0 if complete else None,
                test_relative_humidity_pct=50.0 if complete else None,
                test_method="TEST_ONLY method" if complete else "not_measured",
                basis=basis, source_url="https://example.invalid/test-only",
            )

        entries = tuple(
            SimpleNamespace(grade=SimpleNamespace(
                otr=barrier, wvtr=None, co2tr=co2,
                co2_training_label=label,
            ))
            for barrier, co2, label in (
                (observation(EvidenceBasis.MEASURED),
                 observation(EvidenceBasis.MEASURED), True),
                (observation(EvidenceBasis.SUPPLIER_REPORTED), None, False),
                (observation(EvidenceBasis.ESTIMATED, complete=False),
                 observation(EvidenceBasis.ESTIMATED, complete=False), False),
            )
        )
        otr = _barrier_evidence_report(entries, "otr")
        self.assertEqual(otr["rows_with_values"], 3)
        self.assertEqual(otr["evidence_basis_counts"]["supplier_reported"], 1)
        self.assertEqual(otr["rows_with_complete_test_context"], 2)
        self.assertEqual(otr["strict_measured_training_candidates"], 1)
        co2 = _barrier_evidence_report(entries, "co2tr")
        self.assertEqual(co2["declared_training_label_rows"], 1)
        self.assertEqual(co2["declared_labels_with_measured_complete_context"], 1)


if __name__ == "__main__":
    unittest.main()
