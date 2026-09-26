"""Batch wrapper for Stop-4 local gas/water diagnostics, never approval."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.enrichment import EnrichmentAudit, enrich_scenarios
from packsense.gas_balance import (
    FinishedPackageGasObservation, GasBalanceResult,
    audit_gas_profile, parse_gas_observations,
)
from packsense.ingestion import InputSchemaError, audit_scenarios
from packsense.masters import load_food_references
from packsense.produce_route import parse_route_register
from packsense.respiration import KineticEvidence, parse_kinetics_register
from packsense.water_balance import (
    FinishedPackageWaterObservation, audit_water_profile,
    combine_produce_profile, parse_water_observations,
)


PRODUCE_AUDIT_VERSION = "produce-local-audit-v1"


def build_produce_audit(
    enrichment: EnrichmentAudit,
    kinetics: tuple[KineticEvidence, ...],
    gas_observations: tuple[FinishedPackageGasObservation, ...],
    water_observations: tuple[FinishedPackageWaterObservation, ...],
) -> tuple[dict[str, Any], ...]:
    """Join exact record/structure keys; preserve missing evidence as gaps."""
    rates = {(item.food_reference_id, item.rate_unit): item for item in kinetics}
    if len(rates) != len(kinetics):
        raise ValueError("duplicate kinetics food/gas key")
    gases: dict[tuple[str, str], list[FinishedPackageGasObservation]] = defaultdict(list)
    waters: dict[tuple[str, str], list[FinishedPackageWaterObservation]] = defaultdict(list)
    for item in gas_observations:
        gases[(item.record_id, item.structure_id)].append(item)
    for item in water_observations:
        waters[(item.record_id, item.structure_id)].append(item)
    rows = []
    for row in enrichment.rows:
        enriched = row.enriched
        result: dict[str, Any] = {
            "row_number": row.row_number,
            "record_id": row.record_id,
            "food_reference_id": enriched.food_reference.food_id if enriched else None,
            "issues": [
                {"field": item.field, "code": item.code, "message": item.message}
                for item in row.issues
            ],
            "structures": [],
        }
        if enriched is None:
            result["status"] = "exception"
        elif enriched.produce_route_status == "confirmed_non_respiring":
            result["status"] = "not_applicable"
        elif enriched.produce_route_status != "confirmed_respiring":
            result["status"] = "unresolved_route"
        else:
            keys = sorted(key for key in gases.keys() | waters.keys() if key[0] == row.record_id)
            if not keys:
                result["status"] = "observations_missing"
            else:
                oxygen = rates.get((enriched.food_reference.food_id, "mg O2/kg/h"))
                carbon = rates.get((enriched.food_reference.food_id, "mg CO2/kg/h"))
                for _, structure_id in keys:
                    water = audit_water_profile(
                        enriched, tuple(waters[(row.record_id, structure_id)]), structure_id,
                    )
                    if oxygen is None or carbon is None:
                        gas = tuple(GasBalanceResult(
                            exposure.phase, exposure.temperature_c, "unresolved",
                            None, None, None, None,
                            ("separate_o2_co2_kinetics_missing",), (),
                            row.record_id, structure_id,
                        ) for exposure in enriched.exposures)
                    else:
                        gas = audit_gas_profile(
                            enriched, tuple(gases[(row.record_id, structure_id)]),
                            oxygen, carbon, structure_id=structure_id,
                        )
                    combined = combine_produce_profile(gas, water)
                    if any(item.status == "unresolved" for item in combined):
                        structure_status = "unresolved"
                    elif any(item.status == "local_checks_with_warnings" for item in combined):
                        structure_status = "local_checks_with_warnings"
                    else:
                        structure_status = "local_checks_only"
                    result["structures"].append({
                        "structure_id": structure_id,
                        "status": structure_status,
                        "phases": [
                            {
                                "combined": item.report(),
                                "gas": gas[index].report(),
                                "water": water[index].report(),
                            }
                            for index, item in enumerate(combined)
                        ],
                    })
                statuses = {item["status"] for item in result["structures"]}
                result["status"] = (
                    "unresolved" if "unresolved" in statuses else
                    "local_checks_with_warnings"
                    if "local_checks_with_warnings" in statuses else "local_checks_only"
                )
        rows.append(result)
    return tuple(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local produce gas and water observations")
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("food_master", type=Path)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--route-register", type=Path, required=True)
    parser.add_argument("--kinetics-register", type=Path, required=True)
    parser.add_argument("--gas-observations", type=Path, required=True)
    parser.add_argument("--water-observations", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new JSON report path")
    args = parser.parse_args()
    try:
        scenario_audit = audit_scenarios(args.scenarios, sheet_name=args.scenario_sheet)
        food_audit = load_food_references(args.food_master, sheet_name=args.food_sheet)
        sources = {
            "routes": args.route_register.read_bytes(),
            "kinetics": args.kinetics_register.read_bytes(),
            "gas": args.gas_observations.read_bytes(),
            "water": args.water_observations.read_bytes(),
        }
        routes = parse_route_register(sources["routes"])
        kinetics = parse_kinetics_register(sources["kinetics"])
        gas = parse_gas_observations(sources["gas"])
        water = parse_water_observations(sources["water"])
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    enrichment = enrich_scenarios(
        scenario_audit, food_audit, routes, hashlib.sha256(sources["routes"]).hexdigest(),
    )
    rows = build_produce_audit(enrichment, kinetics, gas, water)
    report = {
        "produce_audit_version": PRODUCE_AUDIT_VERSION,
        "scenario_sha256": enrichment.scenario_sha256,
        "food_master_sha256": enrichment.food_master_sha256,
        "source_sha256": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()
        },
        "total_rows": len(rows),
        "unresolved_rows": sum(
            row["status"] not in (
                "local_checks_only", "local_checks_with_warnings", "not_applicable",
            ) for row in rows
        ),
        "warning_rows": sum(
            row["status"] == "local_checks_with_warnings" for row in rows
        ),
        "produce_safety_certified": False,
        "shelf_life_predicted": False,
        "rows": rows,
    }
    try:
        with args.report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2) + "\n")
    except OSError as exc:
        parser.exit(2, f"report error: {exc}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if rows and report["unresolved_rows"] == 0 and report["warning_rows"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
