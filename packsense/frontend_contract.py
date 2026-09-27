"""Project an audited batch into a conservative frontend decision contract.

This is a view of the existing evidence-gated engineering report. It is not
an inference endpoint and never upgrades a preliminary shortlist to a
validated package or a trained material prediction.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from packsense.recommendation_output import EXPECTED_BATCH_VERSION


CONTRACT_VERSION = "frontend-decision-v1"
ROW_STATUSES = frozenset({"exception", "not_ready", "preliminary_shortlist"})
CANDIDATE_STATUSES = frozenset({"excluded", "unresolved", "eligible_for_shortlist"})
TRACE_FIELDS = (
    "scenario_sha256", "food_master_sha256", "material_master_sha256",
    "route_register_sha256", "assessment_register_sha256",
    "structure_catalogue_sha256", "structure_review_register_sha256",
    "transfer_register_sha256", "public_candidate_catalogue_sha256",
)
SCENARIO_FIELDS = (
    "commodity_type", "moisture_content_pct", "oil_fat_content_pct", "pH",
    "net_pack_quantity", "net_pack_quantity_unit", "storage_type",
    "transport_mode", "transport_handling_severity", "respiration_rate",
    "respiration_rate_unit", "respiration_reference_temperature_c",
)


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _candidate_view(raw: Any) -> dict[str, Any]:
    candidate = _object(raw, "candidate")
    if candidate.get("status") not in CANDIDATE_STATUSES:
        raise ValueError("candidate has an unsupported status")
    if not isinstance(candidate.get("structure_id"), str) or not candidate["structure_id"]:
        raise ValueError("candidate has no structure ID")
    return {
        "structure_id": candidate["structure_id"],
        "pack_format": candidate["pack_format"],
        "status": candidate["status"],
        "reason_codes": _list(candidate["reason_codes"], "candidate reason codes"),
        "layers": _list(candidate["layers"], "candidate layers"),
        "protection_rank": candidate["protection_rank"],
        "service_temperature_min_c": candidate["service_temperature_min_c"],
        "service_temperature_max_c": candidate["service_temperature_max_c"],
    }


def _scenario_view(raw: Any) -> dict[str, Any] | None:
    """Keep validated scenario facts only; legacy batch reports may omit them."""
    if raw is None:
        return None
    scenario = _object(raw, "scenario summary")
    if (not isinstance(scenario.get("commodity_type"), str)
            or not scenario["commodity_type"].strip()):
        raise ValueError("scenario summary has no commodity")
    return {name: scenario.get(name) for name in SCENARIO_FIELDS}


def project_frontend_decisions(report: Mapping[str, Any]) -> dict[str, Any]:
    """Expose actionable states while withholding unvalidated predictions."""
    batch = _object(report, "batch report")
    if batch.get("batch_version") != EXPECTED_BATCH_VERSION:
        raise ValueError("unsupported batch report version")
    if batch.get("package_feasible") is not False or batch.get("shelf_life_predicted") is not False:
        raise ValueError("preliminary batch cannot claim package feasibility or shelf life")
    rows = _list(batch.get("rows"), "batch rows")
    if not rows:
        raise ValueError("batch report has no rows")

    projected = []
    for raw in rows:
        row = _object(raw, "batch row")
        status = row.get("status")
        if status not in ROW_STATUSES:
            raise ValueError("batch row has an unsupported status")
        if type(row.get("row_number")) is not int or row["row_number"] < 1:
            raise ValueError("batch row has no valid source row number")
        issues = _list(row.get("issues"), "input issues")
        card, recommendation = row.get("requirement_card"), row.get("recommendation")
        scenario = _scenario_view(row.get("scenario"))
        if status == "exception":
            if card is not None or recommendation is not None or scenario is not None:
                raise ValueError("input exception cannot carry a recommendation")
            if not issues:
                raise ValueError("input exception must explain its issue")
            requirement_gaps: list[str] = []
            screening_reasons: list[str] = []
            warnings: list[str] = []
            exposure: list[dict[str, Any]] = []
            candidates: list[dict[str, Any]] = []
            preferred = None
            food_reference_id = None
            target_days = None
        else:
            if issues:
                raise ValueError("screened row cannot carry input issues")
            card = _object(card, "requirement card")
            recommendation = _object(recommendation, "recommendation")
            if (recommendation.get("status") != status
                    or recommendation.get("package_feasible") is not False
                    or recommendation.get("shelf_life_predicted") is not False):
                raise ValueError("row recommendation contradicts preliminary batch status")
            if recommendation.get("record_id") != row.get("record_id"):
                raise ValueError("row recommendation record ID mismatch")
            requirement_gaps = _list(card.get("gaps"), "requirement gaps")
            screening_reasons = _list(recommendation.get("reason_codes"), "screening reasons")
            warnings = _list(recommendation.get("warnings"), "screening warnings")
            exposure = _list(card.get("exposures"), "temperature exposures")
            candidates = [_candidate_view(item) for item in _list(
                recommendation.get("candidates"), "screened candidates",
            )]
            eligible_ids = {item["structure_id"] for item in candidates
                            if item["status"] == "eligible_for_shortlist"}
            if len({item["structure_id"] for item in candidates}) != len(candidates):
                raise ValueError("duplicate screened structure ID")
            if (status == "preliminary_shortlist") != bool(eligible_ids):
                raise ValueError("shortlist status contradicts eligible candidates")
            preferred = recommendation.get("preliminary_preferred_structure_id")
            if preferred is not None and preferred not in eligible_ids:
                raise ValueError("preliminary preference is not eligible")
            food_reference_id = recommendation.get("food_reference_id")
            target_days = card.get("target_shelf_life_days")

        projected.append({
            "source_row_number": row["row_number"],
            "record_id": row.get("record_id"),
            "food_reference_id": food_reference_id,
            "scenario": scenario,
            "status": status,
            "input_issues": issues,
            "requirement_gaps": requirement_gaps,
            "screening_reason_codes": screening_reasons,
            "warnings": warnings,
            "target_shelf_life_days": target_days,
            "temperature_exposures": exposure,
            "screened_candidates": candidates,
            "preliminary_preferred_structure_id": preferred,
            "recommended_structure_id": None,
            "material_prediction": None,
            "predicted_shelf_life_days": None,
            "package_feasible": False,
        })

    return {
        "contract_version": CONTRACT_VERSION,
        "source_batch_version": EXPECTED_BATCH_VERSION,
        "model": {
            "task": "material_suitability_ranking",
            "status": "not_deployed",
            "prediction_available": False,
            "model_version": None,
        },
        "recommendation_release_status": "withheld",
        "trace": {name: batch.get(name) for name in TRACE_FIELDS},
        "total_rows": len(projected),
        "rows": projected,
    }


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a frontend decision view from a preliminary batch report",
    )
    parser.add_argument("batch_report", type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="new JSON output path; never overwrites")
    args = parser.parse_args()
    try:
        if args.batch_report.resolve() == args.output.resolve():
            raise ValueError("input and output paths must differ")
        with args.batch_report.open("r", encoding="utf-8") as stream:
            batch = json.load(stream, parse_constant=_reject_nonfinite)
        result = project_frontend_decisions(batch)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"input/output error: {exc}\n")
    print(json.dumps({"output": str(args.output), "total_rows": result["total_rows"],
                      "recommendation_release_status": result["recommendation_release_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
