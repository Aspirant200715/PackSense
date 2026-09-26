"""Experimental Stop-2 food-property estimates from source-reported rows.

This model does not learn package choice or shelf life. It never turns a proxy
or a predicted food property into a measured trial outcome.
"""

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

from packsense.masters import FoodMasterEntry, load_food_references


ESTIMABLE_FIELDS = ("moisture_content_pct", "oil_fat_content_pct")
SEED = 41
INTERVAL_COVERAGE = 0.90


@dataclass(frozen=True, slots=True)
class PropertyEstimate:
    food_id: str
    commodity_type: str
    field: str
    value: float
    interval_low: float
    interval_high: float
    basis: str
    training_label_basis: str
    source_sha256: str
    model_version: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    target: str
    source_sha256: str
    training_label_basis: str
    split_seed: int
    grouping_rule: str
    training_rows: int
    calibration_rows: int
    test_rows: int
    training_groups: int
    calibration_groups: int
    test_groups: int
    model_mae: float
    model_rmse: float
    baseline_mae: float
    baseline_rmse: float
    model_macro_group_mae: float
    baseline_macro_group_mae: float
    interval_radius: float
    test_interval_coverage: float
    model_beats_baseline: bool
    model_version: str = "food-text-ridge-v1"

    def report(self) -> dict:
        return asdict(self)


def _family(entry: FoodMasterEntry) -> str:
    """Hold related name prefixes together to reduce near-duplicate leakage."""
    name = entry.reference.commodity_type.split(",", 1)[0].lower()
    tokens = re.findall(r"[a-z0-9]+", name)
    prefix = " ".join(tokens) if tokens else name.strip()
    return f"{entry.reference.food_group or ''}::{prefix}"


def _has_analytical_derivation(entry: FoodMasterEntry, target: str) -> bool:
    """Use only the source's A (analytical) derivation code for this nutrient."""
    label = "moisture" if target == "moisture_content_pct" else "fat"
    method = entry.reference.composition_method or ""
    return f"{label}=A" in {part.strip() for part in method.split(";")}


def _features(entries: list[FoodMasterEntry]) -> list[str]:
    return [
        f"{entry.reference.food_group or ''} | {entry.reference.commodity_type}"
        for entry in entries
    ]


def _pipeline() -> Pipeline:
    return Pipeline(
        [
            ("text", TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), min_df=2,
                max_features=40000, sublinear_tf=True,
            )),
            ("regression", Ridge(alpha=1.0, solver="lsqr")),
        ]
    )


def _group_split(groups: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Disjoint family groups: development, calibration, untouched test."""
    indices = np.arange(len(groups))
    train_cal, test = next(GroupShuffleSplit(
        n_splits=1, test_size=0.15, random_state=SEED,
    ).split(indices, groups=groups))
    local_train, local_cal = next(GroupShuffleSplit(
        n_splits=1, test_size=0.15 / 0.85, random_state=SEED + 1,
    ).split(train_cal, groups=[groups[i] for i in train_cal]))
    train, calibration = train_cal[local_train], train_cal[local_cal]
    if not (set(groups[i] for i in train).isdisjoint(groups[i] for i in calibration)
            and set(groups[i] for i in train).isdisjoint(groups[i] for i in test)
            and set(groups[i] for i in calibration).isdisjoint(groups[i] for i in test)):
        raise AssertionError("food family crossed a split boundary")
    return train, calibration, test


def _baseline(train_entries: list[FoodMasterEntry], values: np.ndarray, others: list[FoodMasterEntry]) -> np.ndarray:
    by_group: dict[str, list[float]] = defaultdict(list)
    for entry, value in zip(train_entries, values):
        by_group[entry.reference.food_group or ""].append(float(value))
    medians = {group: float(np.median(samples)) for group, samples in by_group.items()}
    fallback = float(np.median(values))
    return np.array([medians.get(entry.reference.food_group or "", fallback) for entry in others])


def _conformal_radius(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Finite-sample absolute-residual quantile on the held-out calibration set."""
    residuals = np.abs(y_true - y_pred)
    quantile = min(1.0, ceil((len(residuals) + 1) * INTERVAL_COVERAGE) / len(residuals))
    return float(np.quantile(residuals, quantile, method="higher"))


def _bounded_interval(prediction: float, radius: float) -> tuple[float, float] | None:
    """Reject out-of-range centers and intervals with no information at all."""
    if not 0 <= prediction <= 100:
        return None
    low, high = max(0.0, prediction - radius), min(100.0, prediction + radius)
    if low == 0 and high == 100:
        return None
    return low, high


def _macro_group_mae(y_true: np.ndarray, y_pred: np.ndarray, groups: list[str]) -> float:
    errors: dict[str, list[float]] = defaultdict(list)
    for actual, predicted, group in zip(y_true, y_pred, groups):
        errors[group].append(abs(float(actual) - float(predicted)))
    return float(np.mean([np.mean(group_errors) for group_errors in errors.values()]))


def evaluate_property(
    entries: tuple[FoodMasterEntry, ...], source_sha256: str, target: str,
) -> tuple[Evaluation, Pipeline]:
    """Fit a fixed candidate on training groups and evaluate one held-out test.

    pH is intentionally unavailable here: the supplied pH values are proxies
    or broad references, not exact-product measurement labels.
    """
    if target not in ESTIMABLE_FIELDS:
        raise ValueError(f"unsupported training target: {target}")
    observed = [
        entry for entry in entries
        if getattr(entry.reference, target) is not None
        and _has_analytical_derivation(entry, target)
    ]
    if len(observed) < 100 or len(set(map(_family, observed))) < 30:
        raise ValueError("too few independent source rows/families to evaluate")
    groups = [_family(entry) for entry in observed]
    train_idx, cal_idx, test_idx = _group_split(groups)
    if min(len(train_idx), len(cal_idx), len(test_idx)) < 30:
        raise ValueError("a split has too few rows for this evaluation")

    y = np.array([getattr(entry.reference, target) for entry in observed], dtype=float)
    train_entries = [observed[i] for i in train_idx]
    cal_entries = [observed[i] for i in cal_idx]
    test_entries = [observed[i] for i in test_idx]
    model = _pipeline()
    model.fit(_features(train_entries), y[train_idx])
    cal_prediction = model.predict(_features(cal_entries))
    test_prediction = model.predict(_features(test_entries))
    radius = _conformal_radius(y[cal_idx], cal_prediction)
    baseline_prediction = _baseline(train_entries, y[train_idx], test_entries)
    test_groups = [groups[i] for i in test_idx]
    model_mae = float(mean_absolute_error(y[test_idx], test_prediction))
    baseline_mae = float(mean_absolute_error(y[test_idx], baseline_prediction))
    evaluation = Evaluation(
        target=target, source_sha256=source_sha256,
        training_label_basis="USDA_nutrient_derivation_A_analytical_only",
        split_seed=SEED,
        grouping_rule="food_group_and_first_comma_delimited_name_segment",
        training_rows=len(train_idx), calibration_rows=len(cal_idx), test_rows=len(test_idx),
        training_groups=len(set(groups[i] for i in train_idx)),
        calibration_groups=len(set(groups[i] for i in cal_idx)),
        test_groups=len(set(test_groups)),
        model_mae=model_mae,
        model_rmse=float(root_mean_squared_error(y[test_idx], test_prediction)),
        baseline_mae=baseline_mae,
        baseline_rmse=float(root_mean_squared_error(y[test_idx], baseline_prediction)),
        model_macro_group_mae=_macro_group_mae(y[test_idx], test_prediction, test_groups),
        baseline_macro_group_mae=_macro_group_mae(y[test_idx], baseline_prediction, test_groups),
        interval_radius=radius,
        test_interval_coverage=float(np.mean(
            (y[test_idx] >= np.maximum(0, test_prediction - radius))
            & (y[test_idx] <= np.minimum(100, test_prediction + radius))
        )),
        model_beats_baseline=model_mae < baseline_mae,
    )
    return evaluation, model


def estimate_missing(
    entries: tuple[FoodMasterEntry, ...], source_sha256: str, target: str,
    evaluation: Evaluation, model: Pipeline,
) -> tuple[PropertyEstimate, ...]:
    """Return labelled screening estimates; do not alter the source workbook."""
    if target != evaluation.target or source_sha256 != evaluation.source_sha256:
        raise ValueError("evaluation and source/target do not match")
    if not evaluation.model_beats_baseline:
        return ()
    missing = [entry for entry in entries if getattr(entry.reference, target) is None]
    if not missing:
        return ()
    predictions = model.predict(_features(missing))
    radius = evaluation.interval_radius
    estimates = []
    for entry, prediction in zip(missing, predictions):
        interval = _bounded_interval(float(prediction), radius)
        if interval is None:
            continue
        estimates.append(PropertyEstimate(
            food_id=entry.reference.food_id,
            commodity_type=entry.reference.commodity_type,
            field=target,
            value=float(prediction),
            interval_low=interval[0],
            interval_high=interval[1],
            basis="experimental_model_estimate_not_measurement",
            training_label_basis=evaluation.training_label_basis,
            source_sha256=source_sha256,
            model_version=evaluation.model_version,
        ))
    return tuple(estimates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate food-property estimates; no package choice")
    parser.add_argument("food_workbook", type=Path)
    parser.add_argument("--target", choices=ESTIMABLE_FIELDS, required=True)
    parser.add_argument("--estimates-report", type=Path, help="new JSON file for labelled missing-row estimates")
    args = parser.parse_args()
    audit = load_food_references(args.food_workbook)
    if audit.issues:
        parser.exit(2, f"source import has {len(audit.issues)} row issues\n")
    try:
        evaluation, model = evaluate_property(audit.entries, audit.source_sha256, args.target)
    except ValueError as exc:
        parser.exit(2, f"evaluation unavailable: {exc}\n")
    report = evaluation.report()
    estimates = estimate_missing(audit.entries, audit.source_sha256, args.target, evaluation, model)
    report["missing_rows"] = sum(
        getattr(entry.reference, args.target) is None for entry in audit.entries
    )
    report["estimates_available"] = len(estimates)
    report["release_status"] = "experimental_screening_only"
    if args.estimates_report:
        payload = {"evaluation": report, "estimates": [asdict(estimate) for estimate in estimates]}
        try:
            with args.estimates_report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(payload, indent=2) + "\n")
        except FileExistsError:
            parser.exit(2, "report error: output already exists; choose a new path\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
