"""Stop-3 contract tests; the small values below are test doubles, not data."""

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

from packsense.contracts import EvidenceBasis, HandlingSeverity, StorageType
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.requirements import (
    AssessmentDecision,
    ProtectionAssessment,
    ProtectionMechanism,
    derive_requirement_card,
    load_protection_assessments,
)


def _enriched(*, route="unclassified", max_temperature=9.0, quantity=100.0):
    scenario = SimpleNamespace(
        record_id="TEST-ROW", storage_temperature_c=4.0,
        storage_type=StorageType.CHILLED, transport_mode="test-mode",
        storage_relative_humidity_pct=80.0, transport_temperature_c=6.0,
        transport_max_temperature_c=max_temperature,
        transport_duration_hours=12.0, transport_handling_severity=HandlingSeverity.HIGH,
        net_pack_quantity=quantity, net_pack_quantity_unit="g",
        desired_shelf_life_days=10.0,
    )
    return EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "test-master-hash",
        "missing", route, exposure_profile(scenario),
    )


def _assessment(
    mechanism=ProtectionMechanism.OXYGEN_INGRESS,
    decision=AssessmentDecision.LIMIT,
    transfer=20.0,
    unit="mmol_o2_per_pack",
    **changes,
):
    values = dict(
        food_reference_id="TEST-FOOD", mechanism=mechanism, decision=decision,
        max_cumulative_transfer=transfer, transfer_unit=unit,
        pack_quantity=100.0, pack_quantity_unit="g",
        valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
        valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
        assessment_rationale="Test-only quality endpoint", source_id="TEST-SOURCE",
        source_locator="test-only-locator", approval_id="TEST-APPROVAL",
        evidence_basis=EvidenceBasis.MEASURED,
    )
    values.update(changes)
    return ProtectionAssessment(**values)


class RequirementCardTests(unittest.TestCase):
    def test_no_evidence_means_no_numeric_barriers_or_candidate_permission(self):
        card = derive_requirement_card(_enriched())
        report = card.report()
        self.assertEqual(report["service_temperature_min_c"], 4.0)
        self.assertEqual(report["service_temperature_max_c"], 9.0)
        self.assertEqual(report["storage_type"], "chilled")
        self.assertEqual(
            [(item["phase"], item["temperature_c"]) for item in report["exposures"]],
            [("storage", 4.0), ("transport", 6.0), ("transport_max_excursion", 9.0)],
        )
        self.assertTrue(report["exposures"][2]["safety_check_only"])
        self.assertIsNone(report["transport_relative_humidity_pct"])
        self.assertIsNone(report["transport_excursion_duration_hours"])
        self.assertEqual(report["mechanism_status"]["oxygen_ingress"], "unassessed")
        self.assertEqual(report["transfer_budgets"], [])
        self.assertIsNone(report["otr_target"])
        self.assertIsNone(report["wvtr_target"])
        self.assertFalse(report["candidate_screening_allowed"])
        self.assertIn("respiration_route_unclassified", report["gaps"])
        self.assertEqual(report["handling_severity"], "high")

    def test_approved_exact_scope_gives_per_pack_target_average_not_otr(self):
        card = derive_requirement_card(_enriched(), (_assessment(),))
        budget = card.transfer_budgets[0]
        self.assertEqual(budget.max_cumulative_transfer, 20.0)
        self.assertEqual(budget.target_average_transfer_per_day, 2.0)
        self.assertEqual(budget.unit, "mmol_o2_per_pack")
        self.assertEqual(card.report()["mechanism_status"]["oxygen_ingress"], "source_limit")
        self.assertIsNone(card.report()["otr_target"])
        self.assertFalse(card.candidate_screening_allowed)

    def test_not_required_needs_explicit_source_assessment(self):
        assessment = _assessment(
            ProtectionMechanism.MOISTURE_GAIN, AssessmentDecision.NOT_REQUIRED,
            None, None,
        )
        card = derive_requirement_card(_enriched(), (assessment,))
        self.assertEqual(
            card.report()["mechanism_status"]["moisture_gain"],
            "source_assessed_not_required",
        )
        self.assertEqual(card.transfer_budgets, ())

    def test_excursion_quantity_and_unknown_transit_rh_block_out_of_scope_limits(self):
        base = _assessment()
        cases = (
            (_enriched(max_temperature=11), base, "oxygen_ingress_temperature_out_of_scope"),
            (_enriched(quantity=101), base, "oxygen_ingress_pack_quantity_out_of_scope"),
            (_enriched(), replace(base, valid_rh_min_pct=50),
             "oxygen_ingress_transport_humidity_unknown"),
        )
        for enriched, assessment, gap in cases:
            with self.subTest(gap=gap):
                card = derive_requirement_card(enriched, (assessment,))
                self.assertIn(gap, card.gaps)
                self.assertEqual(card.transfer_budgets, ())
                self.assertEqual(card.applied_assessments, ())

    def test_respiring_route_does_not_skip_gas_balance(self):
        card = derive_requirement_card(_enriched(route="respiration_evidence_present"))
        self.assertIn("produce_gas_balance_pending_stop_4", card.gaps)
        self.assertNotIn("respiration_route_unclassified", card.gaps)

    def test_unmatched_food_assessment_is_not_borrowed(self):
        card = derive_requirement_card(
            _enriched(), (_assessment(food_reference_id="OTHER-FOOD"),),
        )
        self.assertEqual(card.transfer_budgets, ())
        self.assertIn("oxygen_ingress_unassessed", card.gaps)

    def test_duplicate_food_mechanism_is_not_silently_selected(self):
        with self.assertRaisesRegex(ValueError, "multiple assessments"):
            derive_requirement_card(_enriched(), (_assessment(), _assessment()))


class EvidenceValidationTests(unittest.TestCase):
    def test_estimate_or_supplier_report_cannot_be_approved_limit(self):
        for basis in (EvidenceBasis.ESTIMATED, EvidenceBasis.SUPPLIER_REPORTED):
            with self.subTest(basis=basis), self.assertRaisesRegex(ValueError, "measured"):
                _assessment(evidence_basis=basis)

    def test_limit_units_and_numbers_are_guarded(self):
        for changes in (
            {"max_cumulative_transfer": 0}, {"max_cumulative_transfer": True},
            {"transfer_unit": "g_h2o_per_pack"}, {"valid_rh_max_pct": 101},
            {"approval_id": ""}, {"valid_temperature_min_c": -274},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _assessment(**changes)

    def test_not_required_cannot_hide_a_number(self):
        with self.assertRaisesRegex(ValueError, "not_required"):
            _assessment(decision=AssessmentDecision.NOT_REQUIRED)

    def test_json_register_requires_explicit_schema_and_unique_keys(self):
        entry = asdict(_assessment())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessments.json"
            path.write_text(
                json.dumps({"schema_version": 1, "assessments": [entry]}), encoding="utf-8",
            )
            loaded = load_protection_assessments(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].mechanism, ProtectionMechanism.OXYGEN_INGRESS)
            path.write_text(
                json.dumps({"schema_version": 1, "assessments": [entry, entry]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_protection_assessments(path)
            path.write_text(
                json.dumps({"schema_version": 1, "assessments": [{**entry, "extra": 1}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unexpected"):
                load_protection_assessments(path)
            path.write_text(
                '{"schema_version":1,"schema_version":1,"assessments":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_protection_assessments(path)
            path.write_text('{"schema_version":true,"assessments":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                load_protection_assessments(path)


if __name__ == "__main__":
    unittest.main()
