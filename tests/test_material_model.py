"""Guardrails for the material model; fixtures are never training rows."""

import unittest
from types import SimpleNamespace

from packsense.material_model import (
    FEATURE_COLUMNS, MaterialTrainingConfig, train_material_suitability,
)


class MaterialModelGateTests(unittest.TestCase):
    def setUp(self):
        self.labels = SimpleNamespace(
            register=SimpleNamespace(source_sha256="a" * 64),
            issues=(), accepted=(),
        )
        self.split = SimpleNamespace(status="not_ready", reasons=("no_labels",), manifest=None)

    def test_no_fit_without_independent_source_and_rights_approval(self):
        result = train_material_suitability(
            self.labels, self.split, None, None, {},
        )
        self.assertIsNone(result.estimator)
        self.assertFalse(result.report["model_trained"])
        self.assertEqual(result.report["status"], "not_ready")
        self.assertEqual(result.report["readiness_reasons"], [
            "independent_source_and_rights_review_not_approved"
        ])

    def test_no_fit_with_approval_but_no_real_labels(self):
        result = train_material_suitability(
            self.labels, self.split, None, None, {},
            source_and_rights_review_approved=True,
        )
        self.assertIsNone(result.estimator)
        self.assertFalse(result.report["model_trained"])
        self.assertEqual(result.report["readiness_reasons"], [
            "suitability_intake_not_ready"
        ])

    def test_config_rejects_invalid_selection_settings(self):
        for options in (
            {"regularization_candidates": ()},
            {"regularization_candidates": (float("nan"),)},
            {"max_iterations": 0},
            {"decision_threshold": 1.0},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                MaterialTrainingConfig(**options)

    def test_feature_schema_excludes_identity_and_outcome_fields(self):
        for excluded in (
            "food_reference_id", "scenario_record_id", "structure_id",
            "source_id", "source_family_id", "decision", "review_id",
        ):
            self.assertNotIn(excluded, FEATURE_COLUMNS)
        self.assertIn("storage_temperature_c", FEATURE_COLUMNS)
        self.assertIn("transport_max_temperature_c", FEATURE_COLUMNS)


if __name__ == "__main__":
    unittest.main()
