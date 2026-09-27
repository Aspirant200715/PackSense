"""Evidence-gated, group-separated shelf-life regression for measured trials.

This is a research baseline, not a package-selection model or a release claim.
Only observed failures are regression targets; right-censored rows remain in
the split and are reported, but are not mislabeled as failure times.
"""

import argparse
import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.base import clone
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from packsense.contracts import TrialOutcome
from packsense.ingestion import InputSchemaError
from packsense.splits import (
    SplitPlan,
    ReviewRegister,
    build_split_manifest,
    parse_review_register,
    parse_split_plan,
)
from packsense.trials import TrialAudit, audit_trial_outcomes


MODEL_VERSION = "shelf-life-gbrt-v1"
CATEGORICAL_FEATURES = ("food_id", "structure_id", "structure_catalogue_version")
NUMERIC_FEATURES = (
    "fill_mass_g",
    "package_area_m2",
    "headspace_ml",
    "storage_temperature_c",
    "storage_relative_humidity_pct",
    "transport_temperature_c",
    "transport_max_temperature_c",
    "transport_duration_hours",
)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """CPU gradient-boosting configuration; iterations are not neural epochs."""

    max_iterations: int = 1000
    early_stopping_patience: int = 20
    learning_rate: float = 0.05
    max_depth: int = 2
    min_samples_leaf: int = 2
    random_seed: int = 41

    def __post_init__(self) -> None:
        if self.max_iterations < 1 or self.early_stopping_patience < 1:
            raise ValueError("iteration limit and early-stopping patience must be positive")
        if not 0 < self.learning_rate <= 1:
            raise ValueError("learning_rate must be in (0, 1]")
        if self.max_depth < 1 or self.min_samples_leaf < 1:
            raise ValueError("tree depth and minimum leaf size must be positive")


@dataclass(frozen=True, slots=True)
class TrainingResult:
    report: dict[str, Any]
    estimator: Pipeline | None


def _feature_row(outcome: TrialOutcome) -> dict[str, Any]:
    """Return inference-available facts only; exclude outcome and group IDs."""
    return {
        "food_id": outcome.food_id,
        "structure_id": outcome.structure_id,
        "structure_catalogue_version": outcome.structure_catalogue_version,
        "fill_mass_g": outcome.fill_mass_g,
        "package_area_m2": outcome.package_area_m2,
        "headspace_ml": outcome.headspace_ml,
        "storage_temperature_c": outcome.storage_temperature_c,
        "storage_relative_humidity_pct": outcome.storage_relative_humidity_pct,
        "transport_temperature_c": outcome.transport_temperature_c,
        "transport_max_temperature_c": outcome.transport_max_temperature_c,
        "transport_duration_hours": outcome.transport_duration_hours,
    }


def _macro_group_mae(actual: np.ndarray, predicted: np.ndarray,
                     groups: list[str]) -> float:
    errors: dict[str, list[float]] = {}
    for observed, estimate, group in zip(actual, predicted, groups):
        errors.setdefault(group, []).append(abs(float(observed) - float(estimate)))
    return float(np.mean([np.mean(values) for values in errors.values()]))


def _not_ready(report: dict[str, Any], reason: str) -> TrainingResult:
    report["status"] = "not_ready"
    report["readiness_reasons"] = [reason]
    report["model_trained"] = False
    report["model_validated"] = False
    report["release_status"] = "withheld"
    return TrainingResult(report, None)


def train_shelf_life(
    audit: TrialAudit,
    reviews: ReviewRegister,
    plan: SplitPlan,
    config: TrainingConfig = TrainingConfig(),
) -> TrainingResult:
    """Fit a measured-failure baseline only after the existing split gate passes.

    The untouched test partition is not read until the iteration count is fixed
    by validation and the candidate improves on a training-median baseline.
    Results remain exploratory even when the test metrics are produced.
    """
    split = build_split_manifest(audit, reviews, plan)
    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "training_config": asdict(config),
        "scikit_learn_version": sklearn.__version__,
        "trial_source_sha256": audit.source_sha256,
        "review_register_sha256": reviews.register_sha256,
        "split_plan_sha256": plan.plan_sha256,
        "split_manifest_sha256": split.report()["manifest_sha256"],
        "input_rows": audit.total_rows,
        "schema_valid_rows": len(audit.entries),
        "rejected_rows": audit.total_rows - len(audit.entries),
        "split_audit": split.report(),
        "target": "observed_days for a recorded failure only",
        "censoring_policy": (
            "right-censored rows are excluded from regression fitting and error metrics; "
            "they are retained for counts and a test lower-bound consistency diagnostic"
        ),
        "feature_policy": (
            "food, complete-structure, pack-geometry, storage and transport fields only; "
            "trial/source/group IDs and outcome fields are excluded; identifier features "
            "support only represented food/structure coverage"
        ),
        "review_attestation_limit": (
            "review IDs and hashes pass structural checks; software does not authenticate "
            "source documents, approvals, or data-use rights"
        ),
        "model_trained": False,
        "model_validated": False,
        "release_status": "withheld",
    }

    if split.status != "allocation_prepared" or split.manifest is None:
        return _not_ready(report, "reviewed_group_split_not_ready")
    if audit.issues or audit.total_rows != len(audit.entries):
        return _not_ready(report, "trial_intake_contains_rejected_rows")

    endpoints = {
        (entry.outcome.failure_criterion.strip().casefold(),
         (entry.outcome.failure_threshold or "").strip().casefold())
        for entry in audit.entries
    }
    if len(endpoints) != 1:
        return _not_ready(report, "failure_endpoint_or_threshold_is_not_uniform")
    report["failure_endpoint"] = {
        "criterion": audit.entries[0].outcome.failure_criterion,
        "threshold": audit.entries[0].outcome.failure_threshold,
    }

    assignments = {
        item["trial_id"]: (item["partition"], item["independence_group_id"])
        for item in split.manifest["assignments"]
    }
    entries_by_id = {entry.outcome.trial_id: entry for entry in audit.entries}
    if len(assignments) != len(audit.entries) or set(assignments) != set(entries_by_id):
        return _not_ready(report, "split_assignments_do_not_cover_exact_trial_rows")

    observed_by_partition: dict[str, list[Any]] = {
        "train": [], "validation": [], "test": [],
    }
    censored_by_partition: dict[str, list[Any]] = {
        "train": [], "validation": [], "test": [],
    }
    for trial_id, entry in entries_by_id.items():
        partition, _ = assignments[trial_id]
        destination = observed_by_partition if entry.outcome.failure_observed else censored_by_partition
        destination[partition].append(entry)
    if any(not observed_by_partition[partition] for partition in observed_by_partition):
        return _not_ready(report, "a_partition_has_no_observed_failure_targets")

    report["partition_rows"] = {
        partition: {
            "observed_failure_rows": len(observed_by_partition[partition]),
            "right_censored_rows": len(censored_by_partition[partition]),
            "observed_failure_groups": len({
                assignments[entry.outcome.trial_id][1]
                for entry in observed_by_partition[partition]
            }),
        }
        for partition in observed_by_partition
    }

    frames: dict[str, pd.DataFrame] = {}
    targets: dict[str, np.ndarray] = {}
    for partition in ("train", "validation"):
        entries = observed_by_partition[partition]
        frames[partition] = pd.DataFrame(
            [_feature_row(entry.outcome) for entry in entries],
            columns=CATEGORICAL_FEATURES + NUMERIC_FEATURES,
        )
        targets[partition] = np.asarray(
            [entry.outcome.observed_days for entry in entries], dtype=float,
        )
    groups = {
        partition: [assignments[entry.outcome.trial_id][1] for entry in entries]
        for partition, entries in observed_by_partition.items()
    }

    train_frame = frames["train"]
    numeric_features = [
        name for name in NUMERIC_FEATURES if not train_frame[name].isna().all()
    ]
    excluded_numeric = sorted(set(NUMERIC_FEATURES) - set(numeric_features))
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric_features),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), list(CATEGORICAL_FEATURES)),
        ],
        remainder="drop",
    )
    train_matrix = preprocessor.fit_transform(train_frame)
    validation_matrix = preprocessor.transform(frames["validation"])
    candidate = GradientBoostingRegressor(
        n_estimators=config.max_iterations,
        learning_rate=config.learning_rate,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        random_state=config.random_seed,
        loss="huber",
    )
    candidate.fit(train_matrix, targets["train"])

    best_iteration = 0
    best_validation_mae = float("inf")
    best_validation_prediction: np.ndarray | None = None
    for iteration, prediction in enumerate(
        candidate.staged_predict(validation_matrix), start=1,
    ):
        score = float(mean_absolute_error(targets["validation"], prediction))
        if score < best_validation_mae - 1e-9:
            best_iteration = iteration
            best_validation_mae = score
            best_validation_prediction = np.asarray(prediction, dtype=float)
        elif iteration - best_iteration >= config.early_stopping_patience:
            break

    if best_iteration == 0 or best_validation_prediction is None:
        return _not_ready(report, "validation_iteration_selection_failed")
    training_median = float(np.median(targets["train"]))
    validation_baseline_mae = float(mean_absolute_error(
        targets["validation"],
        np.full(len(targets["validation"]), training_median),
    ))
    report["validation"] = {
        "selected_iterations": best_iteration,
        "candidate_mae_days": best_validation_mae,
        "training_median_baseline_mae_days": validation_baseline_mae,
        "candidate_beats_baseline": best_validation_mae < validation_baseline_mae,
    }
    if best_validation_mae >= validation_baseline_mae:
        report["status"] = "candidate_not_better_on_validation"
        report["model_trained"] = True
        report["release_status"] = "withheld_validation_baseline_not_beaten"
        report["model_validated"] = False
        report["feature_fields"] = {
            "categorical": list(CATEGORICAL_FEATURES),
            "numeric": numeric_features,
            "excluded_all_missing_in_training": excluded_numeric,
        }
        return TrainingResult(report, None)

    development_frame = pd.concat(
        [frames["train"], frames["validation"]], ignore_index=True,
    )
    development_target = np.concatenate([targets["train"], targets["validation"]])
    final_estimator = Pipeline([
        ("preprocess", clone(preprocessor)),
        ("regressor", GradientBoostingRegressor(
            n_estimators=best_iteration,
            learning_rate=config.learning_rate,
            max_depth=config.max_depth,
            min_samples_leaf=config.min_samples_leaf,
            random_state=config.random_seed,
            loss="huber",
        )),
    ])
    final_estimator.fit(development_frame, development_target)

    # Do not materialize test features or labels until validation has selected
    # an iteration count and the candidate has beaten the training baseline.
    test_entries = observed_by_partition["test"]
    frames["test"] = pd.DataFrame(
        [_feature_row(entry.outcome) for entry in test_entries],
        columns=CATEGORICAL_FEATURES + NUMERIC_FEATURES,
    )
    targets["test"] = np.asarray(
        [entry.outcome.observed_days for entry in test_entries], dtype=float,
    )
    groups["test"] = [
        assignments[entry.outcome.trial_id][1] for entry in test_entries
    ]

    test_predictions = final_estimator.predict(frames["test"])
    test_median = float(np.median(development_target))
    test_baseline = np.full(len(targets["test"]), test_median)
    test_group_ids = groups["test"]
    test_by_food: dict[str, dict[str, float | int]] = {}
    for food_id in sorted(frames["test"]["food_id"].unique()):
        mask = frames["test"]["food_id"].to_numpy() == food_id
        test_by_food[str(food_id)] = {
            "observed_failure_rows": int(mask.sum()),
            "mae_days": float(mean_absolute_error(
                targets["test"][mask], test_predictions[mask],
            )),
        }
    censored_test = censored_by_partition["test"]
    censored_test_predictions = (
        final_estimator.predict(pd.DataFrame(
            [_feature_row(entry.outcome) for entry in censored_test],
            columns=CATEGORICAL_FEATURES + NUMERIC_FEATURES,
        )) if censored_test else np.asarray([], dtype=float)
    )
    lower_bound_violations = sum(
        prediction < entry.outcome.observed_days
        for entry, prediction in zip(censored_test, censored_test_predictions)
    )
    report["test"] = {
        "opened_after_validation_selection": True,
        "observed_failure_rows": len(targets["test"]),
        "right_censored_rows": len(censored_test),
        "candidate_mae_days": float(mean_absolute_error(targets["test"], test_predictions)),
        "candidate_rmse_days": float(root_mean_squared_error(targets["test"], test_predictions)),
        "candidate_macro_group_mae_days": _macro_group_mae(
            targets["test"], test_predictions, test_group_ids,
        ),
        "median_baseline_mae_days": float(mean_absolute_error(targets["test"], test_baseline)),
        "median_baseline_rmse_days": float(root_mean_squared_error(targets["test"], test_baseline)),
        "candidate_beats_baseline": bool(
            mean_absolute_error(targets["test"], test_predictions)
            < mean_absolute_error(targets["test"], test_baseline)
        ),
        "censored_lower_bound_violations": int(lower_bound_violations),
        "censored_lower_bound_rows": len(censored_test),
        "mae_by_food_id": test_by_food,
    }
    report["feature_fields"] = {
        "categorical": list(CATEGORICAL_FEATURES),
        "numeric": numeric_features,
        "excluded_all_missing_in_training": excluded_numeric,
    }
    report["training_food_ids"] = sorted(frames["train"]["food_id"].unique().tolist())
    report["training_structure_ids"] = sorted(frames["train"]["structure_id"].unique().tolist())
    report["status"] = "exploratory_test_evaluated"
    report["model_trained"] = True
    report["model_validated"] = False
    report["release_status"] = "research_only_not_release_validated"
    report["limitations"] = [
        "Only observed failures train the regression model; censoring is not modeled.",
        "Test metrics are exploratory and do not establish performance outside represented foods, structures, endpoints, and conditions.",
        "This baseline does not apply hard package-feasibility filters or issue recommendations.",
        "An independent prospective pilot and predeclared release criteria are still required.",
    ]
    return TrainingResult(report, final_estimator)


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train and audit an exploratory shelf-life baseline from reviewed measured trials",
    )
    parser.add_argument("trials", type=Path)
    parser.add_argument("--sheet", help="XLSX worksheet name")
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True,
                        help="new JSON report path; existing files are preserved")
    parser.add_argument("--model", type=Path, required=True,
                        help="new Joblib model path; created only if validation beats baseline")
    parser.add_argument("--max-iterations", type=int, default=1000)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()

    report_path, model_path = args.report.resolve(), args.model.resolve()
    if report_path == model_path:
        parser.exit(2, "output error: report and model paths must differ\n")
    if report_path.exists() or model_path.exists():
        parser.exit(2, "output error: report/model path already exists; choose new paths\n")

    try:
        audit = audit_trial_outcomes(args.trials, sheet_name=args.sheet)
        reviews = parse_review_register(args.reviews.read_bytes())
        plan = parse_split_plan(args.plan.read_bytes())
        config = TrainingConfig(
            max_iterations=args.max_iterations,
            early_stopping_patience=args.patience,
            random_seed=args.seed,
        )
        result = train_shelf_life(audit, reviews, plan, config)
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"training input error: {exc}\n")

    report = result.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if result.estimator is not None:
        artifact = {
            "model_version": MODEL_VERSION,
            "estimator": result.estimator,
            "feature_fields": report["feature_fields"],
            "target": report["target"],
            "failure_endpoint": report["failure_endpoint"],
            "selected_iterations": report["validation"]["selected_iterations"],
            "trial_source_sha256": report["trial_source_sha256"],
            "split_manifest_sha256": report["split_manifest_sha256"],
            "training_config": report["training_config"],
        }
        buffer = io.BytesIO()
        joblib.dump(artifact, buffer, compress=3)
        model_bytes = buffer.getvalue()
        report["model_artifact_sha256"] = hashlib.sha256(model_bytes).hexdigest()
        with model_path.open("xb") as stream:
            stream.write(model_bytes)
        report["model_artifact_created"] = True
    else:
        report["model_artifact_created"] = False
    _write_json_new(report_path, report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if result.estimator is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
