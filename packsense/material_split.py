"""Freeze group-separated material-suitability labels before model fitting.

This prepares an allocation only. It does not authenticate external sources,
fit an ML model, or claim that the labelled package is scientifically safe.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from packsense.enrichment import enrich_scenarios
from packsense.ingestion import InputSchemaError, audit_scenarios
from packsense.masters import load_food_references, load_material_grades
from packsense.material_suitability import (
    SuitabilityAudit, audit_suitability_labels, parse_suitability_register,
)
from packsense.structure_review import (
    audit_structure_reviews, parse_structure_review_register,
)
from packsense.structures import audit_structure_catalogue


SPLIT_VERSION = "material-source-food-group-split-v1"
PARTITIONS = ("train", "validation", "test")
MIN_GROUPS = {"train": 8, "validation": 2, "test": 2}
MIN_CLASS_GROUPS = {"train": 2, "validation": 1, "test": 1}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MISSING = frozenset({"", "unknown", "n/a", "not_reported", "tbd"})
_PLAN_FIELDS = frozenset({
    "schema_version", "plan_id", "suitability_register_sha256",
    "train_groups", "validation_groups", "test_groups",
})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputSchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InputSchemaError(f"non-finite JSON number: {value}")


def _group_ids(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or item.casefold() in _MISSING
        or item != item.strip()
        for item in value
    ):
        raise InputSchemaError(f"{field} must be an array of non-empty group IDs")
    if len(value) != len(set(value)):
        raise InputSchemaError(f"{field} contains duplicate group IDs")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class MaterialSplitPlan:
    plan_id: str
    suitability_register_sha256: str
    plan_sha256: str
    train_groups: tuple[str, ...]
    validation_groups: tuple[str, ...]
    test_groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaterialSplitAudit:
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
            "manifest": self.manifest,
            "source_authenticity_verified_by_code": False,
            "model_trained": False,
        }


def parse_material_split_plan(raw: bytes) -> MaterialSplitPlan:
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputSchemaError("material split plan is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or set(data) != _PLAN_FIELDS:
        raise InputSchemaError("material split plan has missing or unexpected keys")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputSchemaError("unsupported material split schema_version")
    plan_id = data["plan_id"]
    if (not isinstance(plan_id, str) or plan_id.casefold() in _MISSING
            or plan_id != plan_id.strip()):
        raise InputSchemaError("plan_id must be non-empty reviewed text")
    register_hash = data["suitability_register_sha256"]
    if not isinstance(register_hash, str) or not _HASH.fullmatch(register_hash):
        raise InputSchemaError("suitability_register_sha256 must be a lowercase SHA-256")
    groups = {name: _group_ids(data[f"{name}_groups"], f"{name}_groups")
              for name in PARTITIONS}
    return MaterialSplitPlan(
        plan_id, register_hash, hashlib.sha256(raw).hexdigest(),
        groups["train"], groups["validation"], groups["test"],
    )


def _commodity_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def build_material_split(
    audit: SuitabilityAudit, plan: MaterialSplitPlan,
    *, food_commodity_by_id: Mapping[str, str],
) -> MaterialSplitAudit:
    """Require an approximately 80/20, source-and-food-disjoint allocation."""
    reasons: list[str] = []
    if audit.issues or len(audit.accepted) != len(audit.register.labels):
        reasons.append("suitability_intake_has_rejected_labels")
    if not audit.accepted:
        reasons.append("no_accepted_suitability_labels")
    if plan.suitability_register_sha256 != audit.register.source_sha256:
        reasons.append("suitability_register_hash_mismatch")

    assigned = {part: set(getattr(plan, f"{part}_groups")) for part in PARTITIONS}
    all_assigned = set().union(*assigned.values())
    actual_groups = {label.source_family_id for label in audit.accepted}
    for index, first in enumerate(PARTITIONS):
        for second in PARTITIONS[index + 1:]:
            if assigned[first] & assigned[second]:
                reasons.append(f"group_crosses_partitions:{first}:{second}")
    if actual_groups - all_assigned:
        reasons.append("unassigned_source_families")
    if all_assigned - actual_groups:
        reasons.append("unknown_source_families")

    allocation = {
        part: tuple(label for label in audit.accepted
                    if label.source_family_id in assigned[part])
        for part in PARTITIONS
    }
    source_groups: dict[str, set[str]] = defaultdict(set)
    food_partitions: dict[str, set[str]] = defaultdict(set)
    commodity_partitions: dict[str, set[str]] = defaultdict(set)
    for part in PARTITIONS:
        for label in allocation[part]:
            source_groups[label.source_id].add(label.source_family_id)
            food_partitions[label.food_reference_id].add(part)
            commodity = food_commodity_by_id.get(label.food_reference_id)
            if not isinstance(commodity, str) or not commodity.strip():
                reasons.append("food_commodity_name_missing")
            else:
                commodity_partitions[_commodity_key(commodity)].add(part)
    if any(len(groups) > 1 for groups in source_groups.values()):
        reasons.append("source_id_crosses_source_families")
    if any(len(parts) > 1 for parts in food_partitions.values()):
        reasons.append("food_reference_crosses_partitions")
    if any(len(parts) > 1 for parts in commodity_partitions.values()):
        reasons.append("commodity_name_crosses_partitions")

    diagnostics: dict[str, Any] = {
        "total_labels": len(audit.accepted),
        "total_source_families": len(actual_groups),
        "partitions": {},
    }
    for part in PARTITIONS:
        rows = allocation[part]
        class_groups = {
            decision: len({label.source_family_id for label in rows
                           if label.decision == decision})
            for decision in ("suitable", "unsuitable")
        }
        diagnostics["partitions"][part] = {
            "labels": len(rows),
            "source_families": len(assigned[part]),
            "decision_counts": dict(sorted(Counter(x.decision for x in rows).items())),
            "decision_group_counts": class_groups,
            "food_references": len({x.food_reference_id for x in rows}),
            "structures": len({x.structure_id for x in rows}),
        }
        if len(assigned[part]) < MIN_GROUPS[part]:
            reasons.append(f"too_few_source_families:{part}")
        for decision, count in class_groups.items():
            if count < MIN_CLASS_GROUPS[part]:
                reasons.append(f"too_few_{decision}_groups:{part}")

    total = len(audit.accepted)
    development = len(allocation["train"]) + len(allocation["validation"])
    test_fraction = len(allocation["test"]) / total if total else None
    validation_fraction = len(allocation["validation"]) / development if development else None
    diagnostics["test_row_fraction"] = test_fraction
    diagnostics["validation_fraction_of_development"] = validation_fraction
    if test_fraction is not None and not 0.15 <= test_fraction <= 0.25:
        reasons.append("test_fraction_outside_80_20_tolerance")
    if validation_fraction is not None and not 0.15 <= validation_fraction <= 0.25:
        reasons.append("validation_fraction_outside_development_tolerance")

    if reasons:
        return MaterialSplitAudit("not_ready", tuple(sorted(set(reasons))),
                                  diagnostics, None)

    manifest: dict[str, Any] = {
        "split_version": SPLIT_VERSION,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "suitability_register_sha256": audit.register.source_sha256,
        "scenario_sha256": audit.register.scenario_sha256,
        "food_master_sha256": audit.register.food_master_sha256,
        "material_master_sha256": audit.register.material_master_sha256,
        "structure_catalogue_sha256": audit.register.structure_catalogue_sha256,
        "structure_review_sha256": audit.register.structure_review_sha256,
        "partitions": {
            part: {
                "source_family_ids": sorted(assigned[part]),
                "label_ids": sorted(label.label_id for label in allocation[part]),
            }
            for part in PARTITIONS
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return MaterialSplitAudit("allocation_prepared", (), diagnostics, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze material suitability group split")
    parser.add_argument("labels", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--food-master", type=Path, required=True)
    parser.add_argument("--material-master", type=Path, required=True)
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--structure-reviews", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new JSON report path")
    args = parser.parse_args()
    try:
        scenarios = audit_scenarios(args.scenarios)
        foods = load_food_references(args.food_master)
        materials = load_material_grades(args.material_master)
        if foods.issues or materials.issues:
            raise InputSchemaError("food/material master contains rejected rows")
        enriched = enrich_scenarios(scenarios, foods)
        catalogue = audit_structure_catalogue(
            args.structures,
            grades={entry.grade.material_id: entry.grade for entry in materials.entries},
            material_master_sha256=materials.source_sha256,
        )
        review = parse_structure_review_register(args.structure_reviews.read_bytes())
        reviewed = audit_structure_reviews(catalogue, review)
        register = parse_suitability_register(args.labels.read_bytes())
        label_audit = audit_suitability_labels(
            register, enriched, reviewed, material_master_sha256=materials.source_sha256,
        )
        plan = parse_material_split_plan(args.plan.read_bytes())
        split = build_material_split(
            label_audit, plan,
            food_commodity_by_id={entry.reference.food_id: entry.reference.commodity_type
                                  for entry in foods.entries},
        )
        with args.report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(split.report(), indent=2) + "\n")
    except (InputSchemaError, OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input/report error: {exc}\n")
    print(json.dumps(split.report(), indent=2))
    return 0 if split.status == "allocation_prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
