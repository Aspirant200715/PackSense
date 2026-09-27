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
from packsense.gas_balance import FinishedPackageGasObservation, parse_gas_observations
from packsense.grade_reference import compare_grade_barriers
from packsense.ingestion import InputSchemaError, ScenarioAudit, audit_scenarios
from packsense.masters import (
    FoodMasterEntry, MasterAudit, MaterialMasterEntry, load_food_references,
    load_material_grades,
)
from packsense.produce_route import RouteEvidence, parse_route_register
from packsense.produce_audit import (
    PRODUCE_AUDIT_VERSION, PRODUCE_REVIEW_BINDING_VERSION,
    bind_reviewed_produce_structures, build_produce_audit,
)
from packsense.recommendation import screen_package_candidates
from packsense.recommendation_output import summarize_batch, write_summary_csv
from packsense.requirements import (
    ProtectionAssessment, _parse_protection_assessments, derive_requirement_card,
)
from packsense.respiration import KineticEvidence, parse_kinetics_register
from packsense.structure_review import (
    StructureReviewAudit, audit_structure_reviews, parse_structure_review_register,
)
from packsense.structures import audit_structure_catalogue
from packsense.water_balance import FinishedPackageWaterObservation, parse_water_observations


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
    include_grade_reference_comparison: bool = False,
    include_produce_diagnostics: bool = False,
    kinetics: tuple[KineticEvidence, ...] = (),
    kinetics_register_sha256: str | None = None,
    gas_observations: tuple[FinishedPackageGasObservation, ...] = (),
    gas_observation_register_sha256: str | None = None,
    water_observations: tuple[FinishedPackageWaterObservation, ...] = (),
    water_observation_register_sha256: str | None = None,
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
    if type(include_grade_reference_comparison) is not bool:
        raise ValueError("include_grade_reference_comparison must be boolean")
    if type(include_produce_diagnostics) is not bool:
        raise ValueError("include_produce_diagnostics must be boolean")
    produce_sources = (
        (kinetics, kinetics_register_sha256),
        (gas_observations, gas_observation_register_sha256),
        (water_observations, water_observation_register_sha256),
    )
    if any(entries and source_hash is None for entries, source_hash in produce_sources):
        raise ValueError("produce evidence requires a source register hash")
    if not include_produce_diagnostics and any(
        entries or source_hash is not None for entries, source_hash in produce_sources
    ):
        raise ValueError("produce evidence requires include_produce_diagnostics")

    enriched = enrich_scenarios(scenarios, foods, routes, route_register_sha256)
    produce_rows = (
        build_produce_audit(enriched, kinetics, gas_observations, water_observations)
        if include_produce_diagnostics else ()
    )
    if include_produce_diagnostics:
        produce_rows = bind_reviewed_produce_structures(
            enriched, produce_rows, structure_review, materials.source_sha256,
            gas_observations, water_observations,
        )
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
    for index, row in enumerate(enriched.rows):
        if row.enriched is None:
            input_issue_counts.update((issue.field, issue.code) for issue in row.issues)
            result_row = {
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
            }
            if include_grade_reference_comparison:
                result_row["grade_reference_comparison"] = None
            if include_produce_diagnostics:
                result_row["produce_local_diagnostics"] = produce_rows[index]
            rows.append(result_row)
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
        result_row = {
            "row_number": row.row_number,
            "record_id": row.record_id,
            "food_reference_row": row.enriched.food_reference_row,
            "status": recommendation.status.value,
            "issues": [],
            "requirement_card": card.report(),
            "recommendation": recommendation.report(),
        }
        if include_grade_reference_comparison:
            result_row["grade_reference_comparison"] = compare_grade_barriers(
                card, materials,
            )
        if include_produce_diagnostics:
            result_row["produce_local_diagnostics"] = produce_rows[index]
        rows.append(result_row)

    status_counts = Counter(row["status"] for row in rows)
    report = {
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
    if include_grade_reference_comparison:
        report["grade_reference_comparison_rows"] = sum(
            row["grade_reference_comparison"] is not None for row in rows
        )
        report["grade_reference_frontier_rows"] = sum(
            row["grade_reference_comparison"] is not None
            and row["grade_reference_comparison"]["status"] == "reference_comparison"
            for row in rows
        )
    if include_produce_diagnostics:
        report["produce_local_audit_version"] = PRODUCE_AUDIT_VERSION
        report["produce_review_binding_version"] = PRODUCE_REVIEW_BINDING_VERSION
        report["kinetics_register_sha256"] = kinetics_register_sha256
        report["gas_observation_register_sha256"] = gas_observation_register_sha256
        report["water_observation_register_sha256"] = water_observation_register_sha256
        report["produce_local_diagnostic_rows"] = len(produce_rows)
        report["produce_local_unresolved_rows"] = sum(
            row["status"] not in (
                "not_applicable", "local_checks_only", "local_checks_with_warnings",
            ) for row in produce_rows
        )
        report["produce_local_warning_rows"] = sum(
            row["status"] == "local_checks_with_warnings" for row in produce_rows
        )
        report["produce_review_bound_structure_count"] = sum(
            row["review_bound_structure_count"] for row in produce_rows
        )
        report["produce_review_unresolved_structure_count"] = sum(
            len(row["structures"]) - row["review_bound_structure_count"]
            for row in produce_rows
        )
        report["produce_diagnostic_structure_review_joined"] = (
            report["produce_review_bound_structure_count"] > 0
            and all(row["review_binding_status"] in ("joined", "not_applicable")
                    for row in produce_rows)
        )
        report["produce_safety_certified"] = False
    return report


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
    parser.add_argument("--produce-diagnostics", action="store_true",
                        help="opt-in local produce gas/water audit; never MAP approval")
    parser.add_argument("--kinetics-register", type=Path)
    parser.add_argument("--gas-observations", type=Path)
    parser.add_argument("--water-observations", type=Path)
    parser.add_argument(
        "--compare-grade-references", action="store_true",
        help="opt-in lab-condition film-grade comparison; never package suitability",
    )
    parser.add_argument("--report", type=Path, required=True, help="new JSON output path")
    parser.add_argument("--summary-csv", type=Path, help="new one-row-per-scenario CSV path")
    args = parser.parse_args()
    if bool(args.structures) != bool(args.structure_reviews):
        parser.error("--structures and --structure-reviews must be supplied together")
    if args.transfers and not args.structures:
        parser.error("--transfers requires --structures and --structure-reviews")
    if args.produce_diagnostics and not args.route_register:
        parser.error("--produce-diagnostics requires --route-register")
    if not args.produce_diagnostics and any((
        args.kinetics_register, args.gas_observations, args.water_observations,
    )):
        parser.error("produce evidence files require --produce-diagnostics")
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
        kinetics_raw = args.kinetics_register.read_bytes() if args.kinetics_register else None
        kinetics = parse_kinetics_register(kinetics_raw) if kinetics_raw is not None else ()
        kinetics_hash = hashlib.sha256(kinetics_raw).hexdigest() if kinetics_raw is not None else None
        gas_raw = args.gas_observations.read_bytes() if args.gas_observations else None
        gas = parse_gas_observations(gas_raw) if gas_raw is not None else ()
        gas_hash = hashlib.sha256(gas_raw).hexdigest() if gas_raw is not None else None
        water_raw = args.water_observations.read_bytes() if args.water_observations else None
        water = parse_water_observations(water_raw) if water_raw is not None else ()
        water_hash = hashlib.sha256(water_raw).hexdigest() if water_raw is not None else None
        report = build_batch_recommendations(
            scenarios, foods, materials,
            routes=routes, route_register_sha256=route_hash,
            assessments=assessments, assessment_register_sha256=assessment_hash,
            structure_review=structure_review,
            transfer_evidence=transfers, transfer_register_sha256=transfer_hash,
            include_grade_reference_comparison=args.compare_grade_references,
            include_produce_diagnostics=args.produce_diagnostics,
            kinetics=kinetics, kinetics_register_sha256=kinetics_hash,
            gas_observations=gas, gas_observation_register_sha256=gas_hash,
            water_observations=water, water_observation_register_sha256=water_hash,
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
