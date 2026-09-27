"""Evidence-gated exploratory classifier for reviewed food/package judgements.

The two reference masters contain features, not targets. This module accepts
only independently reviewed scenario/complete-structure suitability labels
with a frozen source/food-disjoint split. It never certifies food contact,
package feasibility, or shelf life; engineering gates remain authoritative.
"""

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping

import numpy as np
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix,
    precision_score, recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from packsense.candidate_transfer import TransferDecision
from packsense.contracts import MaterialGrade
from packsense.enrichment import EnrichedScenario, EnrichmentAudit
from packsense.material_split import MaterialSplitAudit
from packsense.material_suitability import SuitabilityAudit, SuitabilityLabel
from packsense.recommendation import (
    BasicRecommendation, CandidateStatus, RecommendationStatus,
)
from packsense.requirements import (
    ProtectionMechanism, RequirementCard, scenario_fingerprint,
)
from packsense.structure_review import (
    ReviewAttestedStructure, StructureReviewAudit, attestation_integrity_gaps,
)


MODEL_VERSION = "material-suitability-logistic-v1"
CATEGORICAL_FEATURES = (
    "food_group", "storage_type", "transport_mode", "handling_severity",
    "pack_quantity_unit", "pack_format", "layer_material_families",
)
NUMERIC_FEATURES = (
    "moisture_content_pct", "oil_fat_content_pct", "pH", "respiration_rate",
    "respiration_reference_temperature_c", "desired_shelf_life_days",
    "storage_temperature_c", "storage_relative_humidity_pct",
    "transport_duration_hours", "transport_temperature_c",
    "transport_max_temperature_c", "net_pack_quantity",
    "layer_count", "total_thickness_um", "contact_layer_thickness_um",
    "service_temperature_min_c", "service_temperature_max_c",
)
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
PARTITIONS = ("train", "validation", "test")


@dataclass(frozen=True, slots=True)
class MaterialTrainingConfig:
    """Fixed CPU baseline and validation search; no neural-network epochs."""

    regularization_candidates: tuple[float, ...] = (0.1, 1.0, 10.0)
    max_iterations: int = 2000
    decision_threshold: float = 0.5
    random_seed: int = 41

    def __post_init__(self) -> None:
        if not self.regularization_candidates or any(
            not isfinite(value) or value <= 0
            for value in self.regularization_candidates
        ):
            raise ValueError("regularization candidates must be positive and finite")
        if self.max_iterations < 1 or not 0 < self.decision_threshold < 1:
            raise ValueError("invalid iteration limit or decision threshold")


@dataclass(frozen=True, slots=True)
class MaterialTrainingResult:
    report: dict[str, Any]
    estimator: Pipeline | None


def _feature_row(
    enriched: EnrichedScenario,
    reviewed: ReviewAttestedStructure,
    grades: Mapping[str, MaterialGrade],
) -> dict[str, Any]:
    """Use inference-available properties, never source/food/structure IDs."""
    scenario = enriched.scenario
    structure = reviewed.structure
    layer_grades = [grades[layer.grade_id] for layer in structure.layers]
    return {
        "food_group": enriched.food_reference.food_group or "not_reported",
        "storage_type": scenario.storage_type.value,
        "transport_mode": scenario.transport_mode,
        "handling_severity": scenario.transport_handling_severity.value,
        "pack_quantity_unit": scenario.net_pack_quantity_unit,
        "pack_format": structure.pack_format,
        "layer_material_families": " | ".join(
            grade.material_family for grade in layer_grades
        ),
        "moisture_content_pct": scenario.moisture_content_pct,
        "oil_fat_content_pct": scenario.oil_fat_content_pct,
        "pH": scenario.pH,
        "respiration_rate": scenario.respiration_rate,
        "respiration_reference_temperature_c": scenario.respiration_reference_temperature_c,
        "desired_shelf_life_days": scenario.desired_shelf_life_days,
        "storage_temperature_c": scenario.storage_temperature_c,
        "storage_relative_humidity_pct": scenario.storage_relative_humidity_pct,
        "transport_duration_hours": scenario.transport_duration_hours,
        "transport_temperature_c": scenario.transport_temperature_c,
        "transport_max_temperature_c": scenario.transport_max_temperature_c,
        "net_pack_quantity": scenario.net_pack_quantity,
        "layer_count": len(structure.layers),
        "total_thickness_um": sum(layer.thickness_um for layer in structure.layers),
        "contact_layer_thickness_um": sum(
            layer.thickness_um for layer in structure.layers if layer.is_food_contact
        ),
        "service_temperature_min_c": structure.service_temperature_min_c,
        "service_temperature_max_c": structure.service_temperature_max_c,
    }


def _not_ready(report: dict[str, Any], reason: str) -> MaterialTrainingResult:
    report["status"] = "not_ready"
    report["readiness_reasons"] = [reason]
    return MaterialTrainingResult(report, None)


def _matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [[row[name] for name in FEATURE_COLUMNS] for row in rows], dtype=object,
    )


def _model(c: float, config: MaterialTrainingConfig) -> Pipeline:
    categorical_indices = list(range(len(CATEGORICAL_FEATURES)))
    numeric_indices = list(range(len(CATEGORICAL_FEATURES), len(FEATURE_COLUMNS)))
    return Pipeline([
        ("preprocess", ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical_indices),
            ("numeric", Pipeline([
                ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scale", StandardScaler()),
            ]), numeric_indices),
        ])),
        ("classifier", LogisticRegression(
            C=c, max_iter=config.max_iterations, random_state=config.random_seed,
        )),
    ])


def _scores(actual: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = probability >= threshold
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(
        actual, predicted, labels=[0, 1],
    ).ravel())
    return {
        "rows": len(actual),
        "brier_score": float(brier_score_loss(actual, probability)),
        "average_precision": float(average_precision_score(actual, probability)),
        "suitable_precision": float(precision_score(actual, predicted, zero_division=0)),
        "suitable_recall": float(recall_score(actual, predicted, zero_division=0)),
        "unsuitable_recall": tn / (tn + fp) if tn + fp else None,
        "false_suitable_count": fp,
        "false_suitable_rate_of_unsuitable": fp / (tn + fp) if tn + fp else None,
        "confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def _split_identity_gaps(
    partition_ids: Mapping[str, list[str]],
    labels_by_id: Mapping[str, SuitabilityLabel],
    scenarios_by_id: Mapping[str, EnrichedScenario],
) -> tuple[str, ...]:
    """Recheck critical leakage boundaries even for an in-memory split audit."""
    source_partitions: dict[str, set[str]] = {}
    food_partitions: dict[str, set[str]] = {}
    commodity_partitions: dict[str, set[str]] = {}
    scenario_partitions: dict[str, set[str]] = {}
    source_families: dict[str, set[str]] = {}
    gaps = set()
    for partition, label_ids in partition_ids.items():
        for label_id in label_ids:
            label = labels_by_id[label_id]
            enriched = scenarios_by_id.get(label.scenario_record_id)
            if enriched is None:
                gaps.add("label_feature_join_incomplete")
                continue
            if label.food_reference_id != enriched.food_reference.food_id:
                gaps.add("label_food_reference_mismatch")
            commodity = enriched.food_reference.commodity_type
            if not isinstance(commodity, str) or not commodity.strip():
                gaps.add("food_commodity_name_missing")
                continue
            commodity_key = " ".join(commodity.split()).casefold()
            for table, key in (
                (source_partitions, label.source_family_id),
                (food_partitions, label.food_reference_id),
                (commodity_partitions, commodity_key),
                (scenario_partitions, label.scenario_record_id),
            ):
                table.setdefault(key, set()).add(partition)
            source_families.setdefault(label.source_id, set()).add(label.source_family_id)
    if any(len(parts) > 1 for parts in source_partitions.values()):
        gaps.add("source_family_crosses_partitions")
    if any(len(parts) > 1 for parts in food_partitions.values()):
        gaps.add("food_reference_crosses_partitions")
    if any(len(parts) > 1 for parts in commodity_partitions.values()):
        gaps.add("commodity_name_crosses_partitions")
    if any(len(parts) > 1 for parts in scenario_partitions.values()):
        gaps.add("scenario_crosses_partitions")
    if any(len(families) > 1 for families in source_families.values()):
        gaps.add("source_id_crosses_source_families")
    return tuple(sorted(gaps))


def _labelled_pair_ranking(
    entries: list[tuple[SuitabilityLabel, dict[str, Any]]],
    probability: np.ndarray,
) -> dict[str, Any]:
    """Score only within-scenario, explicitly judged package alternatives.

    Missing scenario/package pairs are never treated as negative labels.
    A tied top score containing an unsuitable package is not a top-1 hit.
    """
    if len(entries) != len(probability) or not np.all(np.isfinite(probability)) or (
        np.any(probability < 0) or np.any(probability > 1)
    ):
        raise ValueError("ranking probabilities must be finite and aligned with labels")
    by_scenario: dict[str, list[tuple[SuitabilityLabel, float]]] = {}
    for (label, _), score in zip(entries, probability, strict=True):
        by_scenario.setdefault(label.scenario_record_id, []).append((label, float(score)))
    evaluable = 0
    top1_hits = 0
    top_score_ties = 0
    compared_pairs = 0
    correctly_ordered_pairs = 0
    tied_pairs = 0
    for rows in by_scenario.values():
        positive = [(label, score) for label, score in rows
                    if label.decision == "suitable"]
        negative = [(label, score) for label, score in rows
                    if label.decision == "unsuitable"]
        if not positive or not negative:
            continue
        evaluable += 1
        highest = max(score for _, score in rows)
        leaders = [label for label, score in rows if score == highest]
        if len(leaders) > 1:
            top_score_ties += 1
        if all(label.decision == "suitable" for label in leaders):
            top1_hits += 1
        for _, positive_score in positive:
            for _, negative_score in negative:
                compared_pairs += 1
                correctly_ordered_pairs += positive_score > negative_score
                tied_pairs += positive_score == negative_score
    return {
        "scope": "explicitly_judged_alternatives_within_same_scenario_only",
        "status": "evaluable" if evaluable else "not_evaluable",
        "scenarios_with_labels": len(by_scenario),
        "scenarios_with_both_decisions": evaluable,
        "strict_top1_suitable_fraction": top1_hits / evaluable if evaluable else None,
        "top_score_tie_scenarios": top_score_ties,
        "suitable_unsuitable_pairs": compared_pairs,
        "strict_pairwise_correct_fraction": (
            correctly_ordered_pairs / compared_pairs if compared_pairs else None
        ),
        "tied_suitable_unsuitable_pairs": tied_pairs,
        "unlabelled_candidates_evaluated": False,
    }


def train_material_suitability(
    labels: SuitabilityAudit,
    split: MaterialSplitAudit,
    enriched: EnrichmentAudit,
    structures: StructureReviewAudit,
    grades: Mapping[str, MaterialGrade],
    *,
    source_and_rights_review_approved: bool = False,
    config: MaterialTrainingConfig = MaterialTrainingConfig(),
) -> MaterialTrainingResult:
    """Fit only reviewed labels; reserve the test set until validation passes.

    The approval flag records an *external human decision*. Code checks source
    references and hashes but cannot authenticate the underlying papers,
    suitability interpretations, or permission to use them for training.
    """
    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "training_config": asdict(config),
        "scikit_learn_version": sklearn.__version__,
        "register_sha256": labels.register.source_sha256,
        "split_status": split.status,
        "split_manifest_sha256": (
            split.manifest.get("manifest_sha256") if split.manifest else None
        ),
        "feature_fields": {
            "categorical": list(CATEGORICAL_FEATURES),
            "numeric": list(NUMERIC_FEATURES),
            "excluded": [
                "food_reference_id", "scenario_record_id", "structure_id",
                "source_id", "source_family_id", "review_id", "decision",
            ],
        },
        "target": "independently reviewed suitable versus unsuitable judgement",
        "source_authenticity_verified_by_code": False,
        "source_and_rights_review_approved": source_and_rights_review_approved,
        "model_trained": False,
        "model_evaluated": False,
        "model_validated": False,
        "release_status": "withheld",
        "package_feasible": False,
        "shelf_life_predicted": False,
    }
    if type(source_and_rights_review_approved) is not bool or not source_and_rights_review_approved:
        return _not_ready(report, "independent_source_and_rights_review_not_approved")
    if labels.issues or not labels.accepted:
        return _not_ready(report, "suitability_intake_not_ready")
    if split.status != "allocation_prepared" or split.reasons or split.manifest is None:
        return _not_ready(report, "frozen_source_food_group_split_not_ready")
    manifest = split.manifest
    source_fields = (
        "scenario_sha256", "food_master_sha256", "material_master_sha256",
        "structure_catalogue_sha256", "structure_review_sha256",
    )
    if any(manifest.get(field) != getattr(labels.register, field) for field in source_fields):
        return _not_ready(report, "split_and_label_source_hash_mismatch")
    if manifest.get("suitability_register_sha256") != labels.register.source_sha256:
        return _not_ready(report, "split_and_label_register_hash_mismatch")
    report["source_hashes"] = {
        field: getattr(labels.register, field) for field in source_fields
    }
    if enriched.scenario_sha256 != labels.register.scenario_sha256 or (
        enriched.food_master_sha256 != labels.register.food_master_sha256
    ):
        return _not_ready(report, "enrichment_source_hash_mismatch")
    if structures.status != "review_attested" or structures.issues or (
        structures.catalogue_sha256 != labels.register.structure_catalogue_sha256
    ) or structures.review_register_sha256 != labels.register.structure_review_sha256 or (
        attestation_integrity_gaps(structures)
    ):
        return _not_ready(report, "reviewed_structure_source_hash_mismatch")

    by_scenario = {
        item.record_id: item.enriched for item in enriched.rows
        if item.record_id is not None and item.enriched is not None
    }
    if len(by_scenario) != sum(
        item.record_id is not None and item.enriched is not None
        for item in enriched.rows
    ):
        return _not_ready(report, "duplicate_enriched_scenario_id")
    by_structure = {item.structure.structure_id: item for item in structures.reviewed}
    if len(by_structure) != len(structures.reviewed):
        return _not_ready(report, "duplicate_reviewed_structure_id")
    labels_by_id = {label.label_id: label for label in labels.accepted}
    if len(labels_by_id) != len(labels.accepted):
        return _not_ready(report, "duplicate_accepted_label_id")
    partition_ids = {
        name: manifest["partitions"][name]["label_ids"] for name in PARTITIONS
    }
    assigned_ids = [label_id for ids in partition_ids.values() for label_id in ids]
    if len(assigned_ids) != len(set(assigned_ids)) or set(assigned_ids) != set(labels_by_id):
        return _not_ready(report, "split_does_not_cover_exact_accepted_labels")
    for name in PARTITIONS:
        if set(manifest["partitions"][name]["source_family_ids"]) != {
            labels_by_id[label_id].source_family_id for label_id in partition_ids[name]
        }:
            return _not_ready(report, "split_source_families_do_not_match_labels")
    if any(not partition_ids[name] for name in PARTITIONS):
        return _not_ready(report, "empty_training_partition")
    try:
        split_gaps = _split_identity_gaps(partition_ids, labels_by_id, by_scenario)
    except (AttributeError, KeyError, TypeError):
        return _not_ready(report, "split_identity_recheck_incomplete")
    if split_gaps:
        report["split_identity_gaps"] = list(split_gaps)
        return _not_ready(report, "split_identity_recheck_failed")

    def entries(name: str) -> list[tuple[SuitabilityLabel, dict[str, Any]]]:
        result = []
        for label_id in partition_ids[name]:
            label = labels_by_id[label_id]
            scenario = by_scenario[label.scenario_record_id]
            structure = by_structure[label.structure_id]
            result.append((label, _feature_row(scenario, structure, grades)))
        return result

    try:
        training = entries("train")
        validation = entries("validation")
    except (KeyError, AttributeError, TypeError):
        return _not_ready(report, "label_feature_join_incomplete")
    y_train = np.asarray([int(label.decision == "suitable") for label, _ in training])
    y_validation = np.asarray([int(label.decision == "suitable") for label, _ in validation])
    if len(set(y_train)) != 2 or len(set(y_validation)) != 2:
        return _not_ready(report, "train_or_validation_has_one_decision_class")
    x_train = _matrix([row for _, row in training])
    x_validation = _matrix([row for _, row in validation])
    prevalence = float(np.mean(y_train))
    baseline = _scores(
        y_validation, np.full(len(y_validation), prevalence), config.decision_threshold,
    )
    selected: Pipeline | None = None
    selected_c = None
    selected_scores = None
    selected_probability = None
    for c in config.regularization_candidates:
        candidate = _model(c, config)
        candidate.fit(x_train, y_train)
        probability = candidate.predict_proba(x_validation)[:, 1]
        scores = _scores(y_validation, probability, config.decision_threshold)
        if selected_scores is None or scores["brier_score"] < selected_scores["brier_score"]:
            selected, selected_c, selected_scores = candidate, c, scores
            selected_probability = probability
    report["model_trained"] = True
    report["validation"] = {
        "selected_regularization_c": selected_c,
        "candidate": selected_scores,
        "training_prevalence_baseline": baseline,
        "selected_without_test_access": True,
        "labelled_pair_ranking": (
            _labelled_pair_ranking(validation, selected_probability)
            if selected_probability is not None else None
        ),
    }
    if selected is None or selected_scores is None or (
        selected_scores["brier_score"] >= baseline["brier_score"]
    ):
        report["status"] = "validation_baseline_not_beaten"
        return MaterialTrainingResult(report, None)

    # Only now open the independently held-out test partition. Do not refit
    # encoders or classifier with validation/test data after model selection.
    try:
        testing = entries("test")
    except (KeyError, AttributeError, TypeError):
        return _not_ready(report, "test_label_feature_join_incomplete")
    y_test = np.asarray([int(label.decision == "suitable") for label, _ in testing])
    if len(set(y_test)) != 2:
        return _not_ready(report, "test_has_one_decision_class")
    x_test = _matrix([row for _, row in testing])
    test_probability = selected.predict_proba(x_test)[:, 1]
    test_candidate = _scores(y_test, test_probability, config.decision_threshold)
    test_baseline = _scores(
        y_test, np.full(len(y_test), prevalence), config.decision_threshold,
    )
    report["test"] = {
        "opened_after_validation_selection": True,
        "candidate": test_candidate,
        "training_prevalence_baseline": test_baseline,
        "brier_baseline_beaten": (
            test_candidate["brier_score"] < test_baseline["brier_score"]
        ),
        "labelled_pair_ranking": _labelled_pair_ranking(testing, test_probability),
    }
    report["status"] = "exploratory_test_evaluated"
    report["model_evaluated"] = True
    # A held-out score measures agreement with reviewed judgements. It does
    # not establish real-world package suitability or approve deployment.
    report["release_status"] = "withheld_pending_external_performance_and_gate_review"
    return MaterialTrainingResult(report, selected)


def score_exploratory_candidates(
    trained: MaterialTrainingResult,
    enriched: EnrichedScenario,
    card: RequirementCard,
    shortlist: BasicRecommendation,
    structures: StructureReviewAudit,
    grades: Mapping[str, MaterialGrade],
    *,
    material_master_sha256: str,
) -> dict[str, Any]:
    """Score only engineering-screened packages for offline comparison.

    The output cannot set a preferred package or enter the batch recommendation
    result. It measures agreement with reviewed judgements, not food safety.
    No current real PackSense data can satisfy the preceding training gate.
    """
    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "record_id": enriched.scenario.record_id,
        "status": "not_ready",
        "reason_codes": [],
        "scores": [],
        "engineering_preferred_structure_id": shortlist.preferred_structure_id,
        "model_preferred_structure_id": None,
        "recommendation_changed": False,
        "package_feasible": False,
        "release_status": "withheld",
    }

    def refuse(reason: str) -> dict[str, Any]:
        report["reason_codes"] = [reason]
        return report

    training_report = trained.report
    test_report = training_report.get("test")
    if (trained.estimator is None
            or training_report.get("model_version") != MODEL_VERSION
            or training_report.get("status") != "exploratory_test_evaluated"
            or training_report.get("model_trained") is not True
            or training_report.get("model_evaluated") is not True
            or training_report.get("model_validated") is not False
            or training_report.get("source_and_rights_review_approved") is not True
            or training_report.get("release_status")
            != "withheld_pending_external_performance_and_gate_review"
            or not isinstance(test_report, dict)
            or test_report.get("brier_baseline_beaten") is not True):
        return refuse("exploratory_training_gate_not_satisfied")
    source_hashes = training_report.get("source_hashes")
    if not isinstance(source_hashes, dict) or any(
        source_hashes.get(name) != current
        for name, current in (
            ("food_master_sha256", enriched.food_master_sha256),
            ("material_master_sha256", material_master_sha256),
            ("structure_catalogue_sha256", structures.catalogue_sha256),
            ("structure_review_sha256", structures.review_register_sha256),
        )
    ):
        return refuse("model_and_current_source_versions_differ")
    if (shortlist.status is not RecommendationStatus.PRELIMINARY_SHORTLIST
            or shortlist.record_id != enriched.scenario.record_id
            or shortlist.food_reference_id != enriched.food_reference.food_id
            or card.record_id != shortlist.record_id
            or card.food_reference_id != shortlist.food_reference_id
            or card.food_master_sha256 != enriched.food_master_sha256
            or shortlist.food_master_sha256 != enriched.food_master_sha256
            or shortlist.scenario_fingerprint != scenario_fingerprint(card)):
        return refuse("engineering_shortlist_scenario_mismatch")
    if (structures.status != "review_attested" or structures.issues
            or attestation_integrity_gaps(structures)):
        return refuse("reviewed_structure_gate_not_satisfied")

    by_structure = {item.structure.structure_id: item for item in structures.reviewed}
    eligible = [item for item in shortlist.candidates
                if item.status is CandidateStatus.ELIGIBLE_FOR_SHORTLIST]
    if not eligible or len(by_structure) != len(structures.reviewed) or (
        len({item.structure_id for item in shortlist.candidates})
        != len(shortlist.candidates)
    ):
        return refuse("eligible_reviewed_candidates_missing_or_duplicate")
    feature_rows: list[dict[str, Any]] = []
    for candidate in eligible:
        reviewed = by_structure.get(candidate.structure_id)
        if (reviewed is None
                or candidate.catalogue_sha256 != structures.catalogue_sha256
                or candidate.material_master_sha256 != material_master_sha256
                or candidate.review_register_sha256 != structures.review_register_sha256
                or candidate.review_id != reviewed.review_id):
            return refuse("eligible_candidate_review_binding_mismatch")
        if (len(candidate.transfer_checks) != len(ProtectionMechanism)
                or {check.mechanism for check in candidate.transfer_checks}
                != set(ProtectionMechanism)
                or any(check.decision not in (
                    TransferDecision.WITHIN_BUDGET, TransferDecision.NOT_REQUIRED,
                ) for check in candidate.transfer_checks)):
            return refuse("eligible_candidate_transfer_gate_mismatch")
        try:
            feature_rows.append(_feature_row(enriched, reviewed, grades))
        except KeyError:
            return refuse("eligible_candidate_material_grade_missing")

    classes = np.asarray(getattr(trained.estimator, "classes_", None))
    if classes.shape != (2,) or not np.array_equal(classes, [0, 1]):
        return refuse("model_class_order_unexpected")
    probabilities = np.asarray(
        trained.estimator.predict_proba(_matrix(feature_rows)), dtype=float,
    )
    if (probabilities.shape != (len(eligible), 2)
            or not np.all(np.isfinite(probabilities))
            or np.any(probabilities < 0) or np.any(probabilities > 1)
            or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-9)):
        return refuse("model_probability_output_invalid")
    report["status"] = "exploratory_scores_withheld"
    report["training_register_sha256"] = training_report["register_sha256"]
    report["split_manifest_sha256"] = training_report["split_manifest_sha256"]
    report["score_meaning"] = (
        "uncalibrated_model_probability_of_reviewed_label_not_package_safety"
    )
    report["scores"] = [
        {
            "structure_id": candidate.structure_id,
            "exploratory_suitable_label_score": float(probability[1]),
            "engineering_protection_rank": candidate.protection_rank,
        }
        for candidate, probability in sorted(
            zip(eligible, probabilities),
            key=lambda pair: (-pair[1][1], pair[0].structure_id),
        )
    ]
    return report
