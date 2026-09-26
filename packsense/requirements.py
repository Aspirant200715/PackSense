"""Stop 3: source-scoped food protection requirements, before package lookup.

Food composition is not itself an oxygen or moisture failure limit. An
assessment is usable only for the exact food, fill quantity, and full stated
temperature/humidity envelope. No OTR/WVTR, package feasibility, or shelf-life
claim is produced here.
"""

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from math import isclose, isfinite
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.contracts import EvidenceBasis, HandlingSeverity, StorageType
from packsense.enrichment import EnrichedScenario, ExposureCondition, enrich_scenarios
from packsense.ingestion import InputSchemaError, audit_scenarios
from packsense.masters import load_food_references
from packsense.produce_route import parse_route_register


RULE_SET_VERSION = "requirements-v1"


class ProtectionMechanism(StrEnum):
    OXYGEN_INGRESS = "oxygen_ingress"
    MOISTURE_GAIN = "moisture_gain"
    MOISTURE_LOSS = "moisture_loss"


class AssessmentDecision(StrEnum):
    LIMIT = "limit"
    NOT_REQUIRED = "not_required"


TRANSFER_UNITS = {
    ProtectionMechanism.OXYGEN_INGRESS: "mmol_o2_per_pack",
    ProtectionMechanism.MOISTURE_GAIN: "g_h2o_per_pack",
    ProtectionMechanism.MOISTURE_LOSS: "g_h2o_per_pack",
}


@dataclass(frozen=True, slots=True)
class ProtectionAssessment:
    """Manually approved source finding, not a generated training observation.

    A LIMIT is a cumulative tolerated transfer for this exact fill quantity,
    validated across the stated temperature/RH envelope. NOT_REQUIRED is
    likewise an evidence-backed judgment, never the default for an empty cell.
    """

    food_reference_id: str
    mechanism: ProtectionMechanism
    decision: AssessmentDecision
    max_cumulative_transfer: float | None
    transfer_unit: str | None
    pack_quantity: float
    pack_quantity_unit: str
    valid_temperature_min_c: float
    valid_temperature_max_c: float
    valid_rh_min_pct: float
    valid_rh_max_pct: float
    assessment_rationale: str
    source_id: str
    source_locator: str
    approval_id: str
    evidence_basis: EvidenceBasis

    def __post_init__(self) -> None:
        for name in (
            "food_reference_id", "assessment_rationale", "source_id",
            "source_locator", "approval_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty text")
        if not isinstance(self.mechanism, ProtectionMechanism):
            raise ValueError("mechanism must be a ProtectionMechanism")
        if not isinstance(self.decision, AssessmentDecision):
            raise ValueError("decision must be an AssessmentDecision")
        if not isinstance(self.evidence_basis, EvidenceBasis) or self.evidence_basis not in (
            EvidenceBasis.MEASURED, EvidenceBasis.VALIDATED_CORRECTION,
        ):
            raise ValueError("approved assessments require measured or validated evidence")
        if self.pack_quantity_unit not in ("g", "mL"):
            raise ValueError("pack_quantity_unit must be canonical g or mL")
        if not _positive(self.pack_quantity):
            raise ValueError("pack_quantity must be finite and positive")
        for low_name, high_name in (
            ("valid_temperature_min_c", "valid_temperature_max_c"),
            ("valid_rh_min_pct", "valid_rh_max_pct"),
        ):
            low, high = getattr(self, low_name), getattr(self, high_name)
            if not _number(low) or not _number(high) or low > high:
                raise ValueError(f"{low_name}/{high_name} must be finite ordered bounds")
        if not (0 <= self.valid_rh_min_pct <= self.valid_rh_max_pct <= 100):
            raise ValueError("validated RH bounds must be within 0..100 percent")
        if self.valid_temperature_min_c < -273.15:
            raise ValueError("validated temperature is below absolute zero")
        if self.decision is AssessmentDecision.LIMIT:
            if not _positive(self.max_cumulative_transfer):
                raise ValueError("a limit needs a finite positive cumulative transfer")
            if self.transfer_unit != TRANSFER_UNITS[self.mechanism]:
                raise ValueError("transfer_unit does not match the mechanism")
        elif self.max_cumulative_transfer is not None or self.transfer_unit is not None:
            raise ValueError("not_required must not carry a transfer value or unit")


@dataclass(frozen=True, slots=True)
class TransferBudget:
    mechanism: ProtectionMechanism
    max_cumulative_transfer: float
    unit: str
    target_average_transfer_per_day: float
    source_id: str
    approval_id: str


@dataclass(frozen=True, slots=True)
class AppliedAssessment:
    mechanism: ProtectionMechanism
    decision: AssessmentDecision
    source_id: str
    source_locator: str
    approval_id: str
    evidence_basis: EvidenceBasis


@dataclass(frozen=True, slots=True)
class RequirementCard:
    record_id: str
    food_reference_id: str
    food_master_sha256: str
    rule_set_version: str
    target_shelf_life_days: float
    storage_type: StorageType
    transport_mode: str
    exposures: tuple[ExposureCondition, ...]
    service_temperature_min_c: float
    service_temperature_max_c: float
    storage_relative_humidity_pct: float
    transport_relative_humidity_pct: None
    transport_duration_hours: float
    transport_excursion_duration_hours: None
    handling_severity: HandlingSeverity
    net_pack_quantity: float
    net_pack_quantity_unit: str
    produce_route_status: str
    route_source_id: str | None
    route_approval_id: str | None
    mechanism_status: tuple[tuple[ProtectionMechanism, str], ...]
    transfer_budgets: tuple[TransferBudget, ...]
    applied_assessments: tuple[AppliedAssessment, ...]
    gaps: tuple[str, ...]
    candidate_screening_allowed: bool

    def report(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "food_reference_id": self.food_reference_id,
            "scenario_fingerprint": scenario_fingerprint(self),
            "food_master_sha256": self.food_master_sha256,
            "rule_set_version": self.rule_set_version,
            "target_shelf_life_days": self.target_shelf_life_days,
            "storage_type": self.storage_type.value,
            "transport_mode": self.transport_mode,
            "exposures": [
                {
                    "phase": item.phase,
                    "temperature_c": item.temperature_c,
                    "relative_humidity_pct": item.relative_humidity_pct,
                    "duration_hours": item.duration_hours,
                    "safety_check_only": item.safety_check_only,
                }
                for item in self.exposures
            ],
            "service_temperature_min_c": self.service_temperature_min_c,
            "service_temperature_max_c": self.service_temperature_max_c,
            "storage_relative_humidity_pct": self.storage_relative_humidity_pct,
            "transport_relative_humidity_pct": None,
            "transport_duration_hours": self.transport_duration_hours,
            "transport_excursion_duration_hours": None,
            "handling_severity": self.handling_severity.value,
            "net_pack_quantity": self.net_pack_quantity,
            "net_pack_quantity_unit": self.net_pack_quantity_unit,
            "produce_route_status": self.produce_route_status,
            "route_source_id": self.route_source_id,
            "route_approval_id": self.route_approval_id,
            "mechanism_status": {key.value: value for key, value in self.mechanism_status},
            "transfer_budgets": [
                {
                    "mechanism": budget.mechanism.value,
                    "max_cumulative_transfer": budget.max_cumulative_transfer,
                    "unit": budget.unit,
                    "target_average_transfer_per_day": budget.target_average_transfer_per_day,
                    "source_id": budget.source_id,
                    "approval_id": budget.approval_id,
                }
                for budget in self.transfer_budgets
            ],
            "applied_assessments": [
                {
                    "mechanism": item.mechanism.value,
                    "decision": item.decision.value,
                    "source_id": item.source_id,
                    "source_locator": item.source_locator,
                    "approval_id": item.approval_id,
                    "evidence_basis": item.evidence_basis.value,
                }
                for item in self.applied_assessments
            ],
            "gaps": list(self.gaps),
            "candidate_screening_allowed": self.candidate_screening_allowed,
            "otr_target": None,
            "wvtr_target": None,
        }


def scenario_fingerprint(card: RequirementCard) -> str:
    """Hash scenario facts so later evidence cannot be reused for a changed route."""
    fields = {
        "record_id": card.record_id,
        "food_reference_id": card.food_reference_id,
        "target_shelf_life_days": card.target_shelf_life_days,
        "storage_type": card.storage_type.value,
        "transport_mode": card.transport_mode,
        "transport_duration_hours": card.transport_duration_hours,
        "handling_severity": card.handling_severity.value,
        "net_pack_quantity": card.net_pack_quantity,
        "net_pack_quantity_unit": card.net_pack_quantity_unit,
        "exposures": [
            (item.phase, item.temperature_c, item.relative_humidity_pct,
             item.duration_hours, item.safety_check_only)
            for item in card.exposures
        ],
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _positive(value: object) -> bool:
    return _number(value) and value > 0


def _applicability_gap(assessment: ProtectionAssessment, enriched: EnrichedScenario) -> str | None:
    scenario = enriched.scenario
    if assessment.pack_quantity_unit != scenario.net_pack_quantity_unit or not isclose(
        assessment.pack_quantity, scenario.net_pack_quantity, rel_tol=1e-9, abs_tol=1e-9,
    ):
        return "pack_quantity_out_of_scope"
    temperatures = [exposure.temperature_c for exposure in enriched.exposures]
    if (
        min(temperatures) < assessment.valid_temperature_min_c
        or max(temperatures) > assessment.valid_temperature_max_c
    ):
        return "temperature_out_of_scope"
    if not (
        assessment.valid_rh_min_pct
        <= scenario.storage_relative_humidity_pct
        <= assessment.valid_rh_max_pct
    ):
        return "storage_humidity_out_of_scope"
    # Transit RH is not supplied. A narrower source range cannot be claimed
    # to cover it. A 0..100% finding must itself have been source-reviewed.
    if assessment.valid_rh_min_pct > 0 or assessment.valid_rh_max_pct < 100:
        return "transport_humidity_unknown"
    return None


def derive_requirement_card(
    enriched: EnrichedScenario,
    assessments: tuple[ProtectionAssessment, ...] = (),
) -> RequirementCard:
    """Derive a condition-aware card; unknown mechanisms stay unknown."""
    scenario = enriched.scenario
    by_mechanism: dict[ProtectionMechanism, ProtectionAssessment] = {}
    for assessment in assessments:
        if assessment.food_reference_id != enriched.food_reference.food_id:
            continue
        if assessment.mechanism in by_mechanism:
            raise ValueError("multiple assessments for one food and mechanism")
        by_mechanism[assessment.mechanism] = assessment

    statuses: list[tuple[ProtectionMechanism, str]] = []
    budgets: list[TransferBudget] = []
    applied: list[AppliedAssessment] = []
    gaps: list[str] = []
    for mechanism in ProtectionMechanism:
        assessment = by_mechanism.get(mechanism)
        if assessment is None:
            statuses.append((mechanism, "unassessed"))
            gaps.append(f"{mechanism.value}_unassessed")
            continue
        gap = _applicability_gap(assessment, enriched)
        if gap is not None:
            statuses.append((mechanism, "out_of_scope"))
            gaps.append(f"{mechanism.value}_{gap}")
            continue
        applied.append(AppliedAssessment(
            mechanism, assessment.decision, assessment.source_id,
            assessment.source_locator, assessment.approval_id, assessment.evidence_basis,
        ))
        if assessment.decision is AssessmentDecision.NOT_REQUIRED:
            statuses.append((mechanism, "source_assessed_not_required"))
        else:
            statuses.append((mechanism, "source_limit"))
            budgets.append(TransferBudget(
                mechanism, assessment.max_cumulative_transfer, assessment.transfer_unit,
                assessment.max_cumulative_transfer / scenario.desired_shelf_life_days,
                assessment.source_id, assessment.approval_id,
            ))

    if enriched.produce_route_status == "unclassified":
        gaps.append("respiration_route_unclassified")
    elif enriched.produce_route_status in ("respiration_evidence_present", "confirmed_respiring"):
        gaps.append("produce_gas_balance_pending_stop_4")
    elif enriched.produce_route_status == "confirmed_non_respiring":
        pass
    else:
        raise ValueError("unknown produce route status")
    gaps.extend((
        "light_sensitivity_unassessed", "seal_integrity_pending_structure",
        "mechanical_verification_pending_structure", "food_contact_pending_structure",
    ))
    temperatures = [exposure.temperature_c for exposure in enriched.exposures]
    return RequirementCard(
        scenario.record_id, enriched.food_reference.food_id,
        enriched.food_master_sha256, RULE_SET_VERSION,
        scenario.desired_shelf_life_days, scenario.storage_type,
        scenario.transport_mode, enriched.exposures,
        min(temperatures), max(temperatures),
        scenario.storage_relative_humidity_pct, None,
        scenario.transport_duration_hours, None,
        scenario.transport_handling_severity, scenario.net_pack_quantity,
        scenario.net_pack_quantity_unit, enriched.produce_route_status,
        enriched.route_source_id, enriched.route_approval_id,
        tuple(statuses), tuple(budgets), tuple(applied), tuple(gaps), False,
    )


def load_protection_assessments(path: Path) -> tuple[ProtectionAssessment, ...]:
    """Read an explicitly reviewed JSON register; never auto-fill a limit."""
    return _parse_protection_assessments(path.read_bytes())


def _parse_protection_assessments(raw: bytes) -> tuple[ProtectionAssessment, ...]:
    payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "assessments"}:
        raise ValueError("assessment register needs schema_version and assessments only")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or not isinstance(payload["assessments"], list)
    ):
        raise ValueError("unsupported assessment register schema")
    fields = set(ProtectionAssessment.__dataclass_fields__)
    assessments = []
    seen = set()
    for index, item in enumerate(payload["assessments"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"assessment {index} has missing or unexpected fields")
        try:
            parsed = ProtectionAssessment(
                **{
                    **item,
                    "mechanism": ProtectionMechanism(item["mechanism"]),
                    "decision": AssessmentDecision(item["decision"]),
                    "evidence_basis": EvidenceBasis(item["evidence_basis"]),
                }
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"assessment {index}: {exc}") from exc
        key = (parsed.food_reference_id, parsed.mechanism)
        if key in seen:
            raise ValueError(f"assessment {index}: duplicate food/mechanism")
        seen.add(key)
        assessments.append(parsed)
    return tuple(assessments)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build condition-aware food requirement cards")
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("food_master", type=Path)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--route-register", type=Path, help="reviewed exact-food route JSON")
    parser.add_argument("--assessments", type=Path, help="reviewed source-assessment JSON")
    parser.add_argument("--report", type=Path, help="new JSON report path")
    args = parser.parse_args()
    try:
        scenario_audit = audit_scenarios(args.scenarios, sheet_name=args.scenario_sheet)
        food_audit = load_food_references(args.food_master, sheet_name=args.food_sheet)
        raw_routes = args.route_register.read_bytes() if args.route_register else None
        routes = parse_route_register(raw_routes) if raw_routes is not None else ()
        route_sha256 = hashlib.sha256(raw_routes).hexdigest() if raw_routes is not None else None
        raw_assessments = args.assessments.read_bytes() if args.assessments else None
        assessments = (
            _parse_protection_assessments(raw_assessments)
            if raw_assessments is not None else ()
        )
        assessment_sha256 = (
            hashlib.sha256(raw_assessments).hexdigest()
            if raw_assessments is not None else None
        )
    except (InputSchemaError, OSError, csv.Error, BadZipFile, ValueError, UnicodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    enrichment = enrich_scenarios(scenario_audit, food_audit, routes, route_sha256)
    rows = []
    for row in enrichment.rows:
        rows.append({
            "row_number": row.row_number,
            "record_id": row.record_id,
            "status": "requirement_card" if row.enriched else "exception",
            "issues": [
                {"field": issue.field, "code": issue.code, "message": issue.message}
                for issue in row.issues
            ],
            "card": derive_requirement_card(row.enriched, assessments).report()
            if row.enriched else None,
        })
    report = {
        "rule_set_version": RULE_SET_VERSION,
        "scenario_sha256": enrichment.scenario_sha256,
        "food_master_sha256": enrichment.food_master_sha256,
        "route_register_sha256": route_sha256,
        "assessment_register_sha256": assessment_sha256,
        "assessment_count": len(assessments),
        "total_rows": len(rows),
        "exception_rows": sum(row["status"] == "exception" for row in rows),
        "rows": rows,
    }
    if args.report:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except FileExistsError:
            parser.exit(2, "report error: output already exists; choose a new path\n")
        except OSError as exc:
            parser.exit(2, f"report error: {exc}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if not report["exception_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
