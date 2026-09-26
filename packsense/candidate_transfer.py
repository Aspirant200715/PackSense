"""Stop 5 building block: compare sourced whole-package transfer with food budgets.

This check is not package feasibility. It cannot approve a structure, infer
OTR/WVTR from a grade, or predict shelf life. In particular, a within-budget
result leaves food contact, sealing, mechanics, light, and (for produce) the
time-dependent gas/water safety checks unresolved.
"""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from math import isclose, isfinite
from typing import Any

from packsense.contracts import EvidenceBasis
from packsense.requirements import (
    ProtectionMechanism, RequirementCard, TRANSFER_UNITS, scenario_fingerprint,
)


TRANSFER_CHECK_VERSION = "candidate-transfer-v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MISSING = frozenset({"", "unknown", "not_reported", "n/a", "na", "tbd"})


class TransferDecision(StrEnum):
    WITHIN_BUDGET = "within_budget"
    EXCEEDS_BUDGET = "exceeds_budget"
    NOT_REQUIRED = "source_assessed_not_required"
    UNRESOLVED = "unresolved"


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or value.strip().casefold() in _MISSING:
        raise ValueError(f"{name} must be non-empty source text")


@dataclass(frozen=True, slots=True)
class FinishedPackageTransferEvidence:
    """A reviewed cumulative transfer for one exact food/package scenario.

    The source and approval identifiers document an external evidence review;
    this class cannot verify the authenticity of that review.
    """

    record_id: str
    food_reference_id: str
    structure_id: str
    structure_catalogue_sha256: str
    scenario_fingerprint: str
    mechanism: ProtectionMechanism
    cumulative_transfer: float
    transfer_unit: str
    target_days: float
    pack_quantity: float
    pack_quantity_unit: str
    valid_temperature_min_c: float
    valid_temperature_max_c: float
    valid_rh_min_pct: float
    valid_rh_max_pct: float
    source_id: str
    source_locator: str
    approval_id: str
    evidence_basis: EvidenceBasis
    correction_model_id: str | None
    correction_model_version: str | None

    def __post_init__(self) -> None:
        for name in (
            "record_id", "food_reference_id", "structure_id", "source_id",
            "source_locator", "approval_id",
        ):
            _text(getattr(self, name), name)
        if not isinstance(self.scenario_fingerprint, str) or not _HASH.fullmatch(
            self.scenario_fingerprint
        ):
            raise ValueError("scenario_fingerprint must be a lowercase SHA-256")
        if not isinstance(self.structure_catalogue_sha256, str) or not _HASH.fullmatch(
            self.structure_catalogue_sha256
        ):
            raise ValueError("structure_catalogue_sha256 must be a lowercase SHA-256")
        if not isinstance(self.mechanism, ProtectionMechanism):
            raise ValueError("mechanism must be a ProtectionMechanism")
        if self.transfer_unit != TRANSFER_UNITS[self.mechanism]:
            raise ValueError("transfer_unit does not match the mechanism")
        if not isinstance(self.evidence_basis, EvidenceBasis) or self.evidence_basis not in (
            EvidenceBasis.MEASURED, EvidenceBasis.VALIDATED_CORRECTION,
        ):
            raise ValueError("transfer requires measured or validated-correction evidence")
        if self.evidence_basis is EvidenceBasis.VALIDATED_CORRECTION:
            _text(self.correction_model_id, "correction_model_id")
            _text(self.correction_model_version, "correction_model_version")
        elif self.correction_model_id is not None or self.correction_model_version is not None:
            raise ValueError("measured transfer must not carry a correction model")
        for name in ("cumulative_transfer", "target_days", "pack_quantity"):
            value = getattr(self, name)
            if not _finite(value) or value < 0 or (name != "cumulative_transfer" and value == 0):
                raise ValueError(f"{name} must be finite and nonnegative (positive for scope)")
        if self.pack_quantity_unit not in ("g", "mL"):
            raise ValueError("pack_quantity_unit must be canonical g or mL")
        for low_name, high_name in (
            ("valid_temperature_min_c", "valid_temperature_max_c"),
            ("valid_rh_min_pct", "valid_rh_max_pct"),
        ):
            low, high = getattr(self, low_name), getattr(self, high_name)
            if not _finite(low) or not _finite(high) or low > high:
                raise ValueError(f"{low_name}/{high_name} must be finite ordered bounds")
        if self.valid_temperature_min_c < -273.15:
            raise ValueError("validated temperature is below absolute zero")
        if not (0 <= self.valid_rh_min_pct <= self.valid_rh_max_pct <= 100):
            raise ValueError("validated RH bounds must be within 0..100 percent")


@dataclass(frozen=True, slots=True)
class TransferCheck:
    record_id: str
    food_reference_id: str
    structure_id: str
    structure_catalogue_sha256: str
    scenario_fingerprint: str
    mechanism: ProtectionMechanism
    decision: TransferDecision
    observed_cumulative_transfer: float | None
    maximum_cumulative_transfer: float | None
    transfer_unit: str | None
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def report(self) -> dict[str, Any]:
        return {
            "transfer_check_version": TRANSFER_CHECK_VERSION,
            "record_id": self.record_id,
            "food_reference_id": self.food_reference_id,
            "structure_id": self.structure_id,
            "structure_catalogue_sha256": self.structure_catalogue_sha256,
            "scenario_fingerprint": self.scenario_fingerprint,
            "mechanism": self.mechanism.value,
            "decision": self.decision.value,
            "observed_cumulative_transfer": self.observed_cumulative_transfer,
            "maximum_cumulative_transfer": self.maximum_cumulative_transfer,
            "transfer_unit": self.transfer_unit,
            "reason_codes": list(self.reason_codes),
            "evidence_ids": list(self.evidence_ids),
            "package_feasible": False,
            "shelf_life_predicted": False,
        }


def check_transfer_budget(
    card: RequirementCard,
    structure_id: str,
    mechanism: ProtectionMechanism,
    evidence: FinishedPackageTransferEvidence | None = None,
    *, structure_catalogue_sha256: str,
) -> TransferCheck:
    """Compare exact-scope whole-package transfer; never approve a candidate."""
    _text(structure_id, "structure_id")
    if not isinstance(structure_catalogue_sha256, str) or not _HASH.fullmatch(
        structure_catalogue_sha256
    ):
        raise ValueError("structure_catalogue_sha256 must be a lowercase SHA-256")
    if not isinstance(mechanism, ProtectionMechanism):
        raise ValueError("mechanism must be a ProtectionMechanism")

    def result(
        decision: TransferDecision, observed: float | None, maximum: float | None,
        unit: str | None, reasons: tuple[str, ...], ids: tuple[str, ...] = (),
    ) -> TransferCheck:
        return TransferCheck(card.record_id, card.food_reference_id, structure_id,
                             structure_catalogue_sha256, scenario_fingerprint(card),
                             mechanism, decision,
                             observed, maximum, unit, reasons, ids)

    statuses = dict(card.mechanism_status)
    status = statuses.get(mechanism)
    if status not in ("source_limit", "source_assessed_not_required"):
        return result(TransferDecision.UNRESOLVED, None, None, None,
                      (f"food_requirement_{status or 'missing'}",))
    if status == "source_assessed_not_required":
        assessment = next((item for item in card.applied_assessments
                           if item.mechanism is mechanism), None)
        if assessment is None:
            return result(TransferDecision.UNRESOLVED, None, None, None,
                          ("food_assessment_missing",))
        return result(TransferDecision.NOT_REQUIRED, None, None, None, (),
                      (assessment.source_id, assessment.approval_id))

    budget = next((item for item in card.transfer_budgets
                   if item.mechanism is mechanism), None)
    if budget is None:
        return result(TransferDecision.UNRESOLVED, None, None, None,
                      ("food_transfer_budget_missing",))
    if evidence is None:
        return result(TransferDecision.UNRESOLVED, None,
                      budget.max_cumulative_transfer, budget.unit,
                      ("finished_package_transfer_missing",),
                      (budget.source_id, budget.approval_id))
    gaps = []
    if (evidence.record_id != card.record_id
            or evidence.food_reference_id != card.food_reference_id
            or evidence.structure_id != structure_id
            or evidence.structure_catalogue_sha256 != structure_catalogue_sha256
            or evidence.mechanism is not mechanism
            or evidence.scenario_fingerprint != scenario_fingerprint(card)):
        gaps.append("scenario_food_structure_or_mechanism_mismatch")
    if (evidence.transfer_unit != budget.unit
            or evidence.pack_quantity_unit != card.net_pack_quantity_unit
            or not isclose(evidence.pack_quantity, card.net_pack_quantity,
                           rel_tol=0, abs_tol=1e-9)
            or not isclose(evidence.target_days, card.target_shelf_life_days,
                           rel_tol=0, abs_tol=1e-9)):
        gaps.append("unit_quantity_or_target_days_mismatch")
    if (evidence.valid_temperature_min_c > card.service_temperature_min_c
            or evidence.valid_temperature_max_c < card.service_temperature_max_c):
        gaps.append("temperature_out_of_scope")
    # Transit RH is unknown in the scenario. Only an explicitly reviewed
    # full-RH finding can cover that exposure without inventing a value.
    if evidence.valid_rh_min_pct != 0 or evidence.valid_rh_max_pct != 100:
        gaps.append("transport_humidity_unknown")
    if gaps:
        return result(TransferDecision.UNRESOLVED, None,
                      budget.max_cumulative_transfer, budget.unit, tuple(gaps),
                      (budget.source_id, budget.approval_id))
    decision = (TransferDecision.WITHIN_BUDGET if evidence.cumulative_transfer
                <= budget.max_cumulative_transfer else TransferDecision.EXCEEDS_BUDGET)
    ids = (budget.source_id, budget.approval_id, evidence.source_id, evidence.approval_id)
    if evidence.correction_model_id is not None:
        ids += (evidence.correction_model_id, evidence.correction_model_version)
    return result(decision, evidence.cumulative_transfer, budget.max_cumulative_transfer,
                  budget.unit, (), ids)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def parse_transfer_register(raw: bytes) -> tuple[FinishedPackageTransferEvidence, ...]:
    """Parse a separately reviewed register; duplicate claims are an error."""
    payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "observations"}:
        raise ValueError("transfer register needs schema_version and observations only")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported transfer-register schema")
    if not isinstance(payload["observations"], list):
        raise ValueError("observations must be an array")
    fields = set(FinishedPackageTransferEvidence.__dataclass_fields__)
    accepted = []
    seen = set()
    for index, item in enumerate(payload["observations"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"observation {index}: missing or unexpected fields")
        try:
            observation = FinishedPackageTransferEvidence(**{
                **item,
                "mechanism": ProtectionMechanism(item["mechanism"]),
                "evidence_basis": EvidenceBasis(item["evidence_basis"]),
            })
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observation {index}: {exc}") from exc
        key = (observation.record_id, observation.structure_id,
               observation.structure_catalogue_sha256, observation.mechanism,
               observation.scenario_fingerprint)
        if key in seen:
            raise ValueError(f"observation {index}: duplicate scenario/structure/mechanism")
        seen.add(key)
        accepted.append(observation)
    return tuple(accepted)
