"""Stop 2: join a scenario to one sourced food row and retain its exposures.

This stage does not infer missing operating conditions, certify fresh-produce
status, calculate barriers, or make a packaging recommendation.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.contracts import FoodReference, ScenarioInput
from packsense.ingestion import (
    IngestionIssue,
    InputSchemaError,
    ScenarioAudit,
    audit_scenarios,
)
from packsense.masters import FoodMasterEntry, MasterAudit, load_food_references


@dataclass(frozen=True, slots=True)
class ExposureCondition:
    phase: str
    temperature_c: float
    relative_humidity_pct: float | None
    duration_hours: float | None
    safety_check_only: bool


@dataclass(frozen=True, slots=True)
class EnrichedScenario:
    scenario: ScenarioInput
    food_reference: FoodReference
    food_reference_row: int
    food_master_sha256: str
    pH_reference_evidence: str
    produce_route_status: str
    exposures: tuple[ExposureCondition, ...]


@dataclass(frozen=True, slots=True)
class EnrichmentRow:
    row_number: int
    record_id: str | None
    enriched: EnrichedScenario | None
    issues: tuple[IngestionIssue, ...]


@dataclass(frozen=True, slots=True)
class EnrichmentAudit:
    scenario_sha256: str
    food_master_sha256: str
    rows: tuple[EnrichmentRow, ...]

    def report(self) -> dict[str, Any]:
        issues = [issue for row in self.rows for issue in row.issues]
        counts = Counter((issue.field, issue.code) for issue in issues)
        return {
            "scenario_sha256": self.scenario_sha256,
            "food_master_sha256": self.food_master_sha256,
            "total_rows": len(self.rows),
            "enriched_rows": sum(row.enriched is not None for row in self.rows),
            "exception_rows": sum(row.enriched is None for row in self.rows),
            "unclassified_produce_route_rows": sum(
                row.enriched is not None
                and row.enriched.produce_route_status == "unclassified"
                for row in self.rows
            ),
            "issue_counts": [
                {"field": field, "code": code, "count": count}
                for (field, code), count in sorted(counts.items())
            ],
            "rows": [
                {
                    "row_number": row.row_number,
                    "record_id": row.record_id,
                    "status": "enriched" if row.enriched is not None else "exception",
                    "food_reference_id": (
                        row.enriched.food_reference.food_id if row.enriched is not None else None
                    ),
                    "food_reference_row": (
                        row.enriched.food_reference_row if row.enriched is not None else None
                    ),
                    "produce_route_status": (
                        row.enriched.produce_route_status if row.enriched is not None else None
                    ),
                    "issues": [
                        {"field": issue.field, "code": issue.code, "message": issue.message}
                        for issue in row.issues
                    ],
                }
                for row in self.rows
            ],
        }


def _name_key(name: str) -> str:
    """Only whitespace/case normalization; no fuzzy or family-level match."""
    return re.sub(r"\s+", " ", name.strip()).casefold()


def exposure_profile(scenario: ScenarioInput) -> tuple[ExposureCondition, ...]:
    """Keep normal exposures separate from an excursion with unknown duration.

    Desired shelf life is a target, not a measured storage duration. Transit RH
    and excursion duration are absent from the input contract and stay unknown.
    """
    return (
        ExposureCondition(
            "storage", scenario.storage_temperature_c,
            scenario.storage_relative_humidity_pct, None, False,
        ),
        ExposureCondition(
            "transport", scenario.transport_temperature_c,
            None, scenario.transport_duration_hours, False,
        ),
        ExposureCondition(
            "transport_max_excursion", scenario.transport_max_temperature_c,
            None, None, True,
        ),
    )


def enrich_scenarios(
    scenarios: ScenarioAudit, foods: MasterAudit[FoodMasterEntry]
) -> EnrichmentAudit:
    """Resolve exact food identity; retain unresolved rows as exceptions."""
    by_id = {entry.reference.food_id: entry for entry in foods.entries}
    by_name: dict[str, list[FoodMasterEntry]] = defaultdict(list)
    for entry in foods.entries:
        by_name[_name_key(entry.reference.commodity_type)].append(entry)

    rows: list[EnrichmentRow] = []
    for input_row in scenarios.rows:
        scenario = input_row.scenario
        if scenario is None:
            rows.append(EnrichmentRow(
                input_row.row_number,
                _record_id(input_row.raw_values.get("record_id")),
                None,
                input_row.issues,
            ))
            continue

        issues: list[IngestionIssue] = []

        def issue(field: str, code: str, message: str) -> None:
            issues.append(
                IngestionIssue(input_row.row_number, scenario.record_id, field, code, message)
            )

        if scenario.food_reference_id is not None:
            entry = by_id.get(scenario.food_reference_id)
            if entry is None:
                issue(
                    "food_reference_id", "reference_id_not_found",
                    "food reference ID is absent from the accepted master rows",
                )
            elif _name_key(entry.reference.commodity_type) != _name_key(scenario.commodity_type):
                issue(
                    "commodity_type", "reference_name_mismatch",
                    "commodity name does not match the selected food reference ID",
                )
        else:
            matches = by_name.get(_name_key(scenario.commodity_type), [])
            if not matches:
                issue("commodity_type", "reference_not_found", "no exact food reference name match")
                entry = None
            elif len(matches) > 1:
                issue(
                    "food_reference_id", "reference_ambiguous",
                    "multiple food references share this name; supply food_reference_id",
                )
                entry = None
            else:
                entry = matches[0]

        if (
            entry is not None
            and entry.reference.respiration_rate is not None
            and scenario.respiration_rate is None
        ):
            issue(
                "respiration_rate", "missing_respiration",
                "this food reference reports respiration; provide rate, unit, and reference temperature",
            )

        enriched = None
        if not issues and entry is not None:
            route_status = (
                "respiration_evidence_present"
                if scenario.respiration_rate is not None or entry.reference.respiration_rate is not None
                else "unclassified"
            )
            enriched = EnrichedScenario(
                scenario, entry.reference, entry.source_row_number,
                foods.source_sha256, entry.pH_evidence, route_status,
                exposure_profile(scenario),
            )
        rows.append(EnrichmentRow(input_row.row_number, scenario.record_id, enriched, tuple(issues)))
    return EnrichmentAudit(scenarios.source_sha256, foods.source_sha256, tuple(rows))


def _record_id(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Join scenario rows to exact sourced food references")
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("food_master", type=Path)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--report", type=Path, help="new JSON report path")
    args = parser.parse_args()
    try:
        scenario_audit = audit_scenarios(args.scenarios, sheet_name=args.scenario_sheet)
        food_audit = load_food_references(args.food_master, sheet_name=args.food_sheet)
    except (InputSchemaError, OSError, csv.Error, BadZipFile) as exc:
        parser.exit(2, f"input error: {exc}\n")
    audit = enrich_scenarios(scenario_audit, food_audit)
    report = audit.report()
    if args.report:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except FileExistsError:
            parser.exit(2, "report error: output already exists; choose a new path\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if not report["exception_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
