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

from packsense.contracts import MaterialGrade
from packsense.enrichment import EnrichedScenario, EnrichmentAudit
from packsense.material_split import MaterialSplitAudit
from packsense.material_suitability import SuitabilityAudit, SuitabilityLabel
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
    for c in config.regularization_candidates:
        candidate = _model(c, config)
        candidate.fit(x_train, y_train)
        probability = candidate.predict_proba(x_validation)[:, 1]
        scores = _scores(y_validation, probability, config.decision_threshold)
        if selected_scores is None or scores["brier_score"] < selected_scores["brier_score"]:
            selected, selected_c, selected_scores = candidate, c, scores
    report["model_trained"] = True
    report["validation"] = {
        "selected_regularization_c": selected_c,
        "candidate": selected_scores,
        "training_prevalence_baseline": baseline,
        "selected_without_test_access": True,
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
    report["test"] = {
        "opened_after_validation_selection": True,
        "candidate": _scores(
            y_test, selected.predict_proba(x_test)[:, 1], config.decision_threshold,
        ),
        "training_prevalence_baseline": _scores(
            y_test, np.full(len(y_test), prevalence), config.decision_threshold,
        ),
    }
    report["status"] = "exploratory_test_evaluated"
    report["model_validated"] = True
    report["release_status"] = "withheld_pending_external_performance_and_gate_review"
    return MaterialTrainingResult(report, selected)
