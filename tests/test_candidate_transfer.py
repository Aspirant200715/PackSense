"""Calculation-only test doubles; no package or training records are supplied."""

import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from packsense.candidate_transfer import (
    FinishedPackageTransferEvidence, TransferDecision,
    check_transfer_budget as _check_transfer_budget,
    parse_transfer_register,
)
from packsense.contracts import EvidenceBasis, HandlingSeverity, StorageType
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.requirements import (
    AssessmentDecision, ProtectionAssessment, ProtectionMechanism,
    derive_requirement_card, scenario_fingerprint,
)


def check_transfer_budget(*args, **kwargs):
    return _check_transfer_budget(*args, structure_catalogue_sha256="a" * 64, **kwargs)


def _card(*, target_days=10.0, max_temperature=9.0, assessment=True,
          decision=AssessmentDecision.LIMIT):
    scenario = SimpleNamespace(
        record_id="TEST-ROW", storage_temperature_c=4.0,
        storage_type=StorageType.CHILLED, transport_mode="test-mode",
        storage_relative_humidity_pct=80.0, transport_temperature_c=6.0,
        transport_max_temperature_c=max_temperature,
        transport_duration_hours=12.0, transport_handling_severity=HandlingSeverity.HIGH,
        net_pack_quantity=100.0, net_pack_quantity_unit="g",
        desired_shelf_life_days=target_days,
    )
    enriched = EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "test-master-hash",
        "missing", "confirmed_non_respiring", exposure_profile(scenario),
    )
    if not assessment:
        return derive_requirement_card(enriched)
    source = ProtectionAssessment(
        food_reference_id="TEST-FOOD", mechanism=ProtectionMechanism.OXYGEN_INGRESS,
        decision=decision,
        max_cumulative_transfer=20.0 if decision is AssessmentDecision.LIMIT else None,
        transfer_unit="mmol_o2_per_pack" if decision is AssessmentDecision.LIMIT else None,
        pack_quantity=100.0, pack_quantity_unit="g",
        valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
        valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
        assessment_rationale="Test-only transfer limit", source_id="TEST-FOOD-SOURCE",
        source_locator="test-only-locator", approval_id="TEST-FOOD-APPROVAL",
        evidence_basis=EvidenceBasis.MEASURED,
    )
    return derive_requirement_card(enriched, (source,))


def _evidence(card, **changes):
    values = dict(
        record_id=card.record_id, food_reference_id=card.food_reference_id,
        structure_id="TEST-STRUCTURE", structure_catalogue_sha256="a" * 64,
        scenario_fingerprint=scenario_fingerprint(card),
        mechanism=ProtectionMechanism.OXYGEN_INGRESS,
        cumulative_transfer=10.0, transfer_unit="mmol_o2_per_pack",
        target_days=card.target_shelf_life_days, pack_quantity=card.net_pack_quantity,
        pack_quantity_unit=card.net_pack_quantity_unit,
        valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
        valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
        source_id="TEST-PACKAGE-SOURCE", source_locator="test-only-locator",
        approval_id="TEST-PACKAGE-APPROVAL", evidence_basis=EvidenceBasis.MEASURED,
        correction_model_id=None, correction_model_version=None,
    )
    values.update(changes)
    return FinishedPackageTransferEvidence(**values)


class CandidateTransferTests(unittest.TestCase):
    def test_exact_scoped_comparison_is_not_a_package_pass(self):
        card = _card()
        result = check_transfer_budget(
            card, "TEST-STRUCTURE", ProtectionMechanism.OXYGEN_INGRESS,
            _evidence(card, cumulative_transfer=20.0),
        )
        self.assertEqual(result.decision, TransferDecision.WITHIN_BUDGET)
        self.assertEqual(result.maximum_cumulative_transfer, 20.0)
        self.assertFalse(result.report()["package_feasible"])
        self.assertFalse(result.report()["shelf_life_predicted"])
        self.assertIn("TEST-PACKAGE-SOURCE", result.evidence_ids)

    def test_exceedance_is_a_hard_negative_not_a_life_prediction(self):
        card = _card()
        result = check_transfer_budget(
            card, "TEST-STRUCTURE", ProtectionMechanism.OXYGEN_INGRESS,
            _evidence(card, cumulative_transfer=20.01),
        )
        self.assertEqual(result.decision, TransferDecision.EXCEEDS_BUDGET)
        self.assertFalse(result.report()["package_feasible"])

    def test_absent_evidence_or_food_limit_stays_unresolved(self):
        card = _card()
        missing = check_transfer_budget(card, "TEST-STRUCTURE",
                                        ProtectionMechanism.OXYGEN_INGRESS)
        self.assertEqual(missing.decision, TransferDecision.UNRESOLVED)
        self.assertIn("finished_package_transfer_missing", missing.reason_codes)
        unknown = check_transfer_budget(
            _card(assessment=False), "TEST-STRUCTURE",
            ProtectionMechanism.OXYGEN_INGRESS, _evidence(card),
        )
        self.assertEqual(unknown.decision, TransferDecision.UNRESOLVED)
        self.assertIn("food_requirement_unassessed", unknown.reason_codes)

    def test_not_required_is_from_food_assessment_not_missing_package_data(self):
        result = check_transfer_budget(
            _card(decision=AssessmentDecision.NOT_REQUIRED), "TEST-STRUCTURE",
            ProtectionMechanism.OXYGEN_INGRESS,
        )
        self.assertEqual(result.decision, TransferDecision.NOT_REQUIRED)
        self.assertIn("TEST-FOOD-APPROVAL", result.evidence_ids)
        self.assertFalse(result.report()["package_feasible"])

    def test_scenario_fingerprint_changes_with_shelf_life_and_excursion(self):
        base = scenario_fingerprint(_card())
        self.assertEqual(base, _card().report()["scenario_fingerprint"])
        self.assertNotEqual(base, scenario_fingerprint(_card(target_days=11)))
        self.assertNotEqual(base, scenario_fingerprint(_card(max_temperature=10)))

    def test_wrong_food_structure_or_profile_cannot_be_borrowed(self):
        card = _card()
        for change in (
            {"food_reference_id": "OTHER-FOOD"},
            {"structure_id": "OTHER-STRUCTURE"},
            {"structure_catalogue_sha256": "b" * 64},
            {"scenario_fingerprint": "f" * 64},
        ):
            with self.subTest(change=change):
                result = check_transfer_budget(
                    card, "TEST-STRUCTURE", ProtectionMechanism.OXYGEN_INGRESS,
                    _evidence(card, **change),
                )
                self.assertEqual(result.decision, TransferDecision.UNRESOLVED)
                self.assertIsNone(result.observed_cumulative_transfer)

    def test_out_of_scope_quantity_time_temperature_or_humidity_is_not_compared(self):
        card = _card()
        for change, code in (
            ({"pack_quantity": 101}, "unit_quantity_or_target_days_mismatch"),
            ({"target_days": 11}, "unit_quantity_or_target_days_mismatch"),
            ({"valid_temperature_max_c": 8}, "temperature_out_of_scope"),
            ({"valid_rh_min_pct": 50}, "transport_humidity_unknown"),
        ):
            with self.subTest(change=change):
                result = check_transfer_budget(
                    card, "TEST-STRUCTURE", ProtectionMechanism.OXYGEN_INGRESS,
                    _evidence(card, **change),
                )
                self.assertEqual(result.decision, TransferDecision.UNRESOLVED)
                self.assertIn(code, result.reason_codes)

    def test_estimated_or_supplier_transfer_and_invalid_numbers_are_rejected(self):
        card = _card()
        for basis in (EvidenceBasis.ESTIMATED, EvidenceBasis.SUPPLIER_REPORTED):
            with self.subTest(basis=basis), self.assertRaisesRegex(ValueError, "measured"):
                _evidence(card, evidence_basis=basis)
        for change in ({"cumulative_transfer": -1}, {"cumulative_transfer": float("nan")},
                       {"pack_quantity": True}, {"valid_rh_max_pct": 101},
                       {"scenario_fingerprint": "not-a-hash"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                _evidence(card, **change)

    def test_corrected_value_needs_a_versioned_validated_model(self):
        card = _card()
        with self.assertRaisesRegex(ValueError, "correction_model_id"):
            _evidence(card, evidence_basis=EvidenceBasis.VALIDATED_CORRECTION)
        corrected = _evidence(
            card, evidence_basis=EvidenceBasis.VALIDATED_CORRECTION,
            correction_model_id="TEST-MODEL", correction_model_version="TEST-VERSION",
        )
        result = check_transfer_budget(
            card, "TEST-STRUCTURE", ProtectionMechanism.OXYGEN_INGRESS, corrected,
        )
        self.assertEqual(result.decision, TransferDecision.WITHIN_BUDGET)
        self.assertIn("TEST-MODEL", result.evidence_ids)
        with self.assertRaisesRegex(ValueError, "must not carry"):
            _evidence(card, correction_model_id="TEST-MODEL")

    def test_register_parser_is_strict_and_rejects_duplicate_claims(self):
        card = _card()
        item = asdict(_evidence(card))
        payload = {"schema_version": 1, "observations": [item]}
        accepted = parse_transfer_register(json.dumps(payload).encode("utf-8"))
        self.assertEqual(len(accepted), 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_transfer_register(json.dumps({**payload, "observations": [item, item]}).encode())
        with self.assertRaisesRegex(ValueError, "unexpected"):
            parse_transfer_register(json.dumps({**payload, "observations": [{**item, "extra": 1}]}).encode())
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_transfer_register(b'{"schema_version":1,"schema_version":1,"observations":[]}')
        with self.assertRaisesRegex(ValueError, "unsupported"):
            parse_transfer_register(b'{"schema_version":true,"observations":[]}')


if __name__ == "__main__":
    unittest.main()
