"""Read complete package-structure *drafts* without approving them for use.

A film-grade row is not a manufacturable package. This intake cross-checks
exact grade identities and gauges, but independent source/contact review and
finished-structure performance validation remain mandatory before promotion.
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from math import isclose, isfinite
from pathlib import Path
from typing import Any, Mapping

from packsense.contracts import EvidenceBasis, MaterialGrade, StructureLayer
from packsense.ingestion import InputSchemaError, _sha256
from packsense.masters import load_material_grades


CATALOGUE_FIELDS = frozenset({"catalogue_version", "structures"})
STRUCTURE_FIELDS = frozenset({
    "structure_id", "pack_format", "layers", "sealant_grade_id", "converter",
    "forming_method", "closure_type", "structure_source_id",
    "structure_source_locator", "food_contact_evidence_id",
    "food_contact_evidence_locator", "compatible_food_scope",
    "service_temperature_min_c", "service_temperature_max_c",
})
LAYER_FIELDS = frozenset({"grade_id", "thickness_um", "role", "is_food_contact"})
UNSPECIFIED = frozenset({"", "unknown", "not_reported", "n/a", "na", "tbd"})
BROAD_FOOD_SCOPE = frozenset({"*", "all", "all_foods", "any"})


@dataclass(frozen=True, slots=True)
class StructureDraft:
    """Source-declared stack, not an approved PackageStructure contract."""

    structure_id: str
    pack_format: str
    layers: tuple[StructureLayer, ...]
    sealant_grade_id: str
    converter: str
    forming_method: str
    closure_type: str
    structure_source_id: str
    structure_source_locator: str
    food_contact_evidence_id: str
    food_contact_evidence_locator: str
    compatible_food_scope: tuple[str, ...]
    service_temperature_min_c: float
    service_temperature_max_c: float
    estimated_barrier_grade_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StructureIssue:
    source_index: int
    structure_id: str | None
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class StructureCatalogueAudit:
    source_path: str
    source_sha256: str
    catalogue_version: str
    material_master_sha256: str
    total_rows: int
    entries: tuple[StructureDraft, ...]
    issues: tuple[StructureIssue, ...]

    def report(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "catalogue_version": self.catalogue_version,
            "material_master_sha256": self.material_master_sha256,
            "total_rows": self.total_rows,
            "schema_valid_drafts": len(self.entries),
            "rejected_rows": self.total_rows - len(self.entries),
            "drafts_with_estimated_barrier_grades": sum(
                bool(entry.estimated_barrier_grade_ids) for entry in self.entries
            ),
            "approved_package_structures": 0,
            "approval_reason": (
                "Importer checks structure syntax and exact grade/gauge joins only; "
                "source authenticity, food-contact scope, manufacturability, "
                "service limits, finished-package barrier and seal performance "
                "require independent evidence review."
            ),
            "issues": [
                {"source_index": issue.source_index, "structure_id": issue.structure_id,
                 "field": issue.field, "message": issue.message}
                for issue in self.issues
            ],
        }


class _StructureError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputSchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InputSchemaError(f"non-finite JSON number: {value}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in UNSPECIFIED:
        raise _StructureError(field, "required source text is missing")
    return value.strip()


def _temperature(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _StructureError(field, "expected finite temperature in Celsius")
    try:
        number = float(value)
    except OverflowError as exc:
        raise _StructureError(field, "invalid temperature in Celsius") from exc
    if not isfinite(number) or number < -273.15:
        raise _StructureError(field, "invalid temperature in Celsius")
    return number


def _thickness(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _StructureError(field, "expected positive numeric micrometres")
    try:
        number = float(value)
    except OverflowError as exc:
        raise _StructureError(field, "expected positive numeric micrometres") from exc
    if not isfinite(number) or number <= 0:
        raise _StructureError(field, "expected positive numeric micrometres")
    return number


def _fields(raw: Any, required: frozenset[str], field: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _StructureError(field, "expected a JSON object")
    missing = sorted(required - raw.keys())
    unexpected = sorted(raw.keys() - required)
    if missing or unexpected:
        raise _StructureError(field, f"missing keys: {missing}; unexpected keys: {unexpected}")
    return raw


def _layer(raw: Any, index: int, grades: Mapping[str, MaterialGrade]) -> StructureLayer:
    field = f"layers[{index}]"
    data = _fields(raw, LAYER_FIELDS, field)
    grade_id = _text(data["grade_id"], f"{field}.grade_id")
    if grade_id not in grades:
        raise _StructureError(f"{field}.grade_id", "grade is absent from the supplied material master")
    thickness = _thickness(data["thickness_um"], f"{field}.thickness_um")
    reference_thickness = grades[grade_id].thickness_um
    if reference_thickness is None or not isfinite(reference_thickness) or not isclose(
        thickness, reference_thickness, rel_tol=0, abs_tol=1e-9
    ):
        raise _StructureError(f"{field}.thickness_um", "layer gauge differs from the exact grade observation")
    role = _text(data["role"], f"{field}.role")
    if not isinstance(data["is_food_contact"], bool):
        raise _StructureError(f"{field}.is_food_contact", "expected JSON true or false")
    return StructureLayer(grade_id, thickness, role, data["is_food_contact"])


def _parse_structure(raw: Any, grades: Mapping[str, MaterialGrade]) -> StructureDraft:
    data = _fields(raw, STRUCTURE_FIELDS, "structure")
    if not isinstance(data["layers"], list) or not data["layers"]:
        raise _StructureError("layers", "at least one ordered layer is required")
    layers = tuple(_layer(layer, index, grades) for index, layer in enumerate(data["layers"]))
    if not layers[-1].is_food_contact or any(layer.is_food_contact for layer in layers[:-1]):
        raise _StructureError("layers", "exactly the innermost layer must be marked food-contact")
    if layers[-1].role.casefold() != "sealant":
        raise _StructureError("layers", "the innermost layer must have the sealant role")
    sealant_id = _text(data["sealant_grade_id"], "sealant_grade_id")
    if sealant_id != layers[-1].grade_id:
        raise _StructureError("sealant_grade_id", "sealant must be the innermost grade")
    scope = data["compatible_food_scope"]
    if not isinstance(scope, list) or not scope:
        raise _StructureError("compatible_food_scope", "explicit non-empty food scope is required")
    food_scope = tuple(_text(value, "compatible_food_scope") for value in scope)
    if len({value.casefold() for value in food_scope}) != len(food_scope) or any(
        value.casefold() in BROAD_FOOD_SCOPE for value in food_scope
    ):
        raise _StructureError("compatible_food_scope", "duplicate or blanket food scope is not accepted")
    service_min = _temperature(data["service_temperature_min_c"], "service_temperature_min_c")
    service_max = _temperature(data["service_temperature_max_c"], "service_temperature_max_c")
    if service_min > service_max:
        raise _StructureError("service_temperature_max_c", "maximum service temperature is below minimum")
    estimated = tuple(dict.fromkeys(
        layer.grade_id for layer in layers
        if any(observation is not None and observation.basis is EvidenceBasis.ESTIMATED
               for observation in (grades[layer.grade_id].otr,
                                   grades[layer.grade_id].co2tr,
                                   grades[layer.grade_id].wvtr))
    ))
    return StructureDraft(
        structure_id=_text(data["structure_id"], "structure_id"),
        pack_format=_text(data["pack_format"], "pack_format"),
        layers=layers,
        sealant_grade_id=sealant_id,
        converter=_text(data["converter"], "converter"),
        forming_method=_text(data["forming_method"], "forming_method"),
        closure_type=_text(data["closure_type"], "closure_type"),
        structure_source_id=_text(data["structure_source_id"], "structure_source_id"),
        structure_source_locator=_text(data["structure_source_locator"], "structure_source_locator"),
        food_contact_evidence_id=_text(data["food_contact_evidence_id"], "food_contact_evidence_id"),
        food_contact_evidence_locator=_text(data["food_contact_evidence_locator"],
                                            "food_contact_evidence_locator"),
        compatible_food_scope=food_scope,
        service_temperature_min_c=service_min,
        service_temperature_max_c=service_max,
        estimated_barrier_grade_ids=estimated,
    )


def audit_structure_catalogue(path: str | Path, *, grades: Mapping[str, MaterialGrade],
                              material_master_sha256: str) -> StructureCatalogueAudit:
    """Audit a JSON catalogue; accepted drafts are never recommendation-ready."""
    source = Path(path).resolve(strict=True)
    if source.suffix.lower() != ".json":
        raise InputSchemaError("structure catalogue must be a .json file")
    if not grades or len(material_master_sha256) != 64:
        raise InputSchemaError("a populated, versioned material master is required")
    with source.open("r", encoding="utf-8") as stream:
        raw = json.load(stream, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    catalogue = _fields(raw, CATALOGUE_FIELDS, "catalogue")
    version = _text(catalogue["catalogue_version"], "catalogue_version")
    rows = catalogue["structures"]
    if not isinstance(rows, list):
        raise InputSchemaError("structures must be a JSON array")
    ids = Counter(
        row.get("structure_id").strip() for row in rows
        if isinstance(row, dict) and isinstance(row.get("structure_id"), str)
        and row["structure_id"].strip()
    )
    entries: list[StructureDraft] = []
    issues: list[StructureIssue] = []
    for index, row in enumerate(rows):
        label = row.get("structure_id") if isinstance(row, dict) else None
        if not isinstance(label, str) or not label.strip():
            label = None
        try:
            draft = _parse_structure(row, grades)
            if ids[draft.structure_id] > 1:
                raise _StructureError("structure_id", "duplicate structure identifier")
            entries.append(draft)
        except _StructureError as exc:
            issues.append(StructureIssue(index, label, exc.field, str(exc)))
    return StructureCatalogueAudit(str(source), _sha256(source), version,
                                   material_master_sha256, len(rows), tuple(entries),
                                   tuple(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a sourced package-structure catalogue")
    parser.add_argument("input", type=Path)
    parser.add_argument("--materials", type=Path, required=True, help="material grade master XLSX")
    parser.add_argument("--sheet", help="material master worksheet, if multi-sheet")
    parser.add_argument("--report", type=Path, help="new full JSON audit report path")
    args = parser.parse_args()
    try:
        materials = load_material_grades(args.materials, sheet_name=args.sheet)
        if materials.issues:
            raise InputSchemaError("material master has rejected rows; resolve them before joining")
        audit = audit_structure_catalogue(
            args.input,
            grades={entry.grade.material_id: entry.grade for entry in materials.entries},
            material_master_sha256=materials.source_sha256,
        )
    except (InputSchemaError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    report = audit.report()
    if args.report:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except FileExistsError:
            parser.exit(2, "report error: output already exists; choose a new path\n")
    print(json.dumps(report, indent=2))
    return 0 if not report["rejected_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
