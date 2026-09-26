"""Batch audit routes unmatched evidence to gaps; no training observations."""

import unittest
from types import SimpleNamespace

from packsense.contracts import EvidenceBasis
from packsense.enrichment import (
    EnrichedScenario, EnrichmentAudit, EnrichmentRow, exposure_profile,
)
from packsense.produce_audit import build_produce_audit
from packsense.water_balance import FinishedPackageWaterObservation


def _enriched(route):
    scenario = SimpleNamespace(
        record_id="TEST-CASE", storage_temperature_c=10.0,
        storage_relative_humidity_pct=90.0, transport_temperature_c=12.0,
        transport_max_temperature_c=15.0, transport_duration_hours=8.0,
        net_pack_quantity=1000.0, net_pack_quantity_unit="g",
    )
    return EnrichedScenario(
        scenario, SimpleNamespace(food_id="TEST-FOOD"), 2, "TEST-HASH",
        "missing", route, exposure_profile(scenario),
    )


class ProduceAuditTests(unittest.TestCase):
    def test_water_diagnostic_is_retained_when_gas_kinetics_missing(self) -> None:
        audit = EnrichmentAudit(
            "SCENARIO-HASH", "FOOD-HASH",
            (EnrichmentRow(2, "TEST-CASE", _enriched("confirmed_respiring"), ()),),
        )
        water = FinishedPackageWaterObservation(
            "TEST-CASE", "TEST-FOOD", "TEST-STRUCTURE", "storage", 10.0,
            1000.0, 0.2, 0.01, -0.1, False, 0.0, 0.5, 90.0, 8.0, 9.0,
            "TEST-TRANS", "TEST-RESP", "TEST-PACK", "TEST-HEADSPACE",
            "test-only-page", "TEST-REVIEW", EvidenceBasis.MEASURED,
        )
        row, = build_produce_audit(audit, (), (), (water,))
        self.assertEqual(row["status"], "unresolved")
        storage = row["structures"][0]["phases"][0]
        self.assertEqual(storage["gas"]["status"], "unresolved")
        self.assertAlmostEqual(storage["water"]["local_vapor_input_g_h"], 0.11)

    def test_missing_structure_observations_remain_unresolved(self) -> None:
        audit = EnrichmentAudit(
            "SCENARIO-HASH", "FOOD-HASH",
            (EnrichmentRow(2, "TEST-CASE", _enriched("confirmed_respiring"), ()),),
        )
        row, = build_produce_audit(audit, (), (), ())
        self.assertEqual(row["status"], "observations_missing")
        self.assertEqual(row["structures"], [])

    def test_confirmed_non_respiring_is_not_a_missing_gas_measurement(self) -> None:
        audit = EnrichmentAudit(
            "SCENARIO-HASH", "FOOD-HASH",
            (EnrichmentRow(2, "TEST-CASE", _enriched("confirmed_non_respiring"), ()),),
        )
        row, = build_produce_audit(audit, (), (), ())
        self.assertEqual(row["status"], "not_applicable")

    def test_unclassified_route_stays_unresolved(self) -> None:
        audit = EnrichmentAudit(
            "SCENARIO-HASH", "FOOD-HASH",
            (EnrichmentRow(2, "TEST-CASE", _enriched("unclassified"), ()),),
        )
        row, = build_produce_audit(audit, (), (), ())
        self.assertEqual(row["status"], "unresolved_route")


if __name__ == "__main__":
    unittest.main()
