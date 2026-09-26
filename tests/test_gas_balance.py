"""Hand-worked local balances are tests, never training observations."""

import json
import unittest
from dataclasses import asdict, replace
from types import SimpleNamespace

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.gas_balance import (
    CO2_MOLAR_MASS_G_MOL, O2_MOLAR_MASS_G_MOL,
    FinishedPackageGasObservation, audit_gas_profile,
    calculate_local_balance, parse_gas_observations,
)
from packsense.respiration import KineticEvidence


def _enriched(*, mass=1000.0, route="confirmed_respiring"):
    scenario = SimpleNamespace(
        record_id="TEST-CASE",
        net_pack_quantity=mass, net_pack_quantity_unit="g",
        respiration_rate=O2_MOLAR_MASS_G_MOL,
        respiration_rate_unit="mg O2/kg/h",
        respiration_reference_temperature_c=10.0,
        storage_temperature_c=10.0, storage_relative_humidity_pct=90.0,
        transport_temperature_c=10.0, transport_max_temperature_c=15.0,
        transport_duration_hours=8.0,
    )
    return EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "TEST-HASH",
        "missing", route, exposure_profile(scenario),
    )


def _rate(unit, measured):
    return KineticEvidence(
        food_reference_id="TEST-FOOD", measured_rate=measured,
        rate_unit=unit, reference_temperature_c=10.0, q10=2.0,
        valid_temperature_min_c=5.0, valid_temperature_max_c=20.0,
        reference_o2_pct=5.0, reference_co2_pct=5.0,
        rate_source_id=f"TEST-{unit}-SOURCE", q10_source_id="TEST-Q10-SOURCE",
        source_locator="test-only-page", approval_id="TEST-REVIEW",
        rate_basis=EvidenceBasis.MEASURED,
        q10_basis=EvidenceBasis.VALIDATED_CORRECTION,
    )


def _observation(**changes):
    values = dict(
        record_id="TEST-CASE",
        food_reference_id="TEST-FOOD", structure_id="TEST-STRUCTURE",
        phase="storage", temperature_c=10.0, fill_mass_g=1000.0,
        headspace_mmol=100.0, initial_o2_pct=5.0, initial_co2_pct=5.0,
        external_o2_pct=20.0, external_co2_pct=0.1,
        o2_transfer_mmol_h=0.5, co2_transfer_mmol_h=-0.25,
        min_o2_pct=3.0, max_co2_pct=10.0,
        transfer_source_id="TEST-TRANSFER", gas_limit_source_id="TEST-LIMITS",
        structure_approval_id="TEST-STRUCTURE-REVIEW",
        source_locator="test-only-page", approval_id="TEST-GAS-REVIEW",
        transfer_basis=EvidenceBasis.MEASURED,
        gas_limit_basis=EvidenceBasis.MEASURED,
    )
    values.update(changes)
    return FinishedPackageGasObservation(**values)


class GasBalanceTests(unittest.TestCase):
    def test_local_inventory_and_signed_flux_are_exact(self) -> None:
        result = calculate_local_balance(
            _enriched(), _observation(),
            _rate("mg O2/kg/h", O2_MOLAR_MASS_G_MOL),
            _rate("mg CO2/kg/h", CO2_MOLAR_MASS_G_MOL),
        )
        self.assertEqual(result.status, "local_balance_only")
        self.assertAlmostEqual(result.o2_inventory_mmol, 5.0)
        self.assertAlmostEqual(result.co2_inventory_mmol, 5.0)
        self.assertAlmostEqual(result.o2_net_mmol_h, -0.5)
        self.assertAlmostEqual(result.co2_net_mmol_h, 0.75)
        self.assertFalse(result.report()["gas_safety_certified"])
        self.assertFalse(result.report()["shelf_life_predicted"])

    def test_initial_limit_violation_is_flagged_without_safety_approval(self) -> None:
        observation = _observation(initial_o2_pct=2.0)
        oxygen = replace(_rate("mg O2/kg/h", O2_MOLAR_MASS_G_MOL),
                         reference_o2_pct=2.0)
        carbon = replace(_rate("mg CO2/kg/h", CO2_MOLAR_MASS_G_MOL),
                         reference_o2_pct=2.0)
        result = calculate_local_balance(_enriched(), observation, oxygen, carbon)
        self.assertEqual(result.status, "initial_limit_violation")
        self.assertIn("initial_o2_below_limit", result.warning_codes)

    def test_missing_phase_does_not_borrow_another_temperature(self) -> None:
        results = audit_gas_profile(
            _enriched(), (_observation(),),
            _rate("mg O2/kg/h", O2_MOLAR_MASS_G_MOL),
            _rate("mg CO2/kg/h", CO2_MOLAR_MASS_G_MOL),
            structure_id="TEST-STRUCTURE",
        )
        self.assertEqual([item.phase for item in results],
                         ["storage", "transport", "transport_max_excursion"])
        self.assertEqual(results[1].status, "unresolved")
        self.assertIsNone(results[2].o2_net_mmol_h)

    def test_food_mass_route_and_scenario_rate_mismatches_block(self) -> None:
        oxygen = _rate("mg O2/kg/h", O2_MOLAR_MASS_G_MOL)
        carbon = _rate("mg CO2/kg/h", CO2_MOLAR_MASS_G_MOL)
        cases = (
            (_enriched(mass=900), _observation(), "fill_mass_mismatch_or_volume_only"),
            (_enriched(route="unclassified"), _observation(), "route_not_confirmed_respiring"),
            (_enriched(), _observation(record_id="OTHER"), "scenario_record_mismatch"),
            (_enriched(), _observation(), "scenario_rate_out_of_scope:reference_measurement_mismatch"),
        )
        for enriched, observation, expected in cases:
            if expected.startswith("scenario_rate"):
                oxygen_case = replace(oxygen, measured_rate=oxygen.measured_rate + 1)
            else:
                oxygen_case = oxygen
            with self.subTest(expected=expected):
                result = calculate_local_balance(enriched, observation, oxygen_case, carbon)
                self.assertEqual(result.warning_codes, (expected,))

    def test_estimated_transfer_and_limits_are_rejected(self) -> None:
        for changes in (
            {"transfer_basis": EvidenceBasis.ESTIMATED},
            {"gas_limit_basis": EvidenceBasis.ESTIMATED},
            {"headspace_mmol": 0},
            {"initial_o2_pct": 90, "initial_co2_pct": 20},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _observation(**changes)

    def test_register_rejects_duplicate_food_structure_phase(self) -> None:
        entry = asdict(_observation())
        accepted = parse_gas_observations(json.dumps({
            "schema_version": 1, "observations": [entry],
        }).encode())
        self.assertEqual(len(accepted), 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_gas_observations(json.dumps({
                "schema_version": 1, "observations": [entry, entry],
            }).encode())


if __name__ == "__main__":
    unittest.main()
