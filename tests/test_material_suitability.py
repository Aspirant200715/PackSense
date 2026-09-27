"""TEST_ONLY suitability intake fixtures; none are training observations."""

import json
import unittest
from dataclasses import replace

from packsense.contracts import (
    FoodReference, HandlingSeverity, PackageStructure, ScenarioInput, StorageType,
    StructureLayer,
)
from packsense.enrichment import (
    EnrichedScenario, EnrichmentAudit, EnrichmentRow, exposure_profile,
)
from packsense.ingestion import InputSchemaError
from packsense.material_suitability import (
    audit_suitability_labels, parse_suitability_register,
)
from packsense.structure_review import (
    CHECK_KINDS, EvidenceCheck, ReviewAttestedStructure, StructureReviewAudit,
)


SCENARIO_HASH = "a" * 64
FOOD_HASH = "b" * 64
MATERIAL_HASH = "c" * 64
CATALOGUE_HASH = "d" * 64
REVIEW_HASH = "e" * 64


def _label(**changes):
    row = {
        "label_id": "TEST_ONLY_LABEL",
        "scenario_record_id": "TEST_ONLY_SCENARIO",
        "food_reference_id": "TEST_ONLY_FOOD",
        "structure_id": "TEST_ONLY_STRUCTURE",
        "decision": "suitable",
        "evidence_basis": "independent_expert_assessment",
        "source_family_id": "TEST_ONLY_SOURCE_FAMILY",
        "source_id": "TEST_ONLY_SOURCE",
        "source_locator": "TEST_ONLY_LOCATOR",
        "source_finding": "TEST_ONLY_EXPLICIT_FINDING",
        "decision_criterion": "TEST_ONLY_CRITERION",
        "review_id": "TEST_ONLY_REVIEW",
        "reviewer_id": "TEST_ONLY_REVIEWER",
        "rights_review_id": "TEST_ONLY_RIGHTS",
        "rationale": "TEST_ONLY_REASON",
    }
    row.update(changes)
    return row


def _register(*labels, **changes):
    document = {
        "schema_version": 1,
        "scenario_sha256": SCENARIO_HASH,
        "food_master_sha256": FOOD_HASH,
        "material_master_sha256": MATERIAL_HASH,
        "structure_catalogue_sha256": CATALOGUE_HASH,
        "structure_review_sha256": REVIEW_HASH,
        "labels": list(labels),
    }
    document.update(changes)
    return json.dumps(document).encode("utf-8")


def _enriched():
    scenario = ScenarioInput(
        record_id="TEST_ONLY_SCENARIO", commodity_type="Dry snack",
        moisture_content_pct=5.0, oil_fat_content_pct=20.0, pH=6.0,
        desired_shelf_life_days=30.0, storage_type=StorageType.AMBIENT,
        storage_temperature_c=24.0, storage_relative_humidity_pct=60.0,
        transport_mode="TEST_ONLY_MODE", transport_duration_hours=12.0,
        transport_temperature_c=27.0, transport_max_temperature_c=35.0,
        transport_handling_severity=HandlingSeverity.MEDIUM,
        net_pack_quantity=100.0, net_pack_quantity_unit="g",
        food_reference_id="TEST_ONLY_FOOD",
    )
    food = FoodReference(
        food_id="TEST_ONLY_FOOD", commodity_type="Dry snack", food_group="TEST_ONLY",
        moisture_content_pct=5.0, oil_fat_content_pct=20.0, pH=6.0,
        pH_basis="TEST_ONLY", respiration_rate=None, respiration_rate_unit=None,
        respiration_reference_temperature_c=None, source_citations="TEST_ONLY_SOURCE",
    )
    joined = EnrichedScenario(scenario, food, 2, FOOD_HASH, "TEST_ONLY",
                              "confirmed_non_respiring", exposure_profile(scenario))
    return EnrichmentAudit(SCENARIO_HASH, FOOD_HASH, (
        EnrichmentRow(2, scenario.record_id, joined, ()),
    ))


def _reviewed():
    structure = PackageStructure(
        structure_id="TEST_ONLY_STRUCTURE", pack_format="TEST_ONLY_POUCH",
        layers=(StructureLayer("TEST_ONLY_GRADE", 20.0, "sealant", True),),
        sealant_grade_id="TEST_ONLY_GRADE",
        structure_source_id="TEST_ONLY_CONSTRUCTION_SOURCE",
        food_contact_evidence_id="TEST_ONLY_CONTACT_SOURCE",
        compatible_food_scope=("Dry snack",),
        service_temperature_min_c=-5.0, service_temperature_max_c=40.0,
    )
    checks = tuple(EvidenceCheck(
        kind, (structure.structure_source_id if kind == "construction" else
               structure.food_contact_evidence_id if kind == "food_contact" else
               f"TEST_ONLY_{kind.upper()}_SOURCE"),
        "TEST_ONLY_LOCATOR", "f" * 64, "TEST_ONLY_REVIEW",
        "TEST_ONLY_RIGHTS", "pass",
    ) for kind in sorted(CHECK_KINDS))
    item = ReviewAttestedStructure(
        structure, CATALOGUE_HASH, MATERIAL_HASH, REVIEW_HASH,
        "TEST_ONLY_REVIEW", tuple(check.review_id for check in checks), (), checks,
    )
    return StructureReviewAudit("review_attested", CATALOGUE_HASH, REVIEW_HASH,
                                (item,), ())


class MaterialSuitabilityTests(unittest.TestCase):
    def test_exact_sourced_pair_is_accepted_but_not_called_a_model(self):
        register = parse_suitability_register(_register(_label()))
        audit = audit_suitability_labels(
            register, _enriched(), _reviewed(),
            material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(len(audit.accepted), 1)
        self.assertEqual(audit.issues, ())
        report = audit.report()
        self.assertEqual(report["decision_counts"], {"suitable": 1})
        self.assertEqual(report["independent_source_families"], 1)
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["model_trained"])
        self.assertFalse(report["scientific_suitability_verified_by_code"])

    def test_empty_register_does_not_become_training_data(self):
        register = parse_suitability_register(_register())
        audit = audit_suitability_labels(
            register, _enriched(), _reviewed(),
            material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(audit.report()["accepted_labels"], 0)
        self.assertEqual(audit.report()["training_readiness_reason"], "no_accepted_labels")

    def test_explicit_unsuitable_measured_comparison_is_not_inferred_from_absence(self):
        register = parse_suitability_register(_register(_label(
            decision="unsuitable", evidence_basis="measured_comparison",
        )))
        audit = audit_suitability_labels(
            register, _enriched(), _reviewed(),
            material_master_sha256=MATERIAL_HASH,
        )
        self.assertEqual(audit.report()["decision_counts"], {"unsuitable": 1})
        self.assertEqual(audit.report()["evidence_basis_counts"],
                         {"measured_comparison": 1})

    def test_duplicate_and_invalid_labels_are_rejected(self):
        cases = (
            _register(_label(), _label(label_id="TEST_ONLY_OTHER")),
            _register(_label(decision="used_in_market")),
            _register(_label(evidence_basis="supplier_application")),
            _register(_label(source_locator="unknown")),
            _register(_label(), schema_version=True),
            _register(_label(), scenario_sha256="INVALID"),
            b'{"schema_version":1,"schema_version":1}',
        )
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(InputSchemaError):
                    parse_suitability_register(raw)

    def test_mismatched_bindings_are_not_accepted(self):
        cases = (
            (_label(scenario_record_id="TEST_ONLY_OTHER"), _reviewed(),
             "scenario_not_enriched"),
            (_label(food_reference_id="TEST_ONLY_OTHER"), _reviewed(),
             "food_reference_mismatch"),
            (_label(structure_id="TEST_ONLY_OTHER"), _reviewed(),
             "reviewed_structure_missing_or_stale"),
            (_label(), replace(_reviewed(), reviewed=(replace(
                _reviewed().reviewed[0], structure=replace(
                    _reviewed().reviewed[0].structure,
                    compatible_food_scope=("TEST_ONLY_OTHER",),
                ),
            ),)), "reviewed_food_scope_mismatch"),
            (_label(), replace(_reviewed(), reviewed=(replace(
                _reviewed().reviewed[0], structure=replace(
                    _reviewed().reviewed[0].structure,
                    service_temperature_max_c=30.0,
                ),
            ),)), "service_temperature_out_of_scope"),
        )
        for label, review, expected in cases:
            with self.subTest(expected=expected):
                register = parse_suitability_register(_register(label))
                audit = audit_suitability_labels(
                    register, _enriched(), review,
                    material_master_sha256=MATERIAL_HASH,
                )
                self.assertEqual(audit.accepted, ())
                self.assertEqual(audit.issues[0].code, expected)

    def test_stale_versions_and_broken_review_fail_closed(self):
        with self.assertRaisesRegex(InputSchemaError, "different source version"):
            audit_suitability_labels(
                parse_suitability_register(_register(_label(), food_master_sha256="0" * 64)),
                _enriched(), _reviewed(), material_master_sha256=MATERIAL_HASH,
            )
        broken = replace(_reviewed(), reviewed=(replace(
            _reviewed().reviewed[0], evidence_checks=(), evidence_check_ids=(),
        ),))
        with self.assertRaisesRegex(InputSchemaError, "not internally consistent"):
            audit_suitability_labels(
                parse_suitability_register(_register(_label())),
                _enriched(), broken, material_master_sha256=MATERIAL_HASH,
            )


if __name__ == "__main__":
    unittest.main()
