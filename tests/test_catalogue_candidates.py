"""Public catalogue facts remain drafts, not material-suitability labels."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from packsense.catalogue_candidates import audit_candidate_catalogue, load_candidate_catalogue
from packsense.ingestion import InputSchemaError


SOURCE = Path(__file__).resolve().parents[1] / "data" / "public_catalogue_candidates.v1.json"


class CandidateCatalogueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(SOURCE.read_text(encoding="utf-8"))

    def _parse_modified(self, change) -> None:
        data = copy.deepcopy(self.data)
        change(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            load_candidate_catalogue(path)

    def test_real_pilot_coverage_and_approval_boundary(self) -> None:
        data, digest = load_candidate_catalogue(SOURCE)
        self.assertEqual(64, len(digest))
        self.assertEqual(5, len(data["sources"]))
        report = audit_candidate_catalogue(SOURCE)
        self.assertEqual(10, report["candidate_count"])
        self.assertEqual(
            {"finished_pouch": 1, "laminate_film": 2,
             "produce_bag": 6, "tray_component": 1},
            report["candidate_kind_counts"],
        )
        self.assertEqual(3, report["coverage"]["declared_layer_stacks"])
        self.assertEqual(2, report["coverage"]["all_layer_gauges_reported"])
        self.assertEqual(4, report["coverage"]["with_otr"])
        self.assertEqual(4, report["coverage"]["with_wvtr"])
        self.assertEqual(0, report["coverage"]["with_co2tr"])
        self.assertEqual(6, report["coverage"]["with_exact_food_quantity_temperature_use"])
        self.assertEqual(6, report["coverage"]["gauge_interpretations_needing_confirmation"])
        self.assertEqual(0, report["approved_package_structures"])
        self.assertEqual(0, report["suitability_training_labels"])
        self.assertFalse(report["recommendation_ready"])
        self.assertTrue(all(
            "exact_material_grade_join" in row["missing_for_promotion"]
            for row in report["candidate_blockers"]
        ))
        self.assertTrue(all(
            "reviewed_finished_package_seal_and_handling" in row["missing_for_promotion"]
            for row in report["candidate_blockers"]
        ))
        liner = next(row for row in report["candidate_blockers"]
                     if row["candidate_id"] == "SUMITOMO-PPLUS-PK601")
        self.assertIn("required_outer_package_definition", liner["missing_for_promotion"])
        pouch = next(row for row in report["candidate_blockers"]
                     if row["candidate_id"] == "POUCHDIRECT-SKU179")
        self.assertIn("indicative_barrier_not_measured_package_transfer",
                      pouch["missing_for_promotion"])
        self.assertNotIn("seal_strength_evidence", pouch["missing_for_promotion"])

    def test_exact_pouch_claims_remain_unapproved_and_food_unspecific(self) -> None:
        data, _ = load_candidate_catalogue(SOURCE)
        pouch = next(item for item in data["candidates"]
                     if item["candidate_id"] == "POUCHDIRECT-SKU179")
        self.assertEqual(pouch["record_kind"], "finished_pouch")
        self.assertEqual([layer["gauge_min"] for layer in pouch["layers"]],
                         [12, 12, 80])
        self.assertEqual(pouch["claimed_food_scope"], [])
        self.assertIsNone(pouch["service_temperature_c"])
        self.assertIsNone(pouch["seal_observation"]["process_temperature_min_c"])
        self.assertTrue(all(obs["basis"] == "supplier_indicative"
                            for obs in pouch["barrier_observations"]))
        self.assertFalse(audit_candidate_catalogue(SOURCE)["recommendation_ready"])

    def test_unpaired_seal_process_temperature_is_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "bounds must be paired"):
            self._parse_modified(lambda data: data["candidates"][-1][
                "seal_observation"
            ].__setitem__("process_temperature_min_c", 120))

    def test_supplier_storage_temperature_is_not_service_limit(self) -> None:
        report = audit_candidate_catalogue(SOURCE)
        self.assertEqual(0, report["coverage"]["with_service_temperature_limit"])
        self.assertTrue(all(
            "verified_service_temperature_limit" in row["missing_for_promotion"]
            for row in report["candidate_blockers"]
        ))

    def test_duplicate_candidate_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "duplicate candidate_id"):
            self._parse_modified(lambda data: data["candidates"].append(
                copy.deepcopy(data["candidates"][0])
            ))

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "absent from sources"):
            self._parse_modified(lambda data: data["candidates"][0].__setitem__(
                "source_id", "MADE-UP-SOURCE"
            ))

    def test_bad_barrier_test_conditions_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "both test temperature and RH"):
            self._parse_modified(lambda data: data["candidates"][1][
                "barrier_observations"
            ][0].__setitem__("test_rh_pct", None))

    def test_barrier_bounds_cannot_be_inverted(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "minimum exceeds maximum"):
            self._parse_modified(lambda data: data["candidates"][1][
                "barrier_observations"
            ][0].__setitem__("lower", 0.8))

    def test_zero_barrier_bound_is_valid_but_negative_is_not(self) -> None:
        self._parse_modified(lambda data: data["candidates"][0][
            "barrier_observations"
        ][0].__setitem__("upper", 0))
        with self.assertRaisesRegex(InputSchemaError, "nonnegative and finite"):
            self._parse_modified(lambda data: data["candidates"][0][
                "barrier_observations"
            ][0].__setitem__("upper", -1))

    def test_food_application_cannot_extend_supplier_scope(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "absent from claimed_food_scope"):
            self._parse_modified(lambda data: data["candidates"][3][
                "applications"
            ][0].__setitem__("commodity", "strawberry"))

    def test_wildcard_food_scope_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "cannot be a wildcard"):
            self._parse_modified(lambda data: data["candidates"][3].__setitem__(
                "claimed_food_scope", ["all_foods"]
            ))

    def test_malformed_excursion_rejected(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "must be paired"):
            self._parse_modified(lambda data: data["candidates"][3][
                "applications"
            ][0].__setitem__("excursion_max_hours", None))

    def test_rights_cannot_be_self_approved(self) -> None:
        with self.assertRaisesRegex(InputSchemaError, "must not claim rights approval"):
            self._parse_modified(lambda data: data["sources"][0].__setitem__(
                "rights_review_status", "approved"
            ))

    def test_duplicate_json_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(InputSchemaError, "duplicate JSON key"):
                load_candidate_catalogue(path)


if __name__ == "__main__":
    unittest.main()
