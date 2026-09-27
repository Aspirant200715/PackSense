"""TEST_ONLY split fixtures; no food-package observations are fitted."""

import json
import unittest
from dataclasses import replace

from packsense.ingestion import InputSchemaError
from packsense.material_split import (
    build_material_split, parse_material_split_plan,
)
from packsense.material_suitability import (
    SuitabilityAudit, SuitabilityLabel, SuitabilityRegister,
)


REGISTER_HASH = "a" * 64


def _labels():
    labels = []
    for number in range(12):
        group = f"TEST_ONLY_SOURCE_FAMILY_{number:02d}"
        food = f"TEST_ONLY_FOOD_{number:02d}"
        for decision in ("suitable", "unsuitable"):
            labels.append(SuitabilityLabel(
                label_id=f"TEST_ONLY_LABEL_{number:02d}_{decision}",
                scenario_record_id=f"TEST_ONLY_SCENARIO_{number:02d}",
                food_reference_id=food,
                structure_id=f"TEST_ONLY_STRUCTURE_{decision}",
                decision=decision,
                evidence_basis="independent_expert_assessment",
                source_family_id=group,
                source_id=f"TEST_ONLY_SOURCE_{number:02d}",
                source_locator="TEST_ONLY_LOCATOR",
                source_finding="TEST_ONLY_FINDING",
                decision_criterion="TEST_ONLY_CRITERION",
                review_id="TEST_ONLY_REVIEW",
                reviewer_id="TEST_ONLY_REVIEWER",
                rights_review_id="TEST_ONLY_RIGHTS",
                rationale="TEST_ONLY_REASON",
            ))
    return tuple(labels)


def _audit(labels=None):
    rows = _labels() if labels is None else tuple(labels)
    register = SuitabilityRegister(
        source_sha256=REGISTER_HASH, scenario_sha256="b" * 64,
        food_master_sha256="c" * 64, material_master_sha256="d" * 64,
        structure_catalogue_sha256="e" * 64,
        structure_review_sha256="f" * 64, labels=rows,
    )
    return SuitabilityAudit(register, rows, ())


def _plan(**changes):
    data = {
        "schema_version": 1,
        "plan_id": "TEST_ONLY_PLAN",
        "suitability_register_sha256": REGISTER_HASH,
        "train_groups": [f"TEST_ONLY_SOURCE_FAMILY_{n:02d}" for n in range(8)],
        "validation_groups": [f"TEST_ONLY_SOURCE_FAMILY_{n:02d}" for n in range(8, 10)],
        "test_groups": [f"TEST_ONLY_SOURCE_FAMILY_{n:02d}" for n in range(10, 12)],
    }
    data.update(changes)
    return parse_material_split_plan(json.dumps(data).encode("utf-8"))


def _split(audit, plan, names=None):
    if names is None:
        names = {f"TEST_ONLY_FOOD_{n:02d}": f"TEST_ONLY_COMMODITY_{n:02d}"
                 for n in range(12)}
    return build_material_split(audit, plan, food_commodity_by_id=names)


class MaterialSplitTests(unittest.TestCase):
    def test_balanced_source_and_food_disjoint_80_20_allocation(self):
        split = _split(_audit(), _plan())
        self.assertEqual(split.status, "allocation_prepared")
        self.assertEqual(split.reasons, ())
        self.assertEqual(split.diagnostics["test_row_fraction"], 4 / 24)
        self.assertEqual(split.diagnostics["validation_fraction_of_development"], 4 / 20)
        self.assertEqual(len(split.manifest["partitions"]["test"]["label_ids"]), 4)
        self.assertEqual(len(split.manifest["manifest_sha256"]), 64)
        self.assertFalse(split.report()["model_trained"])

    def test_bad_group_assignments_fail_closed(self):
        cases = (
            (_plan(test_groups=["TEST_ONLY_SOURCE_FAMILY_10",
                                "TEST_ONLY_SOURCE_FAMILY_07"]),
             "group_crosses_partitions:train:test"),
            (_plan(test_groups=["TEST_ONLY_SOURCE_FAMILY_10"]),
             "unassigned_source_families"),
            (_plan(test_groups=["TEST_ONLY_SOURCE_FAMILY_10",
                                "TEST_ONLY_SOURCE_FAMILY_UNKNOWN"]),
             "unknown_source_families"),
            (_plan(suitability_register_sha256="0" * 64),
             "suitability_register_hash_mismatch"),
        )
        for plan, expected in cases:
            with self.subTest(expected=expected):
                split = _split(_audit(), plan)
                self.assertEqual(split.status, "not_ready")
                self.assertIsNone(split.manifest)
                self.assertIn(expected, split.reasons)

    def test_food_or_source_shared_across_partitions_is_leakage(self):
        labels = list(_labels())
        labels[-1] = replace(labels[-1], food_reference_id=labels[0].food_reference_id)
        split = _split(_audit(labels), _plan())
        self.assertIn("food_reference_crosses_partitions", split.reasons)
        labels = list(_labels())
        labels[-1] = replace(labels[-1], source_id=labels[0].source_id)
        split = _split(_audit(labels), _plan())
        self.assertIn("source_id_crosses_source_families", split.reasons)
        names = {f"TEST_ONLY_FOOD_{n:02d}": f"TEST_ONLY_COMMODITY_{n:02d}"
                 for n in range(12)}
        names["TEST_ONLY_FOOD_11"] = names["TEST_ONLY_FOOD_00"]
        split = _split(_audit(), _plan(), names)
        self.assertIn("commodity_name_crosses_partitions", split.reasons)

    def test_class_coverage_and_row_fraction_are_checked(self):
        labels = list(_labels())
        labels[-1] = replace(labels[-1], decision="suitable")
        split = _split(_audit(labels), _plan())
        self.assertEqual(split.status, "allocation_prepared")
        labels = tuple(replace(label, decision="suitable")
                       if label.source_family_id in {
                           "TEST_ONLY_SOURCE_FAMILY_10", "TEST_ONLY_SOURCE_FAMILY_11"
                       } and label.decision == "unsuitable" else label
                       for label in _labels())
        split = _split(_audit(labels), _plan())
        self.assertIn("too_few_unsuitable_groups:test", split.reasons)
        labels = tuple(label for label in _labels()
                       if label.source_family_id not in {
                           "TEST_ONLY_SOURCE_FAMILY_10", "TEST_ONLY_SOURCE_FAMILY_11"
                       } or label.decision == "suitable")
        split = _split(_audit(labels), _plan())
        self.assertIn("test_fraction_outside_80_20_tolerance", split.reasons)

    def test_invalid_plan_format_is_rejected(self):
        cases = (
            {"schema_version": True},
            {"plan_id": "unknown"},
            {"train_groups": ["TEST_ONLY_SOURCE_FAMILY_00"] * 2},
            {"test_groups": "TEST_ONLY_SOURCE_FAMILY_10"},
        )
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(InputSchemaError):
                    _plan(**change)
        with self.assertRaises(InputSchemaError):
            parse_material_split_plan(b'{"schema_version":1,"schema_version":1}')


if __name__ == "__main__":
    unittest.main()
