"""One-row-per-scenario CSV view of the preliminary batch JSON report."""

import csv
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

EXPECTED_BATCH_VERSION = "basic-recommendation-batch-v1"
SUMMARY_VERSION = "preliminary-batch-summary-v1"
SUMMARY_COLUMNS = (
    "summary_version",
    "source_row_number",
    "record_id",
    "food_reference_id",
    "food_reference_row_number",
    "status",
    "storage_temperature_c",
    "transport_temperature_c",
    "transport_max_temperature_c",
    "desired_shelf_life_days",
    "candidate_count",
    "eligible_structure_ids",
    "preliminary_preferred_structure_id",
    "preliminary_preferred_pack_format",
    "preliminary_preferred_total_thickness_um",
    "input_issue_codes",
    "requirement_gap_codes",
    "screening_reason_codes",
    "warnings",
    "package_feasible",
    "shelf_life_predicted",
    "scenario_sha256",
    "food_master_sha256",
    "material_master_sha256",
)


def _joined(values: list[str]) -> str:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("summary codes must be string arrays")
    return ";".join(values)


def _spreadsheet_safe(value: Any) -> Any:
    """Keep external text from becoming an Excel formula when CSV is opened."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _temperature_profile(card: Mapping[str, Any]) -> dict[str, float]:
    exposures = card.get("exposures")
    if not isinstance(exposures, list):
        raise ValueError("requirement card has no exposure list")
    temperatures = {}
    for item in exposures:
        if not isinstance(item, dict):
            raise ValueError("invalid exposure entry")
        phase, value = item.get("phase"), item.get("temperature_c")
        if phase in temperatures or isinstance(value, bool) or not isinstance(
            value, (int, float)
        ) or not isfinite(value):
            raise ValueError("invalid or duplicate exposure temperature")
        temperatures[phase] = value
    if set(temperatures) != {"storage", "transport", "transport_max_excursion"}:
        raise ValueError("requirement card has an incomplete exposure profile")
    return temperatures


def summarize_batch(report: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Project a batch report without inventing any package or life claim."""
    if report.get("batch_version") != EXPECTED_BATCH_VERSION:
        raise ValueError("unsupported batch report version")
    if report.get("package_feasible") is not False or report.get("shelf_life_predicted") is not False:
        raise ValueError("preliminary batch must not claim package feasibility or shelf life")
    batch_rows = report.get("rows")
    if not isinstance(batch_rows, list):
        raise ValueError("batch report has no row list")

    rows = []
    for row in batch_rows:
        if not isinstance(row, dict) or row.get("status") not in (
            "exception", "not_ready", "preliminary_shortlist"
        ):
            raise ValueError("batch row has an unsupported status")
        status = row["status"]
        card, recommendation = row.get("requirement_card"), row.get("recommendation")
        if status == "exception":
            if card is not None or recommendation is not None:
                raise ValueError("exception row cannot contain a recommendation")
            issues = row.get("issues")
            if not isinstance(issues, list):
                raise ValueError("exception row has no issue list")
            issue_codes = [f"{issue['field']}:{issue['code']}" for issue in issues]
            food_id = ""
            temperatures: dict[str, float] = {}
            target_days = ""
            candidates = []
            eligible_ids: list[str] = []
            preferred = None
            gaps: list[str] = []
            reasons: list[str] = []
            warnings: list[str] = []
        else:
            if not isinstance(card, dict) or not isinstance(recommendation, dict):
                raise ValueError("screened row needs a card and recommendation")
            if recommendation.get("status") != status or recommendation.get(
                "package_feasible"
            ) is not False or recommendation.get("shelf_life_predicted") is not False:
                raise ValueError("screened row has inconsistent recommendation claims")
            issue_codes = []
            food_id = recommendation["food_reference_id"]
            temperatures = _temperature_profile(card)
            target_days = card["target_shelf_life_days"]
            candidates = recommendation["candidates"]
            if not isinstance(candidates, list):
                raise ValueError("recommendation candidates must be an array")
            eligible_ids = [
                item["structure_id"] for item in candidates
                if item["status"] == "eligible_for_shortlist"
            ]
            if status == "preliminary_shortlist" and not eligible_ids:
                raise ValueError("shortlist has no eligible structure")
            preferred_id = recommendation["preliminary_preferred_structure_id"]
            preferred = next(
                (item for item in candidates if item["structure_id"] == preferred_id), None
            ) if preferred_id is not None else None
            if preferred_id is not None and (
                status != "preliminary_shortlist" or preferred is None
                or preferred["status"] != "eligible_for_shortlist"
            ):
                raise ValueError("preliminary preference is not an eligible candidate")
            gaps = card["gaps"]
            reasons = recommendation["reason_codes"]
            warnings = recommendation["warnings"]

        total_thickness = ""
        if preferred is not None:
            layers = preferred["layers"]
            if not isinstance(layers, list) or not layers:
                raise ValueError("preferred structure has no layer specification")
            thicknesses = [layer["thickness_um"] for layer in layers]
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not isfinite(value) or value <= 0 for value in thicknesses):
                raise ValueError("preferred structure has invalid layer thickness")
            total_thickness = sum(thicknesses)
        rows.append({
            "summary_version": SUMMARY_VERSION,
            "source_row_number": row["row_number"],
            "record_id": row["record_id"] or "",
            "food_reference_id": food_id,
            "food_reference_row_number": row["food_reference_row"] or "",
            "status": status,
            "storage_temperature_c": temperatures.get("storage", ""),
            "transport_temperature_c": temperatures.get("transport", ""),
            "transport_max_temperature_c": temperatures.get("transport_max_excursion", ""),
            "desired_shelf_life_days": target_days,
            "candidate_count": len(candidates),
            "eligible_structure_ids": _joined(eligible_ids),
            "preliminary_preferred_structure_id": preferred["structure_id"] if preferred else "",
            "preliminary_preferred_pack_format": preferred["pack_format"] if preferred else "",
            "preliminary_preferred_total_thickness_um": total_thickness,
            "input_issue_codes": _joined(issue_codes),
            "requirement_gap_codes": _joined(gaps),
            "screening_reason_codes": _joined(reasons),
            "warnings": _joined(warnings),
            "package_feasible": "false",
            "shelf_life_predicted": "false",
            "scenario_sha256": report["scenario_sha256"],
            "food_master_sha256": report["food_master_sha256"],
            "material_master_sha256": report["material_master_sha256"],
        })
    if len(rows) != report.get("total_rows"):
        raise ValueError("batch row count does not match report summary")
    return tuple(rows)


def write_summary_csv(report: Mapping[str, Any], path: Path) -> int:
    """Write a new summary CSV; the detailed JSON remains authoritative."""
    rows = summarize_batch(report)
    with path.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows({key: _spreadsheet_safe(value) for key, value in row.items()}
                         for row in rows)
    return len(rows)
