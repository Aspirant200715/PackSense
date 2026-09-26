"""Test-only catalogue records are never packaged as source or training data."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from packsense.contracts import BarrierObservation, EvidenceBasis, MaterialGrade
from packsense.ingestion import InputSchemaError
from packsense.structures import audit_structure_catalogue


def _test_grade() -> MaterialGrade:
    return MaterialGrade(
        material_id="TEST_ONLY_GRADE", manufacturer="TEST_ONLY_MANUFACTURER",
        grade=None, material_family="TEST_ONLY_FAMILY", film_structure="test film",
        film_role="sealant", thickness_um=20, otr=None, co2tr=None, wvtr=None,
        co2_training_label=False, seal_status="test-only", food_contact_statement="test-only",
        model_use_status="test-only", source_url="TEST_ONLY_SOURCE",
    )


def _test_draft() -> dict:
    return {
        "structure_id": "TEST_ONLY_STRUCTURE",
        "pack_format": "test pouch",
        "layers": [{"grade_id": "TEST_ONLY_GRADE", "thickness_um": 20,
                    "role": "sealant", "is_food_contact": True}],
        "sealant_grade_id": "TEST_ONLY_GRADE",
        "converter": "TEST_ONLY_CONVERTER",
        "forming_method": "test forming method",
        "closure_type": "test closure",
        "structure_source_id": "TEST_ONLY_STRUCTURE_SOURCE",
        "structure_source_locator": "TEST_ONLY_NOT_A_REAL_SOURCE",
        "food_contact_evidence_id": "TEST_ONLY_CONTACT_EVIDENCE",
        "food_contact_evidence_locator": "TEST_ONLY_NOT_A_REAL_CERTIFICATE",
        "compatible_food_scope": ["TEST_ONLY_FOOD_SCOPE"],
        "service_temperature_min_c": -10,
        "service_temperature_max_c": 40,
    }


class StructureCatalogueTests(unittest.TestCase):
    def _audit(self, rows: list[dict], *, grade: MaterialGrade | None = None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalogue.json"
            path.write_text(json.dumps({"catalogue_version": "TEST_ONLY_VERSION",
                                        "structures": rows}), encoding="utf-8")
            return audit_structure_catalogue(
                path, grades={"TEST_ONLY_GRADE": grade or _test_grade()},
                material_master_sha256="a" * 64,
            )

    def test_empty_catalogue_cannot_be_used_for_recommendations(self):
        report = self._audit([]).report()
        self.assertEqual(report["total_rows"], 0)
        self.assertEqual(report["schema_valid_drafts"], 0)
        self.assertEqual(report["approved_package_structures"], 0)

    def test_exact_grade_gauge_join_is_still_only_a_draft(self):
        audit = self._audit([_test_draft()])
        self.assertEqual(len(audit.entries), 1)
        self.assertEqual(audit.entries[0].layers[-1].grade_id, "TEST_ONLY_GRADE")
        self.assertEqual(audit.report()["approved_package_structures"], 0)
        self.assertEqual(len(audit.source_sha256), 64)

    def test_unknown_grade_and_different_gauge_are_rejected(self):
        unknown = _test_draft()
        unknown["layers"][0]["grade_id"] = "TEST_ONLY_UNKNOWN_GRADE"
        wrong_gauge = _test_draft()
        wrong_gauge["layers"][0]["thickness_um"] = 25
        wrong_gauge["structure_id"] = "TEST_ONLY_OTHER_STRUCTURE"
        report = self._audit([unknown, wrong_gauge]).report()
        self.assertEqual(report["schema_valid_drafts"], 0)
        self.assertEqual(report["rejected_rows"], 2)
        self.assertEqual([issue["field"] for issue in report["issues"]],
                         ["layers[0].grade_id", "layers[0].thickness_um"])

    def test_contact_layer_must_be_innermost_sealant(self):
        draft = _test_draft()
        draft["layers"][0]["is_food_contact"] = False
        report = self._audit([draft]).report()
        self.assertEqual(report["issues"][0]["field"], "layers")
        draft = _test_draft()
        draft["sealant_grade_id"] = "TEST_ONLY_OTHER_GRADE"
        report = self._audit([draft]).report()
        self.assertEqual(report["issues"][0]["field"], "sealant_grade_id")

    def test_blanket_food_scope_is_rejected(self):
        draft = _test_draft()
        draft["compatible_food_scope"] = ["all_foods"]
        report = self._audit([draft]).report()
        self.assertEqual(report["issues"][0]["field"], "compatible_food_scope")

    def test_estimated_grade_property_is_flagged_not_approved(self):
        grade = replace(
            _test_grade(),
            co2tr=BarrierObservation(
                value=10, unit="test units", test_temperature_c=None,
                test_relative_humidity_pct=None, test_method=None,
                basis=EvidenceBasis.ESTIMATED, source_url="TEST_ONLY_SOURCE",
            ),
        )
        report = self._audit([_test_draft()], grade=grade).report()
        self.assertEqual(report["schema_valid_drafts"], 1)
        self.assertEqual(report["drafts_with_estimated_barrier_grades"], 1)
        self.assertEqual(report["approved_package_structures"], 0)

    def test_grade_without_observed_gauge_is_rejected(self):
        grade = replace(_test_grade(), thickness_um=None)
        report = self._audit([_test_draft()], grade=grade).report()
        self.assertEqual(report["issues"][0]["field"], "layers[0].thickness_um")

    def test_duplicate_ids_reject_every_occurrence(self):
        report = self._audit([_test_draft(), _test_draft()]).report()
        self.assertEqual(report["schema_valid_drafts"], 0)
        self.assertEqual(report["rejected_rows"], 2)
        self.assertTrue(all(issue["field"] == "structure_id" for issue in report["issues"]))

    def test_duplicate_json_keys_are_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalogue.json"
            path.write_text('{"catalogue_version":"a","catalogue_version":"b","structures":[]}',
                            encoding="utf-8")
            with self.assertRaisesRegex(InputSchemaError, "duplicate JSON key"):
                audit_structure_catalogue(
                    path, grades={"TEST_ONLY_GRADE": _test_grade()},
                    material_master_sha256="a" * 64,
                )

    def test_nonfinite_or_missing_service_limits_are_rejected(self):
        draft = _test_draft()
        draft["service_temperature_max_c"] = 1e309
        with self.assertRaisesRegex(InputSchemaError, "non-finite JSON number"):
            self._audit([draft])
        draft = _test_draft()
        del draft["service_temperature_max_c"]
        report = self._audit([draft]).report()
        self.assertEqual(report["issues"][0]["field"], "structure")


if __name__ == "__main__":
    unittest.main()
