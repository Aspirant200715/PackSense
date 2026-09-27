"""Read supplied food and film-grade references with evidence status intact.

These are reference masters, not recommendation scenarios, finished package
structures, or observed food-package trial outcomes.
"""

import argparse
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Generic, TypeVar

from packsense.contracts import BarrierObservation, EvidenceBasis, FoodReference, MaterialGrade
from packsense.ingestion import InputSchemaError, _read_xlsx, _sha256
from packsense.units import MATERIAL_RATE_UNITS, REFERENCE_RESPIRATION_UNIT


FOOD_NUMBER_COLUMNS = {
    "moisture_content_pct": "moisture_content_pct",
    "oil_fat_content_pct": "oil_fat_content_pct",
    "pH": "pH",
    "pH_ref_min": "pH_ref_min",
    "pH_ref_max": "pH_ref_max",
    "respiration_rate": "respiration_rate",
    "respiration_reference_temperature_c": "respiration_reference_temperature_c",
    "reference_storage_min_c": "ref_storage_min_c",
    "reference_storage_max_c": "ref_storage_max_c",
    "reference_storage_rh_min_pct": "ref_storage_rh_min_pct",
    "reference_storage_rh_max_pct": "ref_storage_rh_max_pct",
    "reference_life_min": "ref_life_min",
    "reference_life_max": "ref_life_max",
}
FOOD_TEXT_COLUMNS = {
    "food_id": "record_id",
    "commodity_type": "commodity_type",
    "food_group": "food_group",
    "pH_basis": "pH_basis",
    "pH_source_food": "pH_source_food",
    "respiration_rate_unit": "respiration_rate_unit",
    "reference_life_unit": "ref_life_unit",
    "reference_storage_basis": "ref_storage_basis",
    "source_citations": "source_citations",
    "composition_method": "composition_method",
}
MATERIAL_COLUMNS = frozenset(
    {
        "material_id", "manufacturer", "grade", "material_family", "film_structure",
        "film_role", "food_application", "thickness_um", "otr_cm3_m2_day",
        "otr_test_temp_c", "otr_test_rh_pct", "otr_test_method",
        "co2tr_cm3_m2_day", "co2_test_temp_c", "co2_test_rh_pct",
        "co2_measurement_method", "co2_value_basis", "co2_source_url",
        "co2_training_label", "wvtr_g_m2_day", "wvtr_test_temp_c",
        "wvtr_test_rh_pct", "wvtr_test_method", "tensile_md_mpa",
        "tensile_td_mpa", "tensile_basis", "seal_status", "seal_min_c",
        "seal_max_c", "seal_test_note", "food_contact_statement", "barrier_value_basis",
        "model_use_status", "source_url", "evidence_note",
    }
)
MISSING_MARKERS = frozenset({"not_reported", "not_applicable", "not_measured"})
T = TypeVar("T")


class MasterRowError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MasterIssue:
    row_number: int
    source_id: str | None
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class FoodMasterEntry:
    source_row_number: int
    reference: FoodReference
    pH_evidence: str  # missing, proxy, reported_reference, or unverified_reference


@dataclass(frozen=True, slots=True)
class MaterialMasterEntry:
    source_row_number: int
    grade: MaterialGrade
    food_application_text: str | None
    barrier_basis_text: str
    co2_basis_text: str
    tensile_basis_text: str | None
    seal_test_note: str | None


@dataclass(frozen=True, slots=True)
class MasterAudit(Generic[T]):
    source_path: str
    source_sha256: str
    sheet_name: str
    total_rows: int
    entries: tuple[T, ...]
    issues: tuple[MasterIssue, ...]

    def report(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "sheet_name": self.sheet_name,
            "total_rows": self.total_rows,
            "accepted_rows": len(self.entries),
            "rejected_rows": self.total_rows - len(self.entries),
            "issues": [
                {"row_number": x.row_number, "source_id": x.source_id,
                 "field": x.field, "message": x.message}
                for x in self.issues
            ],
        }


def _text(raw: dict[str, Any], column: str, *, required: bool = False) -> str | None:
    value = raw.get(column)
    if value is None or isinstance(value, str) and value.strip().lower() in MISSING_MARKERS | {""}:
        if required:
            raise MasterRowError(column, "required source text is missing")
        return None
    if not isinstance(value, str) or not value.strip():
        raise MasterRowError(column, "expected source text")
    return value.strip()


def _number(raw: dict[str, Any], column: str, *, positive: bool = False) -> float | None:
    value = raw.get(column)
    if value is None or isinstance(value, str) and value.strip().lower() in MISSING_MARKERS | {""}:
        return None
    if isinstance(value, bool):
        raise MasterRowError(column, "expected finite numeric source value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MasterRowError(column, "expected finite numeric source value") from exc
    if not isfinite(number) or positive and number <= 0:
        raise MasterRowError(column, "expected positive finite value" if positive else "expected finite value")
    if column in {"moisture_content_pct", "oil_fat_content_pct", "ref_storage_rh_min_pct",
                  "ref_storage_rh_max_pct", "otr_test_rh_pct", "co2_test_rh_pct",
                  "wvtr_test_rh_pct"} and not 0 <= number <= 100:
        raise MasterRowError(column, "percentage must be between 0 and 100")
    if column in {"pH", "pH_ref_min", "pH_ref_max"} and not 0 <= number <= 14:
        raise MasterRowError(column, "pH must be between 0 and 14")
    if column.endswith("_c") and number < -273.15:
        raise MasterRowError(column, "temperature is below absolute zero")
    return number


def _ordered(raw: dict[str, Any], low: str, high: str) -> None:
    minimum, maximum = _number(raw, low), _number(raw, high)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise MasterRowError(high, "maximum is below minimum")


def _read_master(path: str | Path, sheet_name: str | None, columns: set[str]):
    source = Path(path).resolve(strict=True)
    if source.suffix.lower() != ".xlsx":
        raise InputSchemaError("master input must be an .xlsx file")
    header, rows, selected_sheet = _read_xlsx(source, sheet_name)
    if any(not isinstance(name, str) or not name.strip() for name in header):
        raise InputSchemaError("master header names must be non-empty text")
    names = tuple(name.strip() for name in header)
    if len(names) != len(set(names)):
        raise InputSchemaError("duplicate master header names")
    missing = sorted(columns - set(names))
    if missing:
        raise InputSchemaError(f"missing master columns: {', '.join(missing)}")
    return source, names, rows, selected_sheet


def _ph_evidence(reference: FoodReference) -> str:
    if reference.pH is None:
        return "missing"
    basis = (reference.pH_basis or "").lower()
    if "proxy" in basis or "midpoint" in basis:
        return "proxy"
    if "reported reference" in basis:
        return "reported_reference"
    return "unverified_reference"  # never silently classify as product-measured


def load_food_references(path: str | Path, *, sheet_name: str | None = None) -> MasterAudit[FoodMasterEntry]:
    """Import food-property references; scenario blanks are deliberately ignored."""
    columns = set(FOOD_NUMBER_COLUMNS.values()) | set(FOOD_TEXT_COLUMNS.values())
    source, header, rows, selected_sheet = _read_master(path, sheet_name, columns)
    entries: list[FoodMasterEntry] = []
    issues: list[MasterIssue] = []
    seen: set[str] = set()
    total = 0
    for row in rows:
        if all(value is None for value in row.values):
            continue
        total += 1
        raw = dict(zip(header, row.values))
        source_id = raw.get("record_id")
        try:
            if row.formula_columns or len(row.values) != len(header):
                raise MasterRowError("row", "formula cell or column-count mismatch")
            fields = {name: _number(raw, column) for name, column in FOOD_NUMBER_COLUMNS.items()}
            fields.update({
                name: _text(raw, column, required=name in {"food_id", "commodity_type", "source_citations"})
                for name, column in FOOD_TEXT_COLUMNS.items()
            })
            food_id = fields["food_id"]
            if food_id in seen:
                raise MasterRowError("record_id", "duplicate food identifier")
            seen.add(food_id)
            for low, high in (
                ("pH_ref_min", "pH_ref_max"),
                ("ref_storage_min_c", "ref_storage_max_c"),
                ("ref_storage_rh_min_pct", "ref_storage_rh_max_pct"),
                ("ref_life_min", "ref_life_max"),
            ):
                _ordered(raw, low, high)
            respiration = (fields["respiration_rate"], fields["respiration_rate_unit"],
                           fields["respiration_reference_temperature_c"])
            if any(value is not None for value in respiration) and not all(
                value is not None for value in respiration
            ):
                raise MasterRowError("respiration_rate", "respiration fields are incomplete")
            if fields["respiration_rate_unit"] not in {None, REFERENCE_RESPIRATION_UNIT}:
                raise MasterRowError("respiration_rate_unit", "unsupported respiration unit")
            reference = FoodReference(**fields)
            entries.append(FoodMasterEntry(row.number, reference, _ph_evidence(reference)))
        except (MasterRowError, TypeError, ValueError) as exc:
            field = exc.field if isinstance(exc, MasterRowError) else "row"
            issues.append(MasterIssue(row.number, str(source_id) if source_id else None, field, str(exc)))
    return MasterAudit(str(source), _sha256(source), selected_sheet, total, tuple(entries), tuple(issues))


def _barrier(
    raw: dict[str, Any], value_col: str, temperature_col: str, humidity_col: str,
    method_col: str, basis: EvidenceBasis, source_col: str, note: str,
) -> BarrierObservation | None:
    value = _number(raw, value_col, positive=True)
    if value is None:
        return None
    source = _text(raw, source_col, required=True)
    return BarrierObservation(
        value=value, unit=MATERIAL_RATE_UNITS[value_col],
        test_temperature_c=_number(raw, temperature_col),
        test_relative_humidity_pct=_number(raw, humidity_col),
        test_method=_text(raw, method_col), basis=basis, source_url=source,
        source_note=note,
    )


def _co2_basis(text: str) -> EvidenceBasis:
    if text.startswith("supplier measured"):
        return EvidenceBasis.MEASURED
    if text.startswith("estimated"):
        return EvidenceBasis.ESTIMATED
    return EvidenceBasis.UNKNOWN


def _supplier_basis(text: str) -> EvidenceBasis:
    if text.startswith("supplier-calculated"):
        return EvidenceBasis.ESTIMATED
    if text.startswith("supplier"):
        return EvidenceBasis.SUPPLIER_REPORTED
    return EvidenceBasis.UNKNOWN


def load_material_grades(path: str | Path, *, sheet_name: str | None = None) -> MasterAudit[MaterialMasterEntry]:
    """Import grade observations; do not certify finished-package use."""
    source, header, rows, selected_sheet = _read_master(path, sheet_name, set(MATERIAL_COLUMNS))
    entries: list[MaterialMasterEntry] = []
    issues: list[MasterIssue] = []
    seen: set[str] = set()
    total = 0
    for row in rows:
        if all(value is None for value in row.values):
            continue
        total += 1
        raw = dict(zip(header, row.values))
        source_id = raw.get("material_id")
        try:
            if row.formula_columns or len(row.values) != len(header):
                raise MasterRowError("row", "formula cell or column-count mismatch")
            material_id = _text(raw, "material_id", required=True)
            if material_id in seen:
                raise MasterRowError("material_id", "duplicate material identifier")
            seen.add(material_id)
            barrier_text = _text(raw, "barrier_value_basis", required=True)
            co2_text = _text(raw, "co2_value_basis", required=True)
            barrier_basis = _supplier_basis(barrier_text.lower())
            co2_basis = _co2_basis(co2_text.lower())
            label = raw.get("co2_training_label")
            if label not in (0, 1) or isinstance(label, bool):
                raise MasterRowError("co2_training_label", "expected 0 or 1")
            for low, high in (("seal_min_c", "seal_max_c"),):
                _ordered(raw, low, high)
            grade = MaterialGrade(
                material_id=material_id,
                manufacturer=_text(raw, "manufacturer", required=True),
                grade=_text(raw, "grade"),
                material_family=_text(raw, "material_family", required=True),
                film_structure=_text(raw, "film_structure", required=True),
                film_role=_text(raw, "film_role", required=True),
                thickness_um=_number(raw, "thickness_um", positive=True),
                otr=_barrier(raw, "otr_cm3_m2_day", "otr_test_temp_c", "otr_test_rh_pct",
                             "otr_test_method", barrier_basis, "source_url", barrier_text),
                co2tr=_barrier(raw, "co2tr_cm3_m2_day", "co2_test_temp_c", "co2_test_rh_pct",
                               "co2_measurement_method", co2_basis, "co2_source_url", co2_text),
                wvtr=_barrier(raw, "wvtr_g_m2_day", "wvtr_test_temp_c", "wvtr_test_rh_pct",
                              "wvtr_test_method", barrier_basis, "source_url", barrier_text),
                co2_training_label=bool(label),
                seal_status=_text(raw, "seal_status", required=True),
                food_contact_statement=_text(raw, "food_contact_statement", required=True),
                model_use_status=_text(raw, "model_use_status", required=True),
                source_url=_text(raw, "source_url", required=True),
                seal_min_c=_number(raw, "seal_min_c"),
                seal_max_c=_number(raw, "seal_max_c"),
                tensile_md_mpa=_number(raw, "tensile_md_mpa", positive=True),
                tensile_td_mpa=_number(raw, "tensile_td_mpa", positive=True),
                evidence_note=_text(raw, "evidence_note"),
            )
            entries.append(MaterialMasterEntry(
                row.number, grade, _text(raw, "food_application"), barrier_text,
                co2_text, _text(raw, "tensile_basis"), _text(raw, "seal_test_note"),
            ))
        except (MasterRowError, TypeError, ValueError) as exc:
            field = exc.field if isinstance(exc, MasterRowError) else "row"
            issues.append(MasterIssue(row.number, str(source_id) if source_id else None, field, str(exc)))
    return MasterAudit(str(source), _sha256(source), selected_sheet, total, tuple(entries), tuple(issues))


def _barrier_evidence_report(
    entries: tuple[MaterialMasterEntry, ...], property_name: str,
) -> dict[str, Any]:
    """Summarize provenance and condition coverage without promoting references.

    Strict measured candidates require an explicit measured basis and the
    original test temperature, humidity, and method. Supplier-reported values
    remain source references, not silently relabelled measurements.
    """
    if property_name not in {"otr", "co2tr", "wvtr"}:
        raise ValueError("unsupported barrier property")
    observations = [
        (entry, getattr(entry.grade, property_name)) for entry in entries
    ]
    observations = [(entry, value) for entry, value in observations if value is not None]
    basis_counts = {basis.value: 0 for basis in EvidenceBasis}
    complete_context = []
    measured_complete = []
    for entry, observation in observations:
        basis_counts[observation.basis.value] += 1
        method = (observation.test_method or "").strip().casefold()
        has_context = (
            observation.test_temperature_c is not None
            and observation.test_relative_humidity_pct is not None
            and method not in MISSING_MARKERS | {"", "unknown", "n/a", "na"}
        )
        if has_context:
            complete_context.append(entry)
        if (observation.basis is EvidenceBasis.MEASURED and has_context
                and observation.source_url.strip()):
            measured_complete.append(entry)

    result: dict[str, Any] = {
        "rows_with_values": len(observations),
        "evidence_basis_counts": basis_counts,
        "rows_with_complete_test_context": len(complete_context),
        "strict_measured_training_candidates": len(measured_complete),
    }
    if property_name == "co2tr":
        declared = [entry for entry in entries if entry.grade.co2_training_label]
        result["declared_training_label_rows"] = len(declared)
        result["declared_labels_with_measured_complete_context"] = sum(
            entry in measured_complete for entry in declared
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit sourced PackSense reference workbooks")
    parser.add_argument("kind", choices=("food", "material"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--report", type=Path, help="new JSON report path")
    args = parser.parse_args()
    try:
        audit = (load_food_references if args.kind == "food" else load_material_grades)(
            args.input, sheet_name=args.sheet
        )
    except (InputSchemaError, OSError, ValueError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    report = audit.report()
    if args.kind == "food":
        report["coverage"] = {
            "moisture": sum(x.reference.moisture_content_pct is not None for x in audit.entries),
            "fat": sum(x.reference.oil_fat_content_pct is not None for x in audit.entries),
            "pH": sum(x.reference.pH is not None for x in audit.entries),
            "pH_proxy": sum(x.pH_evidence == "proxy" for x in audit.entries),
            "pH_reported_reference": sum(x.pH_evidence == "reported_reference" for x in audit.entries),
            "respiration": sum(x.reference.respiration_rate is not None for x in audit.entries),
        }
    else:
        report["coverage"] = {
            "otr": sum(x.grade.otr is not None for x in audit.entries),
            "otr_with_test_conditions": sum(
                x.grade.otr is not None and x.grade.otr.test_temperature_c is not None
                and x.grade.otr.test_relative_humidity_pct is not None for x in audit.entries
            ),
            "wvtr": sum(x.grade.wvtr is not None for x in audit.entries),
            "wvtr_with_test_conditions": sum(
                x.grade.wvtr is not None and x.grade.wvtr.test_temperature_c is not None
                and x.grade.wvtr.test_relative_humidity_pct is not None for x in audit.entries
            ),
            "co2tr": sum(x.grade.co2tr is not None for x in audit.entries),
            "co2_estimated": sum(x.grade.co2tr is not None and x.grade.co2tr.basis is EvidenceBasis.ESTIMATED for x in audit.entries),
            "co2_measured_missing_test_conditions": sum(
                x.grade.co2tr is not None and x.grade.co2tr.basis is EvidenceBasis.MEASURED
                and (x.grade.co2tr.test_temperature_c is None
                     or x.grade.co2tr.test_relative_humidity_pct is None)
                for x in audit.entries
            ),
            "co2_training_label": sum(x.grade.co2_training_label for x in audit.entries),
        }
        report["barrier_evidence"] = {
            name: _barrier_evidence_report(audit.entries, name)
            for name in ("otr", "wvtr", "co2tr")
        }
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
