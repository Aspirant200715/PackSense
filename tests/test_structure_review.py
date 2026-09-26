"""Constructed TEST_ONLY records check the gate; they are not source data."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from packsense.contracts import BarrierObservation, EvidenceBasis, MaterialGrade
from packsense.structure_review import (
    audit_structure_reviews, draft_digest, parse_structure_review_register,
)
from packsense.structures import audit_structure_catalogue


def _grade() -> MaterialGrade:
    return MaterialGrade(
        material_id="TEST_ONLY_GRADE", manufacturer="TEST_ONLY_MANUFACTURER",
        grade=None, material_family="TEST_ONLY_FAMILY", film_structure="test film",
        film_role="sealant", thickness_um=20, otr=None, co2tr=None, wvtr=None,
        co2_training_label=False, seal_status="test-only",
        food_contact_statement="test-only", model_use_status="test-only",
        source_url="TEST_ONLY_SOURCE",
    )


def _draft_row(structure_id="TEST_ONLY_STRUCTURE") -> dict:
    return {
        "structure_id": structure_id,
        "pack_format": "test pouch",
        "layers": [{"grade_id": "TEST_ONLY_GRADE", "thickness_um": 20,
                    "role": "sealant", "is_food_contact": True}],
        "sealant_grade_id": "TEST_ONLY_GRADE",
        "converter": "TEST_ONLY_CONVERTER",
        "forming_method": "test forming method",
        "closure_type": "test closure",
        "structure_source_id": "TEST_ONLY_CONSTRUCTION_SOURCE",
        "structure_source_locator": "TEST_ONLY_CONSTRUCTION_LOCATOR",
        "food_contact_evidence_id": "TEST_ONLY_CONTACT_SOURCE",
        "food_contact_evidence_locator": "TEST_ONLY_CONTACT_LOCATOR",
        "compatible_food_scope": ["TEST_ONLY_FOOD_A", "TEST_ONLY_FOOD_B"],
        "service_temperature_min_c": -10,
        "service_temperature_max_c": 40,
    }


def _catalogue(rows=None, *, grade=None):
    rows = [_draft_row()] if rows is None else rows
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "test-only-catalogue.json"
        source.write_text(json.dumps({"catalogue_version": "TEST_ONLY_VERSION",
                                      "structures": rows}), encoding="utf-8")
        return audit_structure_catalogue(
            source, grades={"TEST_ONLY_GRADE": grade or _grade()},
            material_master_sha256="a" * 64,
        )


def _check(kind, draft):
    source_id = f"TEST_ONLY_{kind.upper()}_SOURCE"
    locator = f"TEST_ONLY_{kind.upper()}_LOCATOR"
    if kind == "construction":
        source_id, locator = draft.structure_source_id, draft.structure_source_locator
    elif kind == "food_contact":
        source_id, locator = (draft.food_contact_evidence_id,
                              draft.food_contact_evidence_locator)
    return {
        "kind": kind, "source_id": source_id, "source_locator": locator,
        "source_sha256": "b" * 64, "review_id": f"TEST_ONLY_{kind.upper()}_REVIEW",
        "rights_review_id": f"TEST_ONLY_{kind.upper()}_RIGHTS", "decision": "pass",
    }


def _review(draft):
    return {
        "structure_id": draft.structure_id,
        "draft_digest": draft_digest(draft),
        "review_id": "TEST_ONLY_REVIEW", "reviewer_id": "TEST_ONLY_REVIEWER",
        "reviewed_food_scope": ["TEST_ONLY_FOOD_A"],
        "service_temperature_min_c": -5,
        "service_temperature_max_c": 35,
        "checks": [_check(kind, draft) for kind in (
            "construction", "food_contact", "seal_closure", "mechanical",
            "service_temperature",
        )],
    }


def _register(catalogue, reviews=None):
    if reviews is None:
        reviews = [_review(draft) for draft in catalogue.entries]
    payload = {
        "schema_version": 1,
        "catalogue_sha256": catalogue.source_sha256,
        "material_master_sha256": catalogue.material_master_sha256,
        "catalogue_version": catalogue.catalogue_version,
        "reviews": reviews,
    }
    return parse_structure_review_register(json.dumps(payload).encode())


class StructureReviewTests(unittest.TestCase):
    def test_exact_attested_draft_is_not_a_feasible_package(self):
        catalogue = _catalogue()
        result = audit_structure_reviews(catalogue, _register(catalogue))
        self.assertEqual(result.status, "review_attested")
        self.assertEqual(len(result.reviewed), 1)
        reviewed = result.reviewed[0]
        self.assertEqual(reviewed.structure.compatible_food_scope, ("TEST_ONLY_FOOD_A",))
        self.assertEqual(reviewed.structure.service_temperature_min_c, -5)
        self.assertFalse(result.report()["package_feasible"])
        self.assertFalse(result.report()["evidence_authenticity_verified_by_code"])

    def test_changed_draft_or_catalogue_hash_invalidates_review(self):
        catalogue = _catalogue()
        original = _register(catalogue)
        changed = _catalogue([dict(_draft_row(), pack_format="different test pouch")])
        result = audit_structure_reviews(changed, original)
        self.assertEqual(result.status, "not_approved")
        self.assertEqual(result.reviewed, ())
        self.assertIn("catalogue_or_material_version_mismatch",
                      [issue.code for issue in result.issues])
        self.assertIn("draft_digest_mismatch", [issue.code for issue in result.issues])

    def test_review_cannot_cite_unrelated_construction_or_contact(self):
        catalogue = _catalogue()
        for kind, expected in (("construction", "construction_source_mismatch"),
                               ("food_contact", "food_contact_source_mismatch")):
            with self.subTest(kind=kind):
                review = _review(catalogue.entries[0])
                check = next(item for item in review["checks"] if item["kind"] == kind)
                check["source_id"] = "TEST_ONLY_WRONG_SOURCE"
                result = audit_structure_reviews(catalogue, _register(catalogue, [review]))
                self.assertEqual(result.reviewed, ())
                self.assertIn(expected, [issue.code for issue in result.issues])

    def test_failed_check_or_wider_scope_blocks_all_promotions(self):
        catalogue = _catalogue()
        for change, expected in (
            ({"reviewed_food_scope": ["TEST_ONLY_OTHER_FOOD"]},
             "review_food_scope_exceeds_draft"),
            ({"service_temperature_max_c": 50}, "review_service_range_exceeds_draft"),
        ):
            with self.subTest(change=change):
                review = dict(_review(catalogue.entries[0]), **change)
                result = audit_structure_reviews(catalogue, _register(catalogue, [review]))
                self.assertEqual(result.reviewed, ())
                self.assertIn(expected, [issue.code for issue in result.issues])
        review = _review(catalogue.entries[0])
        review["checks"][0]["decision"] = "fail"
        result = audit_structure_reviews(catalogue, _register(catalogue, [review]))
        self.assertIn("required_evidence_check_failed",
                      [issue.code for issue in result.issues])

    def test_rejected_draft_or_missing_review_blocks_whole_catalogue(self):
        bad = _draft_row("TEST_ONLY_BAD")
        bad["layers"][0]["thickness_um"] = 22
        catalogue = _catalogue([_draft_row(), bad])
        result = audit_structure_reviews(catalogue, _register(catalogue))
        self.assertEqual(result.reviewed, ())
        self.assertIn("catalogue_has_rejected_drafts",
                      [issue.code for issue in result.issues])
        clean = _catalogue([_draft_row(), _draft_row("TEST_ONLY_SECOND")])
        result = audit_structure_reviews(clean, _register(clean, [_review(clean.entries[0])]))
        self.assertEqual(result.reviewed, ())
        self.assertIn("missing_structure_review", [issue.code for issue in result.issues])
        reviews = [_review(draft) for draft in clean.entries]
        reviews[1]["checks"][0]["decision"] = "fail"
        result = audit_structure_reviews(clean, _register(clean, reviews))
        self.assertEqual(result.reviewed, ())
        self.assertIn("required_evidence_check_failed",
                      [issue.code for issue in result.issues])

    def test_estimated_grade_barrier_is_not_promoted_to_finished_performance(self):
        grade = replace(_grade(), otr=BarrierObservation(
            value=10, unit="test-only", test_temperature_c=None,
            test_relative_humidity_pct=None, test_method=None,
            basis=EvidenceBasis.ESTIMATED, source_url="TEST_ONLY_SOURCE",
        ))
        catalogue = _catalogue(grade=grade)
        result = audit_structure_reviews(catalogue, _register(catalogue))
        self.assertEqual(result.reviewed[0].estimated_barrier_grade_ids,
                         ("TEST_ONLY_GRADE",))
        self.assertFalse(result.report()["package_feasible"])

    def test_strict_review_parser_refuses_missing_or_ambiguous_claims(self):
        catalogue = _catalogue()
        review = _review(catalogue.entries[0])
        base = {
            "schema_version": 1, "catalogue_sha256": catalogue.source_sha256,
            "material_master_sha256": catalogue.material_master_sha256,
            "catalogue_version": catalogue.catalogue_version, "reviews": [review],
        }
        for changed in (
            {**base, "reviews": [review, review]},
            {**base, "reviews": [{**review, "checks": review["checks"][:-1]}]},
            {**base, "reviews": [{**review, "checks": review["checks"] +
                                  [review["checks"][0]]}]},
            {**base, "reviews": [{**review, "reviewer_id": ""}]},
            {**base, "reviews": [{**review, "extra": "not allowed"}]},
            {**base, "reviews": [{**review, "reviewed_food_scope": ["all_foods"]}]},
            {**base, "reviews": [{**review, "reviewed_food_scope":
                                  ["TEST_ONLY_FOOD_A", "test_only_food_a"]}]},
            {**base, "reviews": [{**review, "service_temperature_max_c": 1e999}]},
            {**base, "reviews": [{**review, "checks": [
                {**review["checks"][0], "rights_review_id": ""},
                *review["checks"][1:]]}]},
            {**base, "reviews": [{**review, "checks": [
                {**review["checks"][0], "kind": []},
                *review["checks"][1:]]}]},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_structure_review_register(json.dumps(changed).encode())
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_structure_review_register(
                b'{"schema_version":1,"schema_version":1}'
            )


if __name__ == "__main__":
    unittest.main()
