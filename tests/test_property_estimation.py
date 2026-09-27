"""Split/calibration checks without fabricated food training rows."""

import unittest
from types import SimpleNamespace

import numpy as np

from packsense.property_estimation import (
    _conformal_radius,
    _bounded_interval,
    _group_split,
    _has_analytical_derivation,
    evaluate_property,
)


class PropertyEstimationTests(unittest.TestCase):
    def test_group_split_never_leaks_a_family(self) -> None:
        groups = [f"group-{index // 2}" for index in range(100)]
        train, calibration, test = _group_split(groups)
        self.assertEqual(set(train) | set(calibration) | set(test), set(range(100)))
        self.assertFalse(set(groups[i] for i in train) & set(groups[i] for i in calibration))
        self.assertFalse(set(groups[i] for i in train) & set(groups[i] for i in test))
        self.assertFalse(set(groups[i] for i in calibration) & set(groups[i] for i in test))
        self.assertEqual(len(test), 20)
        self.assertEqual(len(train) + len(calibration), 80)
        self.assertEqual(len(calibration), 16)

    def test_interval_radius_uses_held_out_residuals(self) -> None:
        actual = np.array([1, 2, 3, 4, 5], dtype=float)
        predicted = np.array([1, 2, 3, 4, 4], dtype=float)
        self.assertEqual(_conformal_radius(actual, predicted), 1)

    def test_out_of_range_prediction_is_not_disguised_as_zero(self) -> None:
        self.assertIsNone(_bounded_interval(-1, 5))
        self.assertIsNone(_bounded_interval(101, 5))
        self.assertIsNone(_bounded_interval(50, 60))
        self.assertEqual(_bounded_interval(50, 10), (40, 60))

    def test_proxy_ph_is_not_a_training_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported training target"):
            evaluate_property((), "source-hash", "pH")

    def test_only_exact_analytical_derivation_code_is_a_label(self) -> None:
        analytical = SimpleNamespace(reference=SimpleNamespace(composition_method="moisture=A; fat=AR"))
        self.assertTrue(_has_analytical_derivation(analytical, "moisture_content_pct"))
        self.assertFalse(_has_analytical_derivation(analytical, "oil_fat_content_pct"))


if __name__ == "__main__":
    unittest.main()
