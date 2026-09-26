"""Stop-2 join behavior; test doubles are never training observations."""

import unittest
from types import SimpleNamespace

from packsense.enrichment import enrich_scenarios, exposure_profile
from packsense.ingestion import IngestionIssue, ParsedScenarioRow, ScenarioAudit
from packsense.masters import FoodMasterEntry, MasterAudit


def _scenario(*, name="REFERENCE A", reference_id=None, respiration=None):
    return SimpleNamespace(
        record_id="CASE-A", commodity_type=name, food_reference_id=reference_id,
        respiration_rate=respiration, storage_temperature_c=4.0,
        storage_relative_humidity_pct=80.0, transport_temperature_c=6.0,
        transport_max_temperature_c=9.0, transport_duration_hours=12.0,
    )


def _food(food_id, name="REFERENCE A", respiration=None):
    reference = SimpleNamespace(
        food_id=food_id, commodity_type=name, respiration_rate=respiration,
    )
    return FoodMasterEntry(2, reference, "missing")


def _audits(scenario, foods):
    scenarios = ScenarioAudit(
        "scenario.csv", "scenario-hash", None, (),
        (ParsedScenarioRow(2, {"record_id": "CASE-A"}, scenario, ()),),
    )
    masters = MasterAudit("food.xlsx", "master-hash", "Food inputs", len(foods), tuple(foods), ())
    return scenarios, masters


class ExposureTests(unittest.TestCase):
    def test_no_exposure_value_is_invented_or_averaged(self) -> None:
        storage, transit, excursion = exposure_profile(_scenario())
        self.assertEqual((storage.phase, storage.temperature_c, storage.relative_humidity_pct),
                         ("storage", 4.0, 80.0))
        self.assertIsNone(storage.duration_hours)
        self.assertEqual((transit.phase, transit.temperature_c, transit.duration_hours),
                         ("transport", 6.0, 12.0))
        self.assertIsNone(transit.relative_humidity_pct)
        self.assertEqual((excursion.phase, excursion.temperature_c),
                         ("transport_max_excursion", 9.0))
        self.assertTrue(excursion.safety_check_only)
        self.assertIsNone(excursion.duration_hours)


class FoodJoinTests(unittest.TestCase):
    def test_unique_exact_name_joins_and_keeps_hashes(self) -> None:
        audit = enrich_scenarios(*_audits(_scenario(name="  Reference   A "), [_food("FOOD-A")]))
        row = audit.rows[0]
        self.assertFalse(row.issues)
        self.assertEqual(row.enriched.food_reference.food_id, "FOOD-A")
        self.assertEqual(row.enriched.food_master_sha256, "master-hash")
        self.assertEqual(row.enriched.produce_route_status, "unclassified")
        self.assertEqual(audit.report()["unclassified_produce_route_rows"], 1)

    def test_ambiguous_name_needs_explicit_food_id(self) -> None:
        foods = [_food("FOOD-A"), _food("FOOD-B")]
        ambiguous = enrich_scenarios(*_audits(_scenario(), foods))
        self.assertIsNone(ambiguous.rows[0].enriched)
        self.assertEqual(ambiguous.rows[0].issues[0].code, "reference_ambiguous")

        selected = enrich_scenarios(*_audits(_scenario(reference_id="FOOD-B"), foods))
        self.assertEqual(selected.rows[0].enriched.food_reference.food_id, "FOOD-B")

    def test_id_and_name_must_agree(self) -> None:
        audit = enrich_scenarios(*_audits(
            _scenario(name="DIFFERENT", reference_id="FOOD-A"), [_food("FOOD-A")],
        ))
        self.assertEqual(audit.rows[0].issues[0].code, "reference_name_mismatch")

    def test_missing_reference_is_exception_not_family_guess(self) -> None:
        audit = enrich_scenarios(*_audits(_scenario(name="ABSENT"), [_food("FOOD-A")]))
        self.assertEqual(audit.rows[0].issues[0].code, "reference_not_found")

    def test_reported_respiration_requires_scenario_respiration(self) -> None:
        audit = enrich_scenarios(*_audits(_scenario(), [_food("FOOD-A", respiration=object())]))
        self.assertEqual(audit.rows[0].issues[0].code, "missing_respiration")

        supplied = enrich_scenarios(*_audits(
            _scenario(respiration=object()), [_food("FOOD-A", respiration=object())],
        ))
        self.assertEqual(supplied.rows[0].enriched.produce_route_status,
                         "respiration_evidence_present")

    def test_input_exceptions_are_preserved(self) -> None:
        issue = IngestionIssue(2, "CASE-A", "storage_temperature_c", "missing_value", "required")
        scenario_audit = ScenarioAudit(
            "scenario.csv", "scenario-hash", None, (),
            (ParsedScenarioRow(2, {"record_id": "CASE-A"}, None, (issue,)),),
        )
        food_audit = MasterAudit("food.xlsx", "master-hash", "Food inputs", 0, (), ())
        audit = enrich_scenarios(scenario_audit, food_audit)
        self.assertEqual(audit.rows[0].issues, (issue,))
        self.assertEqual(audit.report()["exception_rows"], 1)


if __name__ == "__main__":
    unittest.main()
