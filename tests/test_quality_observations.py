"""Contract tests for the source-backed public quality observation intake."""

import os
import unittest

from packsense.ingestion import InputSchemaError
from packsense.quality_observations import (
    LONG_COLUMNS,
    PACKAGE_COLUMNS,
    QualityDataAudit,
    _columns,
    _number,
    audit_public_quality_data,
)


class PublicQualityObservationTests(unittest.TestCase):
    def test_source_headers_are_exact_and_order_independent(self):
        self.assertEqual(_columns(tuple(reversed(LONG_COLUMNS)), LONG_COLUMNS, "long"),
                         tuple(reversed(LONG_COLUMNS)))
        self.assertEqual(_columns(PACKAGE_COLUMNS, PACKAGE_COLUMNS, "package"),
                         PACKAGE_COLUMNS)

    def test_missing_extra_and_duplicate_columns_are_rejected(self):
        with self.assertRaisesRegex(InputSchemaError, "missing"):
            _columns(LONG_COLUMNS[:-1], LONG_COLUMNS, "long")
        with self.assertRaisesRegex(InputSchemaError, "unexpected"):
            _columns(LONG_COLUMNS + ("invented_target",), LONG_COLUMNS, "long")
        with self.assertRaisesRegex(InputSchemaError, "duplicate"):
            _columns(LONG_COLUMNS + ("package",), LONG_COLUMNS, "long")

    def test_measurement_parser_preserves_zero_and_rejects_invalid_ranges(self):
        self.assertEqual(_number("0", "coliform_cfu_g"), 0)
        self.assertEqual(_number("0.836", "water_activity"), 0.836)
        for value, field in ((-1, "peroxide_value_meq_kg"),
                             (1.01, "water_activity"),
                             (14.1, "ph"),
                             ("nan", "ph")):
            with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                _number(value, field)

    def test_failed_empty_audit_cannot_claim_model_readiness(self):
        audit = QualityDataAudit("long.csv", "package.csv", "0" * 64, "1" * 64,
                                 (), (), 0, 0, 0)
        report = audit.report()
        self.assertEqual(report["audit_status"], "failed")
        self.assertEqual(report["readiness"]["shelf_life_prediction"],
                         "not_ready_no_failure_or_censoring_labels")
        self.assertEqual(report["readiness"]["package_recommendation"],
                         "not_ready_incomplete_structure_and_exposure_data")

    @unittest.skipUnless(
        os.environ.get("PACKSENSE_PUBLIC_QUALITY_LONG_CSV")
        and os.environ.get("PACKSENSE_PUBLIC_QUALITY_PACKAGE_CSV"),
        "set source CSV paths to run the real-data integration audit",
    )
    def test_supplied_source_files_reconcile(self):
        audit = audit_public_quality_data(
            os.environ["PACKSENSE_PUBLIC_QUALITY_LONG_CSV"],
            os.environ["PACKSENSE_PUBLIC_QUALITY_PACKAGE_CSV"],
        )
        report = audit.report()
        self.assertEqual(report["audit_status"], "passed")
        self.assertEqual(report["counts"]["package_level_rows_days_30_60_90"], 72)
        self.assertEqual(report["counts"]["measured_quality_values_reconciled"], 504)
        self.assertEqual(report["readiness"]["shelf_life_prediction"],
                         "not_ready_no_failure_or_censoring_labels")


if __name__ == "__main__":
    unittest.main()
