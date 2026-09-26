"""Fail-closed review gate for complete package-structure drafts.

This module checks the shape and exact identity of human review declarations.
It cannot authenticate source documents, prove food-contact compliance, or
establish scenario-level package feasibility from review IDs alone.
"""

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.contracts import PackageStructure
from packsense.ingestion import InputSchemaError
from packsense.masters import load_material_grades
from packsense.structures import (
    BROAD_FOOD_SCOPE, UNSPECIFIED, StructureCatalogueAudit, StructureDraft,
    audit_structure_catalogue,
)


REVIEW_VERSION = "structure-review-v1"
CHECK_KINDS = frozenset({
    "construction", "food_contact", "seal_closure", "mechanical",
    "service_temperature",
})
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MISSING = UNSPECIFIED | {"not_measured"}
_CHECK_FIELDS = frozenset({
    "kind", "source_id", "source_locator", "source_sha256", "review_id",
    "rights_review_id", "decision",
})
_REVIEW_FIELDS = frozenset({
    "structure_id", "draft_digest", "review_id", "reviewer_id",
    "reviewed_food_scope", "service_temperature_min_c",
    "service_temperature_max_c", "checks",
})
_REGISTER_FIELDS = frozenset({
    "schema_version", "catalogue_sha256", "material_master_sha256",
    "catalogue_version", "reviews",
})


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or value.strip().casefold() in _MISSING:
        raise ValueError(f"{field} must be non-empty reviewed text")
    if value != value.strip():
        raise ValueError(f"{field} must not have surrounding whitespace")
    return value.strip()


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _temperature(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite Celsius temperature")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be a finite Celsius temperature") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite Celsius temperature")
    if number < -273.15:
        raise ValueError(f"{field} is below absolute zero")
    return number


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def draft_digest(draft: StructureDraft) -> str:
    """Bind a decision to every parsed draft field, including layer order."""
    return _canonical_hash(asdict(draft))


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    kind: str
    source_id: str
    source_locator: str
    source_sha256: str
    review_id: str
    rights_review_id: str
    decision: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in CHECK_KINDS:
            raise ValueError(f"unknown structure check kind: {self.kind}")
        for field in ("source_id", "source_locator", "review_id", "rights_review_id"):
            _text(getattr(self, field), field)
        _hash(self.source_sha256, "source_sha256")
        if self.decision not in ("pass", "fail"):
            raise ValueError("check decision must be pass or fail")


@dataclass(frozen=True, slots=True)
class StructureReview:
    structure_id: str
    draft_digest: str
    review_id: str
    reviewer_id: str
    reviewed_food_scope: tuple[str, ...]
    service_temperature_min_c: float
    service_temperature_max_c: float
    checks: tuple[EvidenceCheck, ...]

    def __post_init__(self) -> None:
        for field in ("structure_id", "review_id", "reviewer_id"):
            _text(getattr(self, field), field)
        _hash(self.draft_digest, "draft_digest")
        if not isinstance(self.reviewed_food_scope, tuple) or not self.reviewed_food_scope:
            raise ValueError("reviewed_food_scope must be a non-empty array")
        scope = tuple(_text(item, "reviewed_food_scope") for item in self.reviewed_food_scope)
        if len(scope) != len({item.casefold() for item in scope}) or any(
            item.casefold() in BROAD_FOOD_SCOPE for item in scope
        ):
            raise ValueError("reviewed_food_scope cannot duplicate or blanket foods")
        low = _temperature(self.service_temperature_min_c, "service_temperature_min_c")
        high = _temperature(self.service_temperature_max_c, "service_temperature_max_c")
        if low > high:
            raise ValueError("reviewed service temperature range is reversed")
        if not isinstance(self.checks, tuple) or any(
            not isinstance(item, EvidenceCheck) for item in self.checks
        ):
            raise ValueError("checks must be an array of evidence checks")
        kinds = [item.kind for item in self.checks]
        if len(kinds) != len(set(kinds)) or set(kinds) != CHECK_KINDS:
            raise ValueError("checks must contain each required kind exactly once")


@dataclass(frozen=True, slots=True)
class StructureReviewRegister:
    catalogue_sha256: str
    material_master_sha256: str
    catalogue_version: str
    register_sha256: str
    reviews: tuple[StructureReview, ...]

    def __post_init__(self) -> None:
        for field in ("catalogue_sha256", "material_master_sha256", "register_sha256"):
            _hash(getattr(self, field), field)
        _text(self.catalogue_version, "catalogue_version")


@dataclass(frozen=True, slots=True)
class ReviewAttestedStructure:
    """Reviewed construction; still not an applicable or feasible package."""

    structure: PackageStructure
    catalogue_sha256: str
    material_master_sha256: str
    review_register_sha256: str
    review_id: str
    evidence_check_ids: tuple[str, ...]
    estimated_barrier_grade_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StructureReviewIssue:
    structure_id: str | None
    code: str


@dataclass(frozen=True, slots=True)
class StructureReviewAudit:
    status: str
    catalogue_sha256: str
    review_register_sha256: str
    reviewed: tuple[ReviewAttestedStructure, ...]
    issues: tuple[StructureReviewIssue, ...]

    def report(self) -> dict[str, Any]:
        return {
            "review_version": REVIEW_VERSION,
            "status": self.status,
            "catalogue_sha256": self.catalogue_sha256,
            "review_register_sha256": self.review_register_sha256,
            "review_attested_structures": len(self.reviewed),
            "structure_ids": [item.structure.structure_id for item in self.reviewed],
            "issues": [asdict(issue) for issue in self.issues],
            "evidence_authenticity_verified_by_code": False,
            "package_feasible": False,
            "shelf_life_predicted": False,
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


def _fields(value: object, required: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"{label} requires exactly {sorted(required)}")
    return value


def parse_structure_review_register(raw: bytes) -> StructureReviewRegister:
    """Parse a strict declaration; a valid JSON record is not source proof."""
    data = _fields(
        json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant),
        _REGISTER_FIELDS, "structure review register",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported structure review schema_version")
    if not isinstance(data["reviews"], list):
        raise ValueError("reviews must be an array")
    reviews = []
    seen = set()
    for index, item in enumerate(data["reviews"], start=1):
        row = _fields(item, _REVIEW_FIELDS, f"review {index}")
        if not isinstance(row["reviewed_food_scope"], list) or not isinstance(
            row["checks"], list
        ):
            raise ValueError(f"review {index}: scope and checks must be arrays")
        checks = tuple(EvidenceCheck(**_fields(check, _CHECK_FIELDS,
                                               f"review {index} check"))
                       for check in row["checks"])
        review = StructureReview(**{
            **row, "reviewed_food_scope": tuple(row["reviewed_food_scope"]),
            "checks": checks,
        })
        if review.structure_id in seen:
            raise ValueError(f"review {index}: duplicate structure_id")
        seen.add(review.structure_id)
        reviews.append(review)
    return StructureReviewRegister(
        catalogue_sha256=data["catalogue_sha256"],
        material_master_sha256=data["material_master_sha256"],
        catalogue_version=data["catalogue_version"],
        register_sha256=hashlib.sha256(raw).hexdigest(),
        reviews=tuple(reviews),
    )


def audit_structure_reviews(
    catalogue: StructureCatalogueAudit, register: StructureReviewRegister,
) -> StructureReviewAudit:
    """Attest only exact, complete, passing reviews; fail the catalogue closed."""
    issues: list[StructureReviewIssue] = []

    def issue(structure_id: str | None, code: str) -> None:
        issues.append(StructureReviewIssue(structure_id, code))

    if catalogue.issues or catalogue.total_rows != len(catalogue.entries):
        issue(None, "catalogue_has_rejected_drafts")
    if not catalogue.entries:
        issue(None, "no_structure_drafts")
    if (register.catalogue_sha256 != catalogue.source_sha256
            or register.material_master_sha256 != catalogue.material_master_sha256
            or register.catalogue_version != catalogue.catalogue_version):
        issue(None, "catalogue_or_material_version_mismatch")
    drafts = {draft.structure_id: draft for draft in catalogue.entries}
    reviews = {review.structure_id: review for review in register.reviews}
    if len(drafts) != len(catalogue.entries) or len(reviews) != len(register.reviews):
        issue(None, "duplicate_structure_identity")
    for structure_id in sorted(set(drafts) - set(reviews)):
        issue(structure_id, "missing_structure_review")
    for structure_id in sorted(set(reviews) - set(drafts)):
        issue(structure_id, "review_for_absent_structure")

    attested = []
    for structure_id, draft in sorted(drafts.items()):
        review = reviews.get(structure_id)
        if review is None:
            continue
        if review.draft_digest != draft_digest(draft):
            issue(structure_id, "draft_digest_mismatch")
        construction = next(check for check in review.checks
                            if check.kind == "construction")
        contact = next(check for check in review.checks
                       if check.kind == "food_contact")
        if (construction.source_id != draft.structure_source_id
                or construction.source_locator != draft.structure_source_locator):
            issue(structure_id, "construction_source_mismatch")
        if (contact.source_id != draft.food_contact_evidence_id
                or contact.source_locator != draft.food_contact_evidence_locator):
            issue(structure_id, "food_contact_source_mismatch")
        if not set(review.reviewed_food_scope).issubset(draft.compatible_food_scope):
            issue(structure_id, "review_food_scope_exceeds_draft")
        if (review.service_temperature_min_c < draft.service_temperature_min_c
                or review.service_temperature_max_c > draft.service_temperature_max_c):
            issue(structure_id, "review_service_range_exceeds_draft")
        if any(check.decision != "pass" for check in review.checks):
            issue(structure_id, "required_evidence_check_failed")
        if any(item.structure_id == structure_id for item in issues):
            continue
        structure = PackageStructure(
            structure_id=draft.structure_id, pack_format=draft.pack_format,
            layers=draft.layers, sealant_grade_id=draft.sealant_grade_id,
            structure_source_id=draft.structure_source_id,
            food_contact_evidence_id=draft.food_contact_evidence_id,
            compatible_food_scope=review.reviewed_food_scope,
            service_temperature_min_c=review.service_temperature_min_c,
            service_temperature_max_c=review.service_temperature_max_c,
        )
        attested.append(ReviewAttestedStructure(
            structure=structure, catalogue_sha256=catalogue.source_sha256,
            material_master_sha256=catalogue.material_master_sha256,
            review_register_sha256=register.register_sha256,
            review_id=review.review_id,
            evidence_check_ids=tuple(check.review_id for check in review.checks),
            estimated_barrier_grade_ids=draft.estimated_barrier_grade_ids,
        ))
    if issues:
        return StructureReviewAudit("not_approved", catalogue.source_sha256,
                                    register.register_sha256, (), tuple(issues))
    return StructureReviewAudit("review_attested", catalogue.source_sha256,
                                register.register_sha256, tuple(attested), ())


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit external package-structure reviews")
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="new audit JSON path")
    args = parser.parse_args()
    try:
        materials = load_material_grades(args.materials, sheet_name=args.sheet)
        if materials.issues:
            raise InputSchemaError("material master has rejected rows")
        catalogue = audit_structure_catalogue(
            args.catalogue,
            grades={entry.grade.material_id: entry.grade for entry in materials.entries},
            material_master_sha256=materials.source_sha256,
        )
        register = parse_structure_review_register(args.reviews.read_bytes())
        result = audit_structure_reviews(catalogue, register)
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    report = result.report()
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except OSError as exc:
            parser.exit(2, f"report error: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0 if result.status == "review_attested" else 1


if __name__ == "__main__":
    raise SystemExit(main())
