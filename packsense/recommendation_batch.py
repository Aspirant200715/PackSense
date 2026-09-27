"""Run the preliminary recommendation gates on a structured scenario batch.

Food and material workbooks remain reference masters. A scenario row supplies
the actual pack quantity and exposure conditions; no missing scenario values
are filled from a reference row.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.candidate_transfer import (
    FinishedPackageTransferEvidence, parse_transfer_register,
)
from packsense.enrichment import enrich_scenarios
from packsense.ingestion import InputSchemaError, ScenarioAudit, audit_scenarios
from packsense.masters import (
    FoodMasterEntry, MasterAudit, MaterialMasterEntry, load_food_references,
    load_material_grades,
)
from packsense.produce_route import RouteEvidence, parse_route_register
from packsense.recommendation import screen_package_candidates
from packsense.recommendation_output import summarize_batch, write_summary_csv
from packsense.requirements import (
    ProtectionAssessment, _parse_protection_assessments, derive_requirement_card,
)
from packsense.structure_review import (
    StructureReviewAudit, audit_structure_reviews, parse_structure_review_register,
)
from packsense.structures import audit_structure_catalogue


BATCH_VERSION = "basic-recommendation-batch-v1"


def build_batch_recommendations(
    scenarios: ScenarioAudit,
    foods: MasterAudit[FoodMasterEntry],
    materials: MasterAudit[MaterialMasterEntry],
    *,
    routes: tuple[RouteEvidence, ...] = (),
    route_register_sha256: str | None = None,
    assessments: tuple[ProtectionAssessment, ...] = (),
    assessment_register_sha256: str | None = None,
    structure_review: StructureReviewAudit | None = None,
    transfer_evidence: tuple[FinishedPackageTransferEvidence, ...] = (),
    transfer_register_sha256: str | None = None,
) -> dict[str, Any]:
    """Return one auditable exception or recommendation result per input row."""
    if not scenarios.rows:
        raise ValueError("scenario batch has no data rows")
    if foods.issues or materials.issues or not foods.entries or not materials.entries:
        raise ValueError("food and material masters must have accepted rows and no rejected rows")
    if routes and route_register_sha256 is None:
        raise ValueError("route evidence requires a register hash")
    if assessments and assessment_register_sha256 is None:
        raise ValueError("food assessments require a register hash")
    if transfer_evidence and (transfer_register_sha256 is None or structure_review is None):
        raise ValueError("package transfer evidence requires a register hash and structure review")

    enriched = enrich_scenarios(scenarios, foods, routes, route_register_sha256)
    assessments_by_food: dict[str, list[ProtectionAssessment]] = defaultdict(list)
    for item in assessments:
        assessments_by_food[item.food_reference_id].append(item)
    transfers_by_record: dict[str, list[FinishedPackageTransferEvidence]] = defaultdict(list)
    for item in transfer_evidence:
        transfers_by_record[item.record_id].append(item)

    rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    requirement_gap_counts: Counter[str] = Counter()
    input_issue_counts: Counter[tuple[str, str]] = Counter()
    for row in enriched.rows:
        if row.enriched is None:
            input_issue_counts.update((issue.field, issue.code) for issue in row.issues)
            rows.append({
                "row_number": row.row_number,
                "record_id": row.record_id,
                "food_reference_row": None,
                "status": "exception",
                "issues": [
                    {"field": issue.field, "code": issue.code, "message": issue.message}
                    for issue in row.issues
                ],
                "requirement_card": None,
                "recommendation": None,
            })
            continue

        card = derive_requirement_card(
            row.enriched,
            tuple(assessments_by_food.get(row.enriched.food_reference.food_id, ())),
        )
        requirement_gap_counts.update(card.gaps)
        recommendation = screen_package_candidates(
            card, row.enriched.scenario.commodity_type, structure_review,
            transfers_by_record.get(card.record_id, ()),
            current_material_master_sha256=materials.source_sha256,
        )
        reason_counts.update(recommendation.reason_codes)
        rows.append({
            "row_number": row.row_number,
            "record_id": row.record_id,
            "food_reference_row": row.enriched.food_reference_row,
            "status": recommendation.status.value,
            "issues": [],
            "requirement_card": card.report(),
            "recommendation": recommendation.report(),
        })

    status_counts = Counter(row["status"] for row in rows)
    return {
        "batch_version": BATCH_VERSION,
        "scenario_source_path": scenarios.source_path,
        "scenario_sha256": scenarios.source_sha256,
        "food_master_source_path": foods.source_path,
        "food_master_sha256": foods.source_sha256,
        "material_master_source_path": materials.source_path,
        "material_master_sha256": materials.source_sha256,
        "food_master_rows": len(foods.entries),
        "material_master_rows": len(materials.entries),
        "route_register_sha256": route_register_sha256,
        "route_evidence_count": len(routes),
        "assessment_register_sha256": assessment_register_sha256,
        "food_assessment_count": len(assessments),
        "structure_catalogue_sha256": (
            structure_review.catalogue_sha256 if structure_review else None
        ),
        "structure_review_register_sha256": (
            structure_review.review_register_sha256 if structure_review else None
        ),
        "structure_review_status": structure_review.status if structure_review else "missing",
        "reviewed_structure_count": len(structure_review.reviewed) if structure_review else 0,
        "structure_review_issues": [
            {"structure_id": issue.structure_id, "code": issue.code}
            for issue in structure_review.issues
        ] if structure_review else [],
        "transfer_register_sha256": transfer_register_sha256,
        "transfer_observation_count": len(transfer_evidence),
        "total_rows": len(rows),
        "exception_rows": status_counts["exception"],
        "not_ready_rows": status_counts["not_ready"],
        "preliminary_shortlist_rows": status_counts["preliminary_shortlist"],
        "preliminary_preferred_rows": sum(
            row["recommendation"] is not None
            and row["recommendation"]["preliminary_preferred_structure_id"] is not None
            for row in rows
        ),
        "reason_counts": [
            {"code": reason, "count": count}
            for reason, count in sorted(reason_counts.items())
        ],
        "requirement_gap_counts": [
            {"code": reason, "count": count}
            for reason, count in sorted(requirement_gap_counts.items())
        ],
        "input_issue_counts": [
            {"field": field, "code": code, "count": count}
            for (field, code), count in sorted(input_issue_counts.items())
        ],
        "package_feasible": False,
        "shelf_life_predicted": False,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit a scenario batch through the preliminary package shortlist",
    )
    parser.add_argument("scenarios", type=Path, help="structured scenario CSV or XLSX")
    parser.add_argument("--food-master", type=Path, required=True)
    parser.add_argument("--material-master", type=Path, required=True)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--material-sheet")
    parser.add_argument("--route-register", type=Path)
    parser.add_argument("--assessments", type=Path)
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--structure-reviews", type=Path)
    parser.add_argument("--transfers", type=Path)
    parser.add_argument("--report", type=Path, required=True, help="new JSON output path")
    parser.add_argument("--summary-csv", type=Path, help="new one-row-per-scenario CSV path")
    args = parser.parse_args()
    if bool(args.structures) != bool(args.structure_reviews):
        parser.error("--structures and --structure-reviews must be supplied together")
    if args.transfers and not args.structures:
        parser.error("--transfers requires --structures and --structure-reviews")
    if args.summary_csv is not None:
        if args.summary_csv.resolve() == args.report.resolve():
            parser.error("--summary-csv and --report must be different paths")
        if args.summary_csv.exists():
            parser.error("summary CSV already exists; choose a new path")
        if not args.summary_csv.parent.is_dir():
            parser.error("summary CSV parent directory does not exist")

    try:
        scenarios = audit_scenarios(args.scenarios, sheet_name=args.scenario_sheet)
        foods = load_food_references(args.food_master, sheet_name=args.food_sheet)
        materials = load_material_grades(args.material_master, sheet_name=args.material_sheet)
        if foods.issues or materials.issues:
            raise InputSchemaError("resolve rejected food/material master rows before batch screening")
        route_raw = args.route_register.read_bytes() if args.route_register else None
        routes = parse_route_register(route_raw) if route_raw is not None else ()
        route_hash = hashlib.sha256(route_raw).hexdigest() if route_raw is not None else None
        assessment_raw = args.assessments.read_bytes() if args.assessments else None
        assessments = (
            _parse_protection_assessments(assessment_raw)
            if assessment_raw is not None else ()
        )
        assessment_hash = (
            hashlib.sha256(assessment_raw).hexdigest()
            if assessment_raw is not None else None
        )
        structure_review = None
        if args.structures:
            catalogue = audit_structure_catalogue(
                args.structures,
                grades={entry.grade.material_id: entry.grade for entry in materials.entries},
                material_master_sha256=materials.source_sha256,
            )
            review = parse_structure_review_register(args.structure_reviews.read_bytes())
            structure_review = audit_structure_reviews(catalogue, review)
        transfer_raw = args.transfers.read_bytes() if args.transfers else None
        transfers = parse_transfer_register(transfer_raw) if transfer_raw is not None else ()
        transfer_hash = (
            hashlib.sha256(transfer_raw).hexdigest() if transfer_raw is not None else None
        )
        report = build_batch_recommendations(
            scenarios, foods, materials,
            routes=routes, route_register_sha256=route_hash,
            assessments=assessments, assessment_register_sha256=assessment_hash,
            structure_review=structure_review,
            transfer_evidence=transfers, transfer_register_sha256=transfer_hash,
        )
        if args.summary_csv is not None:
            summarize_batch(report)
        with args.report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
        if args.summary_csv is not None:
            write_summary_csv(report, args.summary_csv)
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input/report error: {exc}\n")
    summary = {key: value for key, value in report.items() if key != "rows"}
    if args.summary_csv is not None:
        summary["summary_csv_path"] = str(args.summary_csv)
    print(json.dumps(summary, indent=2))
    return 1 if report["exception_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
