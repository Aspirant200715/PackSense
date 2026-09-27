"""Guardrails for the material model; fixtures are never training rows."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from packsense.material_model import (
    FEATURE_COLUMNS, MaterialTrainingConfig, _engineering_baseline_agreement,
    _labelled_pair_ranking,
    _split_identity_gaps,
    train_material_suitability,
)
from packsense.candidate_transfer import TransferDecision
from packsense.recommendation import (
    BasicRecommendation, CandidateScreen, CandidateStatus, RecommendationStatus,
)
from packsense.requirements import ProtectionMechanism


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

    def test_exploratory_test_score_is_not_called_model_validation(self):
        # TEST_ONLY objects exercise report semantics; no fixture is shipped
        # as a PackSense suitability register or fitted production model.
        hashes = {
            "scenario_sha256": "1" * 64,
            "food_master_sha256": "2" * 64,
            "material_master_sha256": "3" * 64,
            "structure_catalogue_sha256": "4" * 64,
            "structure_review_sha256": "5" * 64,
        }
        decisions = ("unsuitable", "suitable") * 3
        groups = ("TRAIN_NEG", "TRAIN_POS", "VAL_NEG", "VAL_POS",
                  "TEST_NEG", "TEST_POS")
        accepted = tuple(SimpleNamespace(
            label_id=f"TEST_ONLY_{index}", scenario_record_id=f"TEST_ONLY_{index}",
            structure_id="TEST_ONLY_STRUCTURE", source_family_id=groups[index],
            food_reference_id=f"TEST_ONLY_FOOD_{index}",
            source_id=f"TEST_ONLY_SOURCE_{index}",
            decision=decision,
        ) for index, decision in enumerate(decisions))
        labels = SimpleNamespace(
            register=SimpleNamespace(source_sha256="a" * 64, **hashes),
            issues=(), accepted=accepted,
        )
        partitions = {
            name: {
                "label_ids": [accepted[i].label_id for i in indices],
                "source_family_ids": [groups[i] for i in indices],
            }
            for name, indices in (
                ("train", (0, 1)), ("validation", (2, 3)), ("test", (4, 5)),
            )
        }
        split = SimpleNamespace(
            status="allocation_prepared", reasons=(),
            manifest={**hashes, "manifest_sha256": "b" * 64,
                      "suitability_register_sha256": "a" * 64,
                      "partitions": partitions},
        )
        enriched = SimpleNamespace(
            scenario_sha256=hashes["scenario_sha256"],
            food_master_sha256=hashes["food_master_sha256"],
            rows=tuple(SimpleNamespace(
                record_id=label.scenario_record_id,
                enriched=SimpleNamespace(
                    scenario=SimpleNamespace(record_id=label.scenario_record_id),
                    food_reference=SimpleNamespace(
                        food_id=label.food_reference_id,
                        commodity_type=f"TEST_ONLY_COMMODITY_{index}",
                    ),
                ),
            ) for index, label in enumerate(accepted)),
        )
        structures = SimpleNamespace(
            status="review_attested", issues=(),
            catalogue_sha256=hashes["structure_catalogue_sha256"],
            review_register_sha256=hashes["structure_review_sha256"],
            reviewed=(SimpleNamespace(
                structure=SimpleNamespace(structure_id="TEST_ONLY_STRUCTURE"),
            ),),
        )

        class TestOnlyEstimator:
            def fit(self, matrix, targets):
                return self

            def predict_proba(self, matrix):
                positive = np.asarray(matrix[:, len(FEATURE_COLUMNS) - 1],
                                      dtype=float)
                positive = np.where(positive > 0, 0.9, 0.1)
                return np.column_stack((1 - positive, positive))

        def feature_row(scenario, reviewed, grades):
            index = int(scenario.scenario.record_id.rsplit("_", 1)[1])
            return {name: (1.0 if index % 2 else -1.0)
                    for name in FEATURE_COLUMNS}

        with patch("packsense.material_model.attestation_integrity_gaps", return_value=()), \
                patch("packsense.material_model._feature_row", side_effect=feature_row), \
                patch("packsense.material_model._model", return_value=TestOnlyEstimator()):
            result = train_material_suitability(
                labels, split, enriched, structures, {},
                source_and_rights_review_approved=True,
                engineering_shortlists={},
            )
        self.assertEqual("exploratory_test_evaluated", result.report["status"])
        self.assertTrue(result.report["model_trained"])
        self.assertTrue(result.report["model_evaluated"])
        self.assertFalse(result.report["model_validated"])
        self.assertTrue(result.report["test"]["brier_baseline_beaten"])
        self.assertEqual(
            result.report["test"]["labelled_pair_ranking"]["status"], "not_evaluable"
        )
        self.assertEqual(
            result.report["test"]["engineering_screen_comparison"]["status"],
            "not_evaluable",
        )
        self.assertEqual(hashes, result.report["source_hashes"])
        self.assertIsNotNone(result.estimator)
        with patch("packsense.material_model.attestation_integrity_gaps", return_value=()), \
                patch("packsense.material_model._split_identity_gaps",
                      return_value=("food_reference_crosses_partitions",)), \
                patch("packsense.material_model._model") as model_factory:
            blocked = train_material_suitability(
                labels, split, enriched, structures, {},
                source_and_rights_review_approved=True,
            )
        model_factory.assert_not_called()
        self.assertFalse(blocked.report["model_trained"])
        self.assertEqual(blocked.report["readiness_reasons"], [
            "split_identity_recheck_failed"
        ])

    def test_in_memory_split_recheck_rejects_food_and_source_leakage(self):
        labels = {
            "train": SimpleNamespace(
                scenario_record_id="TEST_ONLY_TRAIN", food_reference_id="FOOD_A",
                source_family_id="FAMILY_A", source_id="SOURCE_SHARED",
            ),
            "test": SimpleNamespace(
                scenario_record_id="TEST_ONLY_TEST", food_reference_id="FOOD_A",
                source_family_id="FAMILY_B", source_id="SOURCE_SHARED",
            ),
        }
        scenarios = {
            "TEST_ONLY_TRAIN": SimpleNamespace(food_reference=SimpleNamespace(
                food_id="FOOD_A", commodity_type="Tomato, raw",
            )),
            "TEST_ONLY_TEST": SimpleNamespace(food_reference=SimpleNamespace(
                food_id="FOOD_A", commodity_type=" tomato,  RAW ",
            )),
        }
        gaps = _split_identity_gaps(
            {"train": ["train"], "test": ["test"]}, labels, scenarios,
        )
        self.assertIn("food_reference_crosses_partitions", gaps)
        self.assertIn("commodity_name_crosses_partitions", gaps)
        self.assertIn("source_id_crosses_source_families", gaps)

    def test_within_scenario_ranking_does_not_create_missing_negatives(self):
        labels = [
            SimpleNamespace(scenario_record_id=scenario, decision=decision)
            for scenario, decision in (
                ("TEST_ONLY_A", "suitable"),
                ("TEST_ONLY_A", "unsuitable"),
                ("TEST_ONLY_B", "suitable"),
                ("TEST_ONLY_B", "unsuitable"),
                ("TEST_ONLY_C", "suitable"),
            )
        ]
        rows = [(label, {}) for label in labels]
        result = _labelled_pair_ranking(
            rows, np.asarray([0.8, 0.2, 0.5, 0.5, 0.99]),
        )
        self.assertEqual(result["scenarios_with_labels"], 3)
        self.assertEqual(result["scenarios_with_both_decisions"], 2)
        self.assertEqual(result["strict_top1_suitable_fraction"], 0.5)
        self.assertEqual(result["strict_pairwise_correct_fraction"], 0.5)
        self.assertEqual(result["top_score_tie_scenarios"], 1)
        self.assertEqual(result["tied_suitable_unsuitable_pairs"], 1)
        self.assertFalse(result["unlabelled_candidates_evaluated"])
        with self.assertRaisesRegex(ValueError, "aligned"):
            _labelled_pair_ranking(rows, np.asarray([0.8]))

    def test_engineering_screen_comparison_keeps_unknown_pairs_unknown(self):
        checks = tuple(SimpleNamespace(
            mechanism=mechanism, decision=TransferDecision.WITHIN_BUDGET,
            record_id="TEST_ONLY_CASE", food_reference_id="TEST_ONLY_FOOD",
            structure_id="TEST_ONLY_GOOD", structure_catalogue_sha256="c" * 64,
            scenario_fingerprint="f" * 64,
        ) for mechanism in ProtectionMechanism)
        candidates = (
            CandidateScreen(
                "TEST_ONLY_GOOD", "TEST_ONLY_POUCH",
                CandidateStatus.ELIGIBLE_FOR_SHORTLIST, (), checks, 0.2,
                catalogue_sha256="c" * 64, material_master_sha256="b" * 64,
                review_register_sha256="d" * 64, review_id="TEST_ONLY_REVIEW_GOOD",
            ),
            CandidateScreen(
                "TEST_ONLY_REJECTED", "TEST_ONLY_POUCH",
                CandidateStatus.EXCLUDED, ("food_scope_mismatch",), (), None,
                catalogue_sha256="c" * 64, material_master_sha256="b" * 64,
                review_register_sha256="d" * 64,
                review_id="TEST_ONLY_REVIEW_REJECTED",
            ),
        )
        shortlist = BasicRecommendation(
            "TEST_ONLY_CASE", "TEST_ONLY_FOOD",
            RecommendationStatus.PRELIMINARY_SHORTLIST,
            "TEST_ONLY_GOOD", "source_limited_transfer_pareto_dominance",
            candidates, (), (), food_master_sha256="a" * 64,
            scenario_fingerprint="f" * 64,
            scenario_source_sha256="e" * 64,
        )
        labels = [(SimpleNamespace(
            scenario_record_id="TEST_ONLY_CASE", food_reference_id="TEST_ONLY_FOOD",
            structure_id=structure_id, decision=decision,
        ), {}) for structure_id, decision in (
            ("TEST_ONLY_GOOD", "suitable"),
            ("TEST_ONLY_REJECTED", "unsuitable"),
            ("TEST_ONLY_ABSENT", "unsuitable"),
        )]
        expected_hashes = {
            "scenario_sha256": "e" * 64,
            "food_master_sha256": "a" * 64,
            "material_master_sha256": "b" * 64,
            "structure_catalogue_sha256": "c" * 64,
            "structure_review_sha256": "d" * 64,
        }
        reviewed = {
            candidate.structure_id: SimpleNamespace(review_id=candidate.review_id)
            for candidate in candidates
        }
        with patch("packsense.material_model.derive_requirement_card", return_value=object()), \
                patch("packsense.material_model.scenario_fingerprint", return_value="f" * 64):
            result = _engineering_baseline_agreement(
                labels, {"TEST_ONLY_CASE": object()},
                {"TEST_ONLY_CASE": shortlist}, reviewed, expected_hashes,
            )
            stale = _engineering_baseline_agreement(
                labels, {"TEST_ONLY_CASE": object()},
                {"TEST_ONLY_CASE": shortlist}, reviewed,
                {**expected_hashes, "structure_catalogue_sha256": "e" * 64},
            )
            changed_check = _engineering_baseline_agreement(
                labels, {"TEST_ONLY_CASE": object()},
                {"TEST_ONLY_CASE": replace(
                    shortlist, candidates=(replace(
                        candidates[0], transfer_checks=(SimpleNamespace(
                            **{**vars(checks[0]), "scenario_fingerprint": "e" * 64}
                        ), *checks[1:]),
                    ), candidates[1]),
                )}, reviewed, expected_hashes,
            )
        self.assertEqual(result["status"], "partial_explicit_pair_coverage")
        self.assertEqual(result["screened_pairs"], 2)
        self.assertEqual(result["unknown_pairs"], 1)
        self.assertEqual(result["cross_tab_counts"]["eligible_for_shortlist_suitable"], 1)
        self.assertEqual(result["cross_tab_counts"]["excluded_unsuitable"], 1)
        self.assertEqual(result["cross_tab_counts"]["candidate_not_in_shortlist"], 1)
        self.assertEqual(stale["status"], "not_ready")
        self.assertEqual(changed_check["reason_codes"], [
            "engineering_shortlist_eligible_transfer_gate_mismatch"
        ])
        self.assertFalse(result["unlabelled_candidates_treated_as_negative"])


if __name__ == "__main__":
    unittest.main()
