"""Hand-checkable kinetics cases are equation tests, not training data."""

import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario, exposure_profile
from packsense.respiration import (
    KineticEvidence, correct_rate, parse_kinetics_register, project_exposures,
)


def _enriched(*, route="confirmed_respiring", maximum=15.0, unit="mg CO2/kg/h"):
    scenario = SimpleNamespace(
        record_id="TEST-CASE", respiration_rate=10.0,
        respiration_rate_unit=unit, respiration_reference_temperature_c=5.0,
        storage_temperature_c=5.0, storage_relative_humidity_pct=90.0,
        transport_temperature_c=10.0, transport_max_temperature_c=maximum,
        transport_duration_hours=8.0,
    )
    return EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "TEST-HASH",
        "missing", route, exposure_profile(scenario),
    )


def _evidence(**changes):
    values = dict(
        food_reference_id="TEST-FOOD", measured_rate=10.0,
        rate_unit="mg CO2/kg/h", reference_temperature_c=5.0,
        q10=2.0, valid_temperature_min_c=0.0,
        valid_temperature_max_c=20.0, reference_o2_pct=20.0,
        reference_co2_pct=0.1, rate_source_id="TEST-RATE-SOURCE",
        q10_source_id="TEST-KINETICS-SOURCE", source_locator="test-page",
        approval_id="TEST-REVIEW",
        rate_basis=EvidenceBasis.MEASURED,
        q10_basis=EvidenceBasis.VALIDATED_CORRECTION,
    )
    values.update(changes)
    return KineticEvidence(**values)


class KineticsTests(unittest.TestCase):
    def test_q10_math_keeps_gas_species_and_phases_separate(self) -> None:
        projections = project_exposures(_enriched(), _evidence())
        self.assertEqual([round(x.rate, 6) for x in projections],
                         [10.0, 14.142136, 20.0])
        self.assertTrue(all(x.rate_unit == "mg CO2/kg/h" for x in projections))
        self.assertIsNone(projections[0].duration_hours)
        self.assertTrue(projections[2].safety_check_only)
        self.assertIsNone(projections[2].duration_hours)

    def test_excursion_outside_validated_range_is_not_extrapolated(self) -> None:
        projections = project_exposures(_enriched(maximum=25.0), _evidence())
        self.assertIsNone(projections[-1].rate)
        self.assertEqual(projections[-1].status, "temperature_out_of_scope")

    def test_reference_atmosphere_only_not_an_implied_map_rate(self) -> None:
        value, status = correct_rate(_enriched(), _evidence(), 10.0, 5.0, 5.0)
        self.assertIsNone(value)
        self.assertEqual(status, "atmosphere_out_of_scope")

    def test_route_food_and_measured_rate_must_match(self) -> None:
        cases = (
            (_enriched(route="unclassified"), _evidence(), "route_not_confirmed_respiring"),
            (_enriched(), _evidence(food_reference_id="OTHER"), "food_id_mismatch"),
            (_enriched(), _evidence(measured_rate=11.0), "reference_measurement_mismatch"),
            (_enriched(unit="mg O2/kg/h"), _evidence(), "reference_measurement_mismatch"),
        )
        for enriched, evidence, expected in cases:
            with self.subTest(expected=expected):
                value, status = correct_rate(enriched, evidence, 10.0, 20.0, 0.1)
                self.assertIsNone(value)
                self.assertEqual(status, expected)

    def test_invalid_q10_or_gas_source_is_rejected(self) -> None:
        for changes in (
            {"q10": 0}, {"q10": float("nan")},
            {"valid_temperature_min_c": 10},
            {"reference_o2_pct": 100, "reference_co2_pct": 1},
            {"approval_id": ""},
            {"rate_basis": EvidenceBasis.ESTIMATED},
            {"q10_basis": EvidenceBasis.ESTIMATED},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _evidence(**changes)

    def test_register_rejects_duplicates_and_extra_fields(self) -> None:
        entry = asdict(_evidence())
        accepted = parse_kinetics_register(json.dumps({
            "schema_version": 1, "kinetics": [entry],
        }).encode())
        self.assertEqual(len(accepted), 1)
        for entries in ([entry, entry], [{**entry, "unreviewed": True}]):
            with self.assertRaises(ValueError):
                parse_kinetics_register(json.dumps({
                    "schema_version": 1, "kinetics": entries,
                }).encode())


if __name__ == "__main__":
    unittest.main()
