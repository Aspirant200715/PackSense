"""Stop 4: source-scoped temperature correction of measured produce respiration.

The Q10 relation is applied only inside its reviewed food, gas-composition,
and temperature domain. CO2 production and O2 consumption are distinct
measurements; neither is reconstructed from the other here.
"""

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from math import isclose, isfinite
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario, enrich_scenarios
from packsense.ingestion import InputSchemaError, audit_scenarios
from packsense.masters import load_food_references
from packsense.produce_route import parse_route_register


KINETICS_VERSION = "produce-q10-v1"
RATE_UNITS = frozenset({"mg CO2/kg/h", "mg O2/kg/h"})


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


@dataclass(frozen=True, slots=True)
class KineticEvidence:
    food_reference_id: str
    measured_rate: float
    rate_unit: str
    reference_temperature_c: float
    q10: float
    valid_temperature_min_c: float
    valid_temperature_max_c: float
    reference_o2_pct: float
    reference_co2_pct: float
    rate_source_id: str
    q10_source_id: str
    source_locator: str
    approval_id: str
    rate_basis: EvidenceBasis
    q10_basis: EvidenceBasis

    def __post_init__(self) -> None:
        for name in (
            "food_reference_id", "rate_source_id", "q10_source_id",
            "source_locator", "approval_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")
        if self.rate_unit not in RATE_UNITS:
            raise ValueError("rate_unit must identify CO2 production or O2 consumption")
        if self.rate_basis is not EvidenceBasis.MEASURED:
            raise ValueError("reference rate needs measured evidence")
        if not isinstance(self.q10_basis, EvidenceBasis) or self.q10_basis not in (
            EvidenceBasis.MEASURED, EvidenceBasis.VALIDATED_CORRECTION,
        ):
            raise ValueError("q10 needs measured or validated-correction evidence")
        if not _finite(self.measured_rate) or self.measured_rate <= 0:
            raise ValueError("measured_rate must be positive and finite")
        if not _finite(self.q10) or self.q10 <= 0:
            raise ValueError("q10 must be positive and finite")
        for low_name, high_name in (
            ("valid_temperature_min_c", "valid_temperature_max_c"),
        ):
            low, high = getattr(self, low_name), getattr(self, high_name)
            if not _finite(low) or not _finite(high) or low > high:
                raise ValueError(f"{low_name}/{high_name} need finite ordered bounds")
        if self.valid_temperature_min_c < -273.15:
            raise ValueError("temperature is below absolute zero")
        for name in ("reference_temperature_c", "reference_o2_pct", "reference_co2_pct"):
            if not _finite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not self.valid_temperature_min_c <= self.reference_temperature_c <= self.valid_temperature_max_c:
            raise ValueError("reference temperature is outside the validated range")
        if not (
            0 <= self.reference_o2_pct <= 100
            and 0 <= self.reference_co2_pct <= 100
            and self.reference_o2_pct + self.reference_co2_pct <= 100
        ):
            raise ValueError("reference gas composition exceeds 100 percent")


@dataclass(frozen=True, slots=True)
class RateProjection:
    phase: str
    temperature_c: float
    duration_hours: float | None
    safety_check_only: bool
    rate: float | None
    rate_unit: str
    status: str
    rate_source_id: str
    q10_source_id: str
    approval_id: str

    def report(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "temperature_c": self.temperature_c,
            "duration_hours": self.duration_hours,
            "safety_check_only": self.safety_check_only,
            "rate": self.rate,
            "rate_unit": self.rate_unit,
            "status": self.status,
            "rate_source_id": self.rate_source_id,
            "q10_source_id": self.q10_source_id,
            "approval_id": self.approval_id,
        }


def correct_rate(
    enriched: EnrichedScenario,
    evidence: KineticEvidence,
    temperature_c: float,
    oxygen_pct: float,
    carbon_dioxide_pct: float,
) -> tuple[float | None, str]:
    """Return a same-gas rate or an explicit blocker, never an extrapolation."""
    scenario = enriched.scenario
    if enriched.produce_route_status != "confirmed_respiring":
        return None, "route_not_confirmed_respiring"
    if evidence.food_reference_id != enriched.food_reference.food_id:
        return None, "food_id_mismatch"
    if (
        scenario.respiration_rate is None
        or scenario.respiration_reference_temperature_c is None
        or scenario.respiration_rate_unit != evidence.rate_unit
        or not isclose(
        scenario.respiration_rate, evidence.measured_rate, rel_tol=1e-6, abs_tol=1e-9,
    ) or not isclose(
        scenario.respiration_reference_temperature_c,
        evidence.reference_temperature_c, rel_tol=0, abs_tol=1e-6,
    )):
        return None, "reference_measurement_mismatch"
    if not _finite(temperature_c) or not (
        evidence.valid_temperature_min_c <= temperature_c <= evidence.valid_temperature_max_c
    ):
        return None, "temperature_out_of_scope"
    if not _finite(oxygen_pct) or not _finite(carbon_dioxide_pct) or (
        oxygen_pct < 0 or carbon_dioxide_pct < 0
        or oxygen_pct + carbon_dioxide_pct > 100
    ):
        return None, "invalid_gas_composition"
    # Q10 corrects temperature only. It does not provide a gas-response
    # surface; another O2/CO2 mixture needs separately measured rate data.
    if not (
        isclose(oxygen_pct, evidence.reference_o2_pct, rel_tol=0, abs_tol=1e-6)
        and isclose(carbon_dioxide_pct, evidence.reference_co2_pct, rel_tol=0, abs_tol=1e-6)
    ):
        return None, "atmosphere_out_of_scope"
    value = evidence.measured_rate * evidence.q10 ** (
        (temperature_c - evidence.reference_temperature_c) / 10
    )
    if not isfinite(value):
        return None, "nonfinite_projection"
    return value, "reference_atmosphere_temperature_projection"


def project_exposures(
    enriched: EnrichedScenario, evidence: KineticEvidence,
) -> tuple[RateProjection, ...]:
    """Project each exposure at the evidence's reference atmosphere only."""
    results = []
    for exposure in enriched.exposures:
        value, status = correct_rate(
            enriched, evidence, exposure.temperature_c,
            evidence.reference_o2_pct, evidence.reference_co2_pct,
        )
        results.append(RateProjection(
            exposure.phase, exposure.temperature_c, exposure.duration_hours,
            exposure.safety_check_only, value, evidence.rate_unit, status,
            evidence.rate_source_id, evidence.q10_source_id, evidence.approval_id,
        ))
    return tuple(results)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_kinetics_register(raw: bytes) -> tuple[KineticEvidence, ...]:
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "kinetics"}:
        raise ValueError("kinetics register needs schema_version and kinetics only")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported kinetics-register schema")
    if not isinstance(payload["kinetics"], list):
        raise ValueError("kinetics must be an array")
    fields = set(KineticEvidence.__dataclass_fields__)
    accepted = []
    seen = set()
    for index, item in enumerate(payload["kinetics"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"kinetics {index}: missing or unexpected fields")
        try:
            entry = KineticEvidence(**{
                **item,
                "rate_basis": EvidenceBasis(item["rate_basis"]),
                "q10_basis": EvidenceBasis(item["q10_basis"]),
            })
        except (TypeError, ValueError) as exc:
            raise ValueError(f"kinetics {index}: {exc}") from exc
        key = (entry.food_reference_id, entry.rate_unit)
        if key in seen:
            raise ValueError(f"kinetics {index}: duplicate food/gas rate")
        seen.add(key)
        accepted.append(entry)
    return tuple(accepted)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit scoped produce respiration correction")
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("food_master", type=Path)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--route-register", type=Path, required=True)
    parser.add_argument("--kinetics-register", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="new JSON report path")
    args = parser.parse_args()
    try:
        scenario_audit = audit_scenarios(args.scenarios, sheet_name=args.scenario_sheet)
        food_audit = load_food_references(args.food_master, sheet_name=args.food_sheet)
        raw_routes = args.route_register.read_bytes()
        raw_kinetics = args.kinetics_register.read_bytes()
        routes = parse_route_register(raw_routes)
        kinetics = parse_kinetics_register(raw_kinetics)
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    audit = enrich_scenarios(
        scenario_audit, food_audit, routes, hashlib.sha256(raw_routes).hexdigest(),
    )
    by_key = {(item.food_reference_id, item.rate_unit): item for item in kinetics}
    rows = []
    for row in audit.rows:
        enriched = row.enriched
        evidence = (
            by_key.get((enriched.food_reference.food_id, enriched.scenario.respiration_rate_unit))
            if enriched else None
        )
        projections = (
            project_exposures(enriched, evidence)
            if enriched and evidence and enriched.produce_route_status != "confirmed_non_respiring"
            else ()
        )
        if enriched is None:
            status = "exception"
        elif enriched.produce_route_status == "confirmed_non_respiring":
            status = "not_applicable"
        elif projections and all(item.rate is not None for item in projections):
            status = "projected_reference_atmosphere"
        else:
            status = "kinetics_unresolved"
        rows.append({
            "row_number": row.row_number,
            "record_id": row.record_id,
            "status": status,
            "issues": [issue.code for issue in row.issues],
            "projections": [item.report() for item in projections],
        })
    report = {
        "kinetics_version": KINETICS_VERSION,
        "scenario_sha256": audit.scenario_sha256,
        "food_master_sha256": audit.food_master_sha256,
        "route_register_sha256": audit.route_register_sha256,
        "kinetics_register_sha256": hashlib.sha256(raw_kinetics).hexdigest(),
        "total_rows": len(rows),
        "reference_atmosphere_projected_rows": sum(
            row["status"] == "projected_reference_atmosphere" for row in rows
        ),
        "rows": rows,
    }
    if args.report:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except OSError as exc:
            parser.exit(2, f"report error: {exc}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if rows and all(
        row["status"] in ("projected_reference_atmosphere", "not_applicable") for row in rows
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
