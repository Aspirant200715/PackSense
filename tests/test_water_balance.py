"""Water-ledger equation checks use test doubles, not food-training rows."""

import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.gas_balance import GasBalanceResult
from packsense.water_balance import (
    FinishedPackageWaterObservation, WaterBalanceResult,
    audit_water_profile, calculate_local_water, combine_produce_profile,
    parse_water_observations,
)


def _enriched(*, mass=1000.0, route="confirmed_respiring"):
    scenario = SimpleNamespace(
        record_id="TEST-CASE", net_pack_quantity=mass,
        net_pack_quantity_unit="g", storage_temperature_c=10.0,
        storage_relative_humidity_pct=90.0, transport_temperature_c=12.0,
        transport_max_temperature_c=15.0, transport_duration_hours=8.0,
    )
    return EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "TEST-HASH",
        "missing", route, exposure_profile(scenario),
    )


def _water(**changes):
    values = dict(
        record_id="TEST-CASE", food_reference_id="TEST-FOOD",
        structure_id="TEST-STRUCTURE", phase="storage", temperature_c=10.0,
        fill_mass_g=1000.0, produce_transpiration_g_h=0.2,
        respiratory_water_g_h=0.01, package_water_transfer_g_h=-0.1,
        sorbent_present=False, sorbent_uptake_g_h=0.0,
        initial_headspace_water_g=0.5, external_relative_humidity_pct=90.0,
        headspace_dew_point_c=8.0,
        coldest_internal_surface_c=7.0,
        transpiration_source_id="TEST-TRANS", respiratory_water_source_id="TEST-RESP",
        package_transfer_source_id="TEST-PACK", headspace_source_id="TEST-HEADSPACE",
        source_locator="test-only-page", approval_id="TEST-REVIEW",
        evidence_basis=EvidenceBasis.MEASURED,
    )
    values.update(changes)
    return FinishedPackageWaterObservation(**values)


def _gas(phase, warning_codes=()):
    return GasBalanceResult(
        phase, 10.0, "local_balance_only", 5.0, 5.0, -0.5, 0.75,
        warning_codes, ("TEST-SOURCE",), "TEST-CASE", "TEST-STRUCTURE",
    )


class WaterBalanceTests(unittest.TestCase):
    def test_local_water_ledger_and_measured_dewpoint_warning(self) -> None:
        result = calculate_local_water(_enriched(), _water())
        self.assertAlmostEqual(result.local_vapor_input_g_h, 0.11)
        self.assertAlmostEqual(result.surface_above_dew_point_c, -1.0)
        self.assertIn("surface_at_or_below_measured_dew_point", result.warning_codes)
        self.assertFalse(result.report()["condensation_amount_predicted"])
        self.assertFalse(result.report()["water_safety_certified"])

    def test_surface_above_dewpoint_has_no_condensation_warning(self) -> None:
        result = calculate_local_water(_enriched(), _water(coldest_internal_surface_c=9.0))
        self.assertNotIn("surface_at_or_below_measured_dew_point", result.warning_codes)

    def test_missing_transport_and_excursion_observations_remain_unresolved(self) -> None:
        results = audit_water_profile(_enriched(), (_water(),), "TEST-STRUCTURE")
        self.assertEqual([item.status for item in results],
                         ["local_water_balance_only", "unresolved", "unresolved"])
        self.assertEqual(results[2].temperature_c, 15.0)

    def test_route_record_food_mass_temperature_mismatch_blocks(self) -> None:
        cases = (
            (_enriched(route="unclassified"), _water(), "route_not_confirmed_respiring"),
            (_enriched(), _water(record_id="OTHER"), "scenario_or_food_mismatch"),
            (_enriched(mass=900), _water(), "fill_mass_mismatch_or_volume_only"),
            (_enriched(), _water(temperature_c=11), "exposure_temperature_mismatch"),
            (_enriched(), _water(external_relative_humidity_pct=70), "storage_humidity_mismatch"),
        )
        for enriched, observation, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    calculate_local_water(enriched, observation).warning_codes, (expected,),
                )

    def test_invalid_or_estimated_observations_rejected(self) -> None:
        for changes in (
            {"evidence_basis": EvidenceBasis.ESTIMATED},
            {"evidence_basis": EvidenceBasis.VALIDATED_CORRECTION},
            {"produce_transpiration_g_h": -1},
            {"sorbent_uptake_g_h": 1},
            {"headspace_dew_point_c": 11},
            {"fill_mass_g": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _water(**changes)

    def test_combined_profile_never_certifies_safety(self) -> None:
        phases = ("storage", "transport", "transport_max_excursion")
        gas = tuple(_gas(phase) for phase in phases)
        water = tuple(WaterBalanceResult(
            "TEST-CASE", "TEST-STRUCTURE", phase, 10.0,
            "local_water_balance_only", 0.5, 0.0, 1.0,
            ("surface_at_or_below_measured_dew_point",) if phase == "transport" else (),
            ("TEST-SOURCE",),
        ) for phase in phases)
        combined = combine_produce_profile(gas, water)
        self.assertEqual(combined[1].status, "local_checks_with_warnings")
        self.assertFalse(combined[0].report()["produce_safety_certified"])
        self.assertFalse(combined[0].report()["shelf_life_predicted"])

    def test_mismatched_gas_and_water_structure_rejected(self) -> None:
        gas = tuple(_gas(phase) for phase in
                    ("storage", "transport", "transport_max_excursion"))
        water = tuple(WaterBalanceResult(
            "TEST-CASE", "OTHER-STRUCTURE", phase, 10.0,
            "unresolved", None, None, None, (), (),
        ) for phase in ("storage", "transport", "transport_max_excursion"))
        with self.assertRaisesRegex(ValueError, "different scenarios"):
            combine_produce_profile(gas, water)

    def test_json_register_rejects_duplicates(self) -> None:
        entry = asdict(_water())
        del entry["structure_catalogue_sha256"]  # legacy v1 has no version binding
        self.assertEqual(len(parse_water_observations(json.dumps({
            "schema_version": 1, "observations": [entry],
        }).encode())), 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_water_observations(json.dumps({
                "schema_version": 1, "observations": [entry, entry],
            }).encode())

    def test_v2_register_requires_a_valid_catalogue_hash(self) -> None:
        entry = asdict(_water(structure_catalogue_sha256="a" * 64))
        accepted = parse_water_observations(json.dumps({
            "schema_version": 2, "observations": [entry],
        }).encode())
        self.assertEqual(accepted[0].structure_catalogue_sha256, "a" * 64)
        for invalid in (None, "not-a-hash"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_water_observations(json.dumps({
                    "schema_version": 2,
                    "observations": [{**entry, "structure_catalogue_sha256": invalid}],
                }).encode())


if __name__ == "__main__":
    unittest.main()
