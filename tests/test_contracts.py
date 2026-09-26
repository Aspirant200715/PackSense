"""Schema checks only; no fabricated food, material, or trial records."""

import unittest
from dataclasses import MISSING, fields

from packsense.contracts import (
    BarrierObservation,
    FoodReference,
    HandlingSeverity,
    MaterialGrade,
    PackageSpecification,
    PackageStructure,
    ProduceGasSpecification,
    RecommendationRecord,
    RecommendationStatus,
    ScenarioInput,
    ShelfLifeResult,
    StorageType,
    TrialOutcome,
)
from packsense.units import (
    PACK_QUANTITY_UNITS,
    REFERENCE_RESPIRATION_UNIT,
    SCENARIO_REFERENCE_COLUMNS,
    SCENARIO_REQUIRED_COLUMNS,
    SCENARIO_RESPIRATION_COLUMNS,
    SCENARIO_UNITS,
)


def field_names(model: type) -> set[str]:
    return {field.name for field in fields(model)}


class ScenarioSchemaTests(unittest.TestCase):
    def test_columns_match_architecture_contract(self) -> None:
        expected = set(
            SCENARIO_REQUIRED_COLUMNS + SCENARIO_RESPIRATION_COLUMNS
            + SCENARIO_REFERENCE_COLUMNS
        )
        self.assertEqual(expected, field_names(ScenarioInput))
        self.assertEqual(expected, set(SCENARIO_UNITS))

    def test_required_columns_have_no_default(self) -> None:
        by_name = {field.name: field for field in fields(ScenarioInput)}
        for name in SCENARIO_REQUIRED_COLUMNS:
            with self.subTest(column=name):
                self.assertIs(by_name[name].default, MISSING)
                self.assertIs(by_name[name].default_factory, MISSING)

    def test_respiration_columns_are_conditional(self) -> None:
        by_name = {field.name: field for field in fields(ScenarioInput)}
        for name in SCENARIO_RESPIRATION_COLUMNS:
            with self.subTest(column=name):
                self.assertIsNone(by_name[name].default)

    def test_reference_key_is_optional(self) -> None:
        by_name = {field.name: field for field in fields(ScenarioInput)}
        self.assertIsNone(by_name["food_reference_id"].default)

    def test_codes_and_units_are_explicit(self) -> None:
        self.assertEqual({item.value for item in StorageType}, {"ambient", "chilled", "frozen"})
        self.assertEqual({item.value for item in HandlingSeverity}, {"low", "medium", "high"})
        self.assertEqual(PACK_QUANTITY_UNITS, {"g", "kg", "mL", "L"})
        self.assertEqual(REFERENCE_RESPIRATION_UNIT, "mg CO2/kg/h")
        self.assertNotIn("oxygen_consumption_rate", SCENARIO_UNITS)


class EvidenceSchemaTests(unittest.TestCase):
    def test_food_reference_is_not_a_scenario(self) -> None:
        names = field_names(FoodReference)
        self.assertTrue({"food_id", "pH_basis", "pH_source_food", "source_citations"} <= names)
        self.assertNotIn("desired_shelf_life_days", names)
        self.assertNotIn("transport_max_temperature_c", names)

    def test_material_observation_keeps_evidence_and_conditions(self) -> None:
        observation = field_names(BarrierObservation)
        self.assertTrue(
            {"test_temperature_c", "test_relative_humidity_pct", "basis", "source_url"}
            <= observation
        )
        grade = field_names(MaterialGrade)
        self.assertTrue({"material_id", "co2tr", "co2_training_label", "source_url"} <= grade)
        structure = field_names(PackageStructure)
        self.assertTrue({"structure_id", "layers", "food_contact_evidence_id"} <= structure)

    def test_trial_label_is_observed_not_requested_life(self) -> None:
        names = field_names(TrialOutcome)
        self.assertTrue(
            {"trial_group_id", "batch_id", "source_id", "observed_days", "failure_observed"}
            <= names
        )
        self.assertNotIn("desired_shelf_life_days", names)


class OutputSchemaTests(unittest.TestCase):
    def test_output_carries_sources_and_support_scope(self) -> None:
        self.assertTrue(
            {"interval_low_days", "interval_high_days", "model_version", "validation_scope_id"}
            <= field_names(ShelfLifeResult)
        )
        self.assertTrue(
            {"gas_limit_source_id", "map_suitability"}
            <= field_names(ProduceGasSpecification)
        )
        self.assertIn("produce_gas", field_names(PackageSpecification))
        self.assertTrue(
            {"status", "exception_reasons", "rule_set_version", "scoring_config_version"}
            <= field_names(RecommendationRecord)
        )
        self.assertIn(RecommendationStatus.EXCEPTION, RecommendationStatus)
        self.assertIn(RecommendationStatus.NO_FEASIBLE_PACKAGE, RecommendationStatus)

    def test_contract_records_are_immutable(self) -> None:
        for model in (
            ScenarioInput,
            FoodReference,
            BarrierObservation,
            MaterialGrade,
            PackageStructure,
            TrialOutcome,
            PackageSpecification,
            ShelfLifeResult,
            RecommendationRecord,
        ):
            with self.subTest(model=model.__name__):
                self.assertTrue(model.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
