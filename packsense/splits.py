"""Evidence-gated, source-family-separated trial split manifests.

No model is fitted here. A manifest is an allocation of independently reviewed
measured trials, not evidence that a shelf-life model is accurate or safe.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.ingestion import InputSchemaError
from packsense.trials import TrialAudit, TrialEntry, audit_trial_outcomes


SPLIT_VERSION = "trial-source-group-split-v2"
PARTITIONS = ("train", "validation", "test")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MISSING = frozenset({"", "unknown", "not_reported", "n/a", "na", "tbd"})
_MIN_GROUPS = {"train": 8, "validation": 2, "test": 2}
_MIN_EVENT_GROUPS = {"train": 4, "validation": 2, "test": 2}


def _text(value: object, field: str) -> None:
    if not isinstance(value, str) or value.strip().casefold() in _MISSING:
        raise ValueError(f"{field} must be non-empty reviewed text")


def _hash(value: object, field: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256")


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def trial_digest(entry: TrialEntry) -> str:
    """Bind a review to all parsed trial facts, including the outcome and row."""
    return _canonical_hash({
        "source_row_number": entry.source_row_number,
        "source_locator": entry.source_locator,
        "outcome": asdict(entry.outcome),
    })


@dataclass(frozen=True, slots=True)
class TrialReview:
    trial_id: str
    trial_digest: str
    independence_group_id: str
    evidence_review_id: str
    rights_review_id: str
    endpoint_review_id: str
    structure_review_id: str
    independence_review_id: str

    def __post_init__(self) -> None:
        for field in (
            "trial_id", "independence_group_id", "evidence_review_id",
            "rights_review_id", "endpoint_review_id", "structure_review_id",
            "independence_review_id",
        ):
            _text(getattr(self, field), field)
        _hash(self.trial_digest, "trial_digest")


@dataclass(frozen=True, slots=True)
class ReviewRegister:
    trial_source_sha256: str
    register_sha256: str
    reviews: tuple[TrialReview, ...]

    def __post_init__(self) -> None:
        _hash(self.trial_source_sha256, "trial_source_sha256")
        _hash(self.register_sha256, "register_sha256")


@dataclass(frozen=True, slots=True)
class SplitPlan:
    plan_id: str
    trial_source_sha256: str
    review_register_sha256: str
    plan_sha256: str
    train_groups: tuple[str, ...]
    validation_groups: tuple[str, ...]
    test_groups: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.plan_id, "plan_id")
        for field in ("trial_source_sha256", "review_register_sha256", "plan_sha256"):
            _hash(getattr(self, field), field)
        for partition in PARTITIONS:
            groups = getattr(self, f"{partition}_groups")
            if not isinstance(groups, tuple) or any(
                not isinstance(group, str) or group.strip().casefold() in _MISSING
                for group in groups
            ):
                raise ValueError(f"{partition}_groups must contain non-empty IDs")
            if len(groups) != len(set(groups)):
                raise ValueError(f"{partition}_groups contains duplicate IDs")


@dataclass(frozen=True, slots=True)
class SplitAudit:
    status: str
    reasons: tuple[str, ...]
    diagnostics: dict[str, Any]
    manifest: dict[str, Any] | None

    def report(self) -> dict[str, Any]:
        return {
            "split_version": SPLIT_VERSION,
            "status": self.status,
            "reasons": list(self.reasons),
            "diagnostics": self.diagnostics,
            "manifest_sha256": self.manifest["manifest_sha256"] if self.manifest else None,
            "model_trained": False,
            "model_validated": False,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _payload(raw: bytes, fields: set[str], array_field: str) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"register requires exactly {sorted(fields)}")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    if not isinstance(value[array_field], list):
        raise ValueError(f"{array_field} must be an array")
    return value


def parse_review_register(raw: bytes) -> ReviewRegister:
    data = _payload(raw, {"schema_version", "trial_source_sha256", "reviews"}, "reviews")
    fields = set(TrialReview.__dataclass_fields__)
    reviews = []
    seen = set()
    for index, item in enumerate(data["reviews"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"review {index}: missing or unexpected fields")
        review = TrialReview(**item)
        if review.trial_id in seen:
            raise ValueError(f"review {index}: duplicate trial_id")
        seen.add(review.trial_id)
        reviews.append(review)
    return ReviewRegister(
        data["trial_source_sha256"], hashlib.sha256(raw).hexdigest(), tuple(reviews),
    )


def parse_split_plan(raw: bytes) -> SplitPlan:
    data = _payload(
        raw,
        {"schema_version", "plan_id", "trial_source_sha256", "review_register_sha256",
         "train_groups", "validation_groups", "test_groups"},
        "train_groups",
    )
    for partition in ("validation", "test"):
        if not isinstance(data[f"{partition}_groups"], list):
            raise ValueError(f"{partition}_groups must be an array")
    return SplitPlan(
        plan_id=data["plan_id"],
        trial_source_sha256=data["trial_source_sha256"],
        review_register_sha256=data["review_register_sha256"],
        plan_sha256=hashlib.sha256(raw).hexdigest(),
        train_groups=tuple(data["train_groups"]),
        validation_groups=tuple(data["validation_groups"]),
        test_groups=tuple(data["test_groups"]),
    )


def build_split_manifest(
    audit: TrialAudit, reviews: ReviewRegister, plan: SplitPlan,
) -> SplitAudit:
    """Refuse allocation unless every trial, group, and holdout is auditable."""
    reasons: list[str] = []
    if audit.issues or audit.total_rows != len(audit.entries):
        reasons.append("trial_intake_has_rejected_rows")
    if not audit.entries:
        reasons.append("no_schema_valid_trials")
    if audit.source_sha256 != reviews.trial_source_sha256 or (
        audit.source_sha256 != plan.trial_source_sha256
    ):
        reasons.append("trial_source_hash_mismatch")
    if reviews.register_sha256 != plan.review_register_sha256:
        reasons.append("review_register_hash_mismatch")

    entries = {entry.outcome.trial_id: entry for entry in audit.entries}
    if len(entries) != len(audit.entries):
        reasons.append("duplicate_trial_id")
    by_id = {review.trial_id: review for review in reviews.reviews}
    if len(by_id) != len(reviews.reviews):
        reasons.append("duplicate_review_trial_id")
    missing_reviews = sorted(set(entries) - set(by_id))
    extra_reviews = sorted(set(by_id) - set(entries))
    if missing_reviews:
        reasons.append("missing_trial_reviews:" + ",".join(missing_reviews))
    if extra_reviews:
        reasons.append("review_for_absent_trial:" + ",".join(extra_reviews))

    source_groups: dict[str, set[str]] = defaultdict(set)
    trial_groups: dict[str, set[str]] = defaultdict(set)
    batch_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for trial_id, entry in entries.items():
        review = by_id.get(trial_id)
        if review is None:
            continue
        if review.trial_digest != trial_digest(entry):
            reasons.append(f"trial_review_digest_mismatch:{trial_id}")
        outcome = entry.outcome
        source_groups[outcome.source_id].add(review.independence_group_id)
        trial_groups[outcome.trial_group_id].add(review.independence_group_id)
        batch_groups[(outcome.source_id, outcome.batch_id)].add(review.independence_group_id)
    for source_id, groups in sorted(source_groups.items()):
        if len(groups) != 1:
            reasons.append(f"source_crosses_independence_groups:{source_id}")
    for group_id, groups in sorted(trial_groups.items()):
        if len(groups) != 1:
            reasons.append(f"trial_group_crosses_independence_groups:{group_id}")
    for (source_id, batch_id), groups in sorted(batch_groups.items()):
        if len(groups) != 1:
            reasons.append(f"batch_crosses_independence_groups:{source_id}:{batch_id}")

    assigned = {partition: set(getattr(plan, f"{partition}_groups")) for partition in PARTITIONS}
    all_assigned = set().union(*assigned.values())
    all_reviewed_groups = {review.independence_group_id for review in reviews.reviews}
    for first in PARTITIONS:
        for second in PARTITIONS:
            if first < second and assigned[first] & assigned[second]:
                reasons.append(f"group_crosses_partitions:{first}:{second}")
    if all_reviewed_groups - all_assigned:
        reasons.append("unassigned_independence_groups")
    if all_assigned - all_reviewed_groups:
        reasons.append("unknown_independence_groups")
    group_count = len(all_reviewed_groups)
    for partition in PARTITIONS:
        if len(assigned[partition]) < _MIN_GROUPS[partition]:
            reasons.append(f"too_few_independent_groups:{partition}")
    if group_count:
        shares = {partition: len(assigned[partition]) / group_count for partition in PARTITIONS}
        development_share = shares["train"] + shares["validation"]
        validation_within_development = (
            shares["validation"] / development_share if development_share else 0.0
        )
        if not (0.75 <= development_share <= 0.85
                and 0.15 <= shares["test"] <= 0.25
                and 0.10 <= validation_within_development <= 0.25):
            reasons.append("group_split_outside_predeclared_80_20_holdout_tolerance")
    else:
        shares = {partition: 0.0 for partition in PARTITIONS}
        development_share = 0.0
        validation_within_development = 0.0

    assignments = []
    summaries = {}
    food_events = {}
    for partition in PARTITIONS:
        subset = [
            (entry, by_id[entry.outcome.trial_id]) for entry in audit.entries
            if entry.outcome.trial_id in by_id
            and by_id[entry.outcome.trial_id].independence_group_id in assigned[partition]
        ]
        event_groups = {review.independence_group_id for entry, review in subset
                        if entry.outcome.failure_observed}
        if len(event_groups) < _MIN_EVENT_GROUPS[partition]:
            reasons.append(f"too_few_observed_failure_groups:{partition}")
        food_events[partition] = {entry.outcome.food_id for entry, _ in subset
                                  if entry.outcome.failure_observed}
        summaries[partition] = {
            "independent_groups": len(assigned[partition]),
            "rows": len(subset),
            "observed_failures": sum(entry.outcome.failure_observed for entry, _ in subset),
            "right_censored": sum(not entry.outcome.failure_observed for entry, _ in subset),
            "event_bearing_groups": len(event_groups),
            "group_fraction": shares[partition],
        }
        assignments.extend({
            "trial_id": entry.outcome.trial_id,
            "independence_group_id": review.independence_group_id,
            "partition": partition,
        } for entry, review in subset)
    assigned_row_count = sum(summary["rows"] for summary in summaries.values())
    for partition in PARTITIONS:
        summaries[partition]["row_fraction"] = (
            summaries[partition]["rows"] / assigned_row_count if assigned_row_count else 0.0
        )
    supported_food_ids = sorted(set.intersection(*(food_events[p] for p in PARTITIONS)))
    if not supported_food_ids:
        reasons.append("no_food_with_observed_failures_in_all_partitions")
    diagnostics = {
        "trial_source_sha256": audit.source_sha256,
        "review_register_sha256": reviews.register_sha256,
        "plan_sha256": plan.plan_sha256,
        "total_rows": audit.total_rows,
        "reviewed_rows": len(reviews.reviews),
        "independent_groups": group_count,
        "target_split": "80_percent_development_20_percent_untouched_test",
        "development_group_fraction": development_share,
        "validation_fraction_within_development": validation_within_development,
        "partitions": summaries,
        "supported_food_ids": supported_food_ids,
    }
    if reasons:
        return SplitAudit("not_ready", tuple(dict.fromkeys(reasons)), diagnostics, None)
    manifest = {
        "split_version": SPLIT_VERSION,
        "plan_id": plan.plan_id,
        "trial_source_sha256": audit.source_sha256,
        "review_register_sha256": reviews.register_sha256,
        "plan_sha256": plan.plan_sha256,
        "partitions": {partition: sorted(assigned[partition]) for partition in PARTITIONS},
        "assignments": sorted(assignments, key=lambda item: item["trial_id"]),
        "summaries": summaries,
        "supported_food_ids": supported_food_ids,
        "model_trained": False,
        "model_validated": False,
    }
    manifest["manifest_sha256"] = _canonical_hash(manifest)
    return SplitAudit("allocation_prepared", (), diagnostics, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and freeze reviewed trial group splits")
    parser.add_argument("trials", type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new audit JSON path")
    parser.add_argument("--manifest", type=Path, help="new manifest JSON path when ready")
    args = parser.parse_args()
    try:
        audit = audit_trial_outcomes(args.trials, sheet_name=args.sheet)
        reviews = parse_review_register(args.reviews.read_bytes())
        plan = parse_split_plan(args.plan.read_bytes())
        result = build_split_manifest(audit, reviews, plan)
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    try:
        if args.manifest is not None and args.report.resolve() == args.manifest.resolve():
            raise OSError("report and manifest must be different new paths")
        if args.report.exists():
            raise OSError("report already exists; choose a new path")
        if result.manifest is not None and args.manifest is not None and args.manifest.exists():
            raise OSError("manifest already exists; choose a new path")
        with args.report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result.report(), indent=2) + "\n")
        if result.manifest is not None and args.manifest is not None:
            with args.manifest.open("x", encoding="utf-8") as output:
                output.write(json.dumps(result.manifest, indent=2) + "\n")
    except OSError as exc:
        parser.exit(2, f"report error: {exc}\n")
    print(json.dumps(result.report(), indent=2))
    return 0 if result.manifest is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
