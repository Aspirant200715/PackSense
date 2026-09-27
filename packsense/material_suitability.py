"""Audit sourced food-package suitability labels for a future ranking model.

This module validates evidence identity and joins, not scientific truth. A
schema-valid label is not proof that a package is safe or a model is trainable.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packsense.enrichment import EnrichmentAudit, enrich_scenarios
from packsense.ingestion import InputSchemaError, audit_scenarios
from packsense.masters import load_food_references, load_material_grades
from packsense.structure_review import (
    StructureReviewAudit, attestation_integrity_gaps, audit_structure_reviews,
    parse_structure_review_register,
)
from packsense.structures import audit_structure_catalogue


REGISTER_FIELDS = frozenset({
    "schema_version", "scenario_sha256", "food_master_sha256",
    "material_master_sha256", "structure_catalogue_sha256",
    "structure_review_sha256", "labels",
})
LABEL_FIELDS = frozenset({
    "label_id", "scenario_record_id", "food_reference_id", "structure_id",
    "decision", "evidence_basis", "source_family_id", "source_id",
    "source_locator", "source_finding", "decision_criterion", "review_id",
    "reviewer_id", "rights_review_id", "rationale",
})
DECISIONS = frozenset({"suitable", "unsuitable"})
EVIDENCE_BASES = frozenset({"measured_comparison", "independent_expert_assessment"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_UNSPECIFIED = frozenset({"", "unknown", "n/a", "not_reported", "tbd"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputSchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InputSchemaError(f"non-finite JSON number: {value}")


def _fields(value: Any, expected: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        missing = sorted(expected - value.keys()) if isinstance(value, dict) else sorted(expected)
        extra = sorted(value.keys() - expected) if isinstance(value, dict) else []
        raise InputSchemaError(f"{name} keys mismatch; missing={missing}, extra={extra}")
    return value


def _text(value: Any, name: str) -> str:
    if (not isinstance(value, str) or value != value.strip()
            or value.casefold() in _UNSPECIFIED):
        raise InputSchemaError(f"{name} must be non-empty, reviewed text")
    return value


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise InputSchemaError(f"{name} must be a lowercase SHA-256")
    return value


def _scope(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


@dataclass(frozen=True, slots=True)
class SuitabilityLabel:
    label_id: str
    scenario_record_id: str
    food_reference_id: str
    structure_id: str
    decision: str
    evidence_basis: str
    source_family_id: str
    source_id: str
    source_locator: str
    source_finding: str
    decision_criterion: str
    review_id: str
    reviewer_id: str
    rights_review_id: str
    rationale: str


@dataclass(frozen=True, slots=True)
class SuitabilityRegister:
    source_sha256: str
    scenario_sha256: str
    food_master_sha256: str
    material_master_sha256: str
    structure_catalogue_sha256: str
    structure_review_sha256: str
    labels: tuple[SuitabilityLabel, ...]


@dataclass(frozen=True, slots=True)
class SuitabilityIssue:
    label_id: str
    code: str


@dataclass(frozen=True, slots=True)
class SuitabilityAudit:
    register: SuitabilityRegister
    accepted: tuple[SuitabilityLabel, ...]
    issues: tuple[SuitabilityIssue, ...]

    def report(self) -> dict[str, Any]:
        decisions = Counter(label.decision for label in self.accepted)
        bases = Counter(label.evidence_basis for label in self.accepted)
        return {
            "schema_version": 1,
            "register_sha256": self.register.source_sha256,
            "scenario_sha256": self.register.scenario_sha256,
            "food_master_sha256": self.register.food_master_sha256,
            "material_master_sha256": self.register.material_master_sha256,
            "structure_catalogue_sha256": self.register.structure_catalogue_sha256,
            "structure_review_sha256": self.register.structure_review_sha256,
            "total_labels": len(self.register.labels),
            "accepted_labels": len(self.accepted),
            "rejected_labels": len(self.issues),
            "decision_counts": dict(sorted(decisions.items())),
            "evidence_basis_counts": dict(sorted(bases.items())),
            "independent_source_families": len({x.source_family_id for x in self.accepted}),
            "distinct_food_references": len({x.food_reference_id for x in self.accepted}),
            "distinct_structures": len({x.structure_id for x in self.accepted}),
            "issues": [
                {"label_id": issue.label_id, "code": issue.code}
                for issue in self.issues
            ],
            "training_ready": False,
            "training_readiness_reason": (
                "no_accepted_labels" if not self.accepted
                else "source_independence_and_split_review_not_performed"
            ),
            "model_trained": False,
            "scientific_suitability_verified_by_code": False,
        }


def parse_suitability_register(raw: bytes) -> SuitabilityRegister:
    """Read a strict, version-bound register; never derive absent pair labels."""
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputSchemaError("suitability register is not valid UTF-8 JSON") from exc
    root = _fields(data, REGISTER_FIELDS, "register")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise InputSchemaError("unsupported suitability schema_version")
    hashes = {key: _hash(root[key], key) for key in REGISTER_FIELDS if key.endswith("sha256")}
    if not isinstance(root["labels"], list):
        raise InputSchemaError("labels must be an array")
    labels: list[SuitabilityLabel] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for index, raw_label in enumerate(root["labels"]):
        row = _fields(raw_label, LABEL_FIELDS, f"labels[{index}]")
        values = {key: _text(row[key], f"labels[{index}].{key}") for key in LABEL_FIELDS}
        if values["decision"] not in DECISIONS:
            raise InputSchemaError(f"labels[{index}].decision is unsupported")
        if values["evidence_basis"] not in EVIDENCE_BASES:
            raise InputSchemaError(f"labels[{index}].evidence_basis is unsupported")
        label_id = values["label_id"]
        pair = (values["scenario_record_id"], values["structure_id"])
        if label_id in seen_ids or pair in seen_pairs:
            raise InputSchemaError("duplicate label_id or scenario/structure pair")
        seen_ids.add(label_id)
        seen_pairs.add(pair)
        labels.append(SuitabilityLabel(**values))
    return SuitabilityRegister(
        hashlib.sha256(raw).hexdigest(), labels=tuple(labels), **hashes,
    )


def audit_suitability_labels(
    register: SuitabilityRegister,
    enriched: EnrichmentAudit,
    structure_review: StructureReviewAudit,
    *,
    material_master_sha256: str,
) -> SuitabilityAudit:
    """Bind labels to exact enriched scenarios and review-attested structures."""
    expected = (
        (register.scenario_sha256, enriched.scenario_sha256),
        (register.food_master_sha256, enriched.food_master_sha256),
        (register.material_master_sha256, material_master_sha256),
        (register.structure_catalogue_sha256, structure_review.catalogue_sha256),
        (register.structure_review_sha256, structure_review.review_register_sha256),
    )
    if any(given != current for given, current in expected):
        raise InputSchemaError("suitability register references a different source version")
    if (structure_review.status != "review_attested" or structure_review.issues
            or attestation_integrity_gaps(structure_review)):
        raise InputSchemaError("complete-structure review is not internally consistent")
    scenarios: dict[str, Any] = {}
    for row in enriched.rows:
        if row.record_id is not None:
            if row.record_id in scenarios:
                raise InputSchemaError("duplicate scenario record_id in enrichment")
            scenarios[row.record_id] = row.enriched
    structures = {item.structure.structure_id: item for item in structure_review.reviewed}
    if len(structures) != len(structure_review.reviewed):
        raise InputSchemaError("duplicate reviewed structure_id")
    accepted: list[SuitabilityLabel] = []
    issues: list[SuitabilityIssue] = []
    for label in register.labels:
        scenario = scenarios.get(label.scenario_record_id)
        reviewed = structures.get(label.structure_id)
        code = None
        if scenario is None:
            code = "scenario_not_enriched"
        elif scenario.food_reference.food_id != label.food_reference_id:
            code = "food_reference_mismatch"
        elif reviewed is None or reviewed.material_master_sha256 != material_master_sha256:
            code = "reviewed_structure_missing_or_stale"
        elif _scope(scenario.scenario.commodity_type) not in {
            _scope(scope) for scope in reviewed.structure.compatible_food_scope
        }:
            code = "reviewed_food_scope_mismatch"
        elif any(
            exposure.temperature_c < reviewed.structure.service_temperature_min_c
            or exposure.temperature_c > reviewed.structure.service_temperature_max_c
            for exposure in scenario.exposures
        ):
            code = "service_temperature_out_of_scope"
        if code is None:
            accepted.append(label)
        else:
            issues.append(SuitabilityIssue(label.label_id, code))
    return SuitabilityAudit(register, tuple(accepted), tuple(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit sourced package-suitability labels")
    parser.add_argument("labels", type=Path)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--food-master", type=Path, required=True)
    parser.add_argument("--material-master", type=Path, required=True)
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--structure-reviews", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new JSON output path")
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
        audit = audit_suitability_labels(register, enriched, reviewed,
                                         material_master_sha256=materials.source_sha256)
        with args.report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(audit.report(), indent=2) + "\n")
    except (InputSchemaError, OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input/report error: {exc}\n")
    print(json.dumps(audit.report(), indent=2))
    return 0 if not audit.issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
