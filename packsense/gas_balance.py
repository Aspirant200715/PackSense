"""Stop 4: local O2/CO2 inventory balance at source-observed conditions.

This is a necessary diagnostic, not a dynamic MAP safety simulation. Film or
perforation transfer must be measured for the *finished package* and initial
gas conditions. A local flux cannot establish a safe trajectory or shelf life.
"""

import json
import re
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario
from packsense.respiration import KineticEvidence, correct_rate, project_source_rate


GAS_BALANCE_VERSION = "local-gas-inventory-v1"
# Molecular masses are physical unit-conversion constants, not fitted data.
O2_MOLAR_MASS_G_MOL = 31.9988
CO2_MOLAR_MASS_G_MOL = 44.0095
PHASES = frozenset({"storage", "transport", "transport_max_excursion"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _positive(value: object) -> bool:
    return _finite(value) and value > 0


@dataclass(frozen=True, slots=True)
class FinishedPackageGasObservation:
    """One reviewed package/food gas-transfer observation at exact conditions.

    Transfer is signed into the headspace; a negative CO2 value is egress.
    The observed rates already include any perforations or closures. They
    cannot be borrowed for a different gas mixture or temperature.
    """

    record_id: str
    food_reference_id: str
    structure_id: str
    phase: str
    temperature_c: float
    fill_mass_g: float
    headspace_mmol: float
    initial_o2_pct: float
    initial_co2_pct: float
    external_o2_pct: float
    external_co2_pct: float
    o2_transfer_mmol_h: float
    co2_transfer_mmol_h: float
    min_o2_pct: float
    max_co2_pct: float
    transfer_source_id: str
    gas_limit_source_id: str
    structure_approval_id: str
    source_locator: str
    approval_id: str
    transfer_basis: EvidenceBasis
    gas_limit_basis: EvidenceBasis
    structure_catalogue_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "record_id", "food_reference_id", "structure_id", "transfer_source_id",
            "gas_limit_source_id", "structure_approval_id", "source_locator",
            "approval_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")
        if self.structure_catalogue_sha256 is not None and (
            not isinstance(self.structure_catalogue_sha256, str)
            or not _HASH.fullmatch(self.structure_catalogue_sha256)
        ):
            raise ValueError("structure_catalogue_sha256 must be a lowercase SHA-256")
        if self.phase not in PHASES:
            raise ValueError("phase is not a known exposure")
        if not isinstance(self.transfer_basis, EvidenceBasis) or self.transfer_basis not in (
            EvidenceBasis.MEASURED, EvidenceBasis.VALIDATED_CORRECTION,
        ):
            raise ValueError("package transfer needs measured or validated evidence")
        if self.gas_limit_basis is not EvidenceBasis.MEASURED:
            raise ValueError("food gas limits need measured evidence")
        for name in ("fill_mass_g", "headspace_mmol"):
            if not _positive(getattr(self, name)):
                raise ValueError(f"{name} must be finite and positive")
        if not _finite(self.temperature_c) or self.temperature_c < -273.15:
            raise ValueError("temperature must be physical and finite")
        for name in ("o2_transfer_mmol_h", "co2_transfer_mmol_h"):
            if not _finite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        for prefix in ("initial", "external"):
            o2 = getattr(self, f"{prefix}_o2_pct")
            co2 = getattr(self, f"{prefix}_co2_pct")
            if not _finite(o2) or not _finite(co2) or not (
                0 <= o2 <= 100 and 0 <= co2 <= 100 and o2 + co2 <= 100
            ):
                raise ValueError(f"{prefix} gas percentages must be physical")
        if not _finite(self.min_o2_pct) or not 0 <= self.min_o2_pct <= 100:
            raise ValueError("min_o2_pct must be physical")
        if not _finite(self.max_co2_pct) or not 0 <= self.max_co2_pct <= 100:
            raise ValueError("max_co2_pct must be physical")


@dataclass(frozen=True, slots=True)
class GasBalanceResult:
    phase: str
    temperature_c: float
    status: str
    o2_inventory_mmol: float | None
    co2_inventory_mmol: float | None
    o2_net_mmol_h: float | None
    co2_net_mmol_h: float | None
    warning_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    record_id: str | None = None
    structure_id: str | None = None

    def report(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "record_id": self.record_id,
            "structure_id": self.structure_id,
            "temperature_c": self.temperature_c,
            "status": self.status,
            "o2_inventory_mmol": self.o2_inventory_mmol,
            "co2_inventory_mmol": self.co2_inventory_mmol,
            "o2_net_mmol_h": self.o2_net_mmol_h,
            "co2_net_mmol_h": self.co2_net_mmol_h,
            "warning_codes": list(self.warning_codes),
            "evidence_ids": list(self.evidence_ids),
            "gas_safety_certified": False,
            "shelf_life_predicted": False,
        }


def _unresolved(
    phase: str, temperature_c: float, code: str,
    record_id: str | None = None, structure_id: str | None = None,
) -> GasBalanceResult:
    return GasBalanceResult(
        phase, temperature_c, "unresolved", None, None, None, None,
        (code,), (), record_id, structure_id,
    )


def calculate_local_balance(
    enriched: EnrichedScenario,
    observation: FinishedPackageGasObservation,
    oxygen_rate: KineticEvidence,
    carbon_dioxide_rate: KineticEvidence,
) -> GasBalanceResult:
    """Calculate species inventories/fluxes at an exact observed state only."""
    phase = observation.phase
    temp = observation.temperature_c
    def block(code: str) -> GasBalanceResult:
        return _unresolved(phase, temp, code, observation.record_id, observation.structure_id)
    if enriched.produce_route_status != "confirmed_respiring":
        return block("route_not_confirmed_respiring")
    if observation.record_id != enriched.scenario.record_id:
        return block("scenario_record_mismatch")
    if observation.food_reference_id != enriched.food_reference.food_id or (
        oxygen_rate.food_reference_id != observation.food_reference_id
        or carbon_dioxide_rate.food_reference_id != observation.food_reference_id
    ):
        return block("food_id_mismatch")
    if oxygen_rate.rate_unit != "mg O2/kg/h" or carbon_dioxide_rate.rate_unit != "mg CO2/kg/h":
        return block("separate_o2_co2_measurements_required")
    scenario = enriched.scenario
    selected = (
        oxygen_rate if scenario.respiration_rate_unit == "mg O2/kg/h" else
        carbon_dioxide_rate if scenario.respiration_rate_unit == "mg CO2/kg/h" else None
    )
    if selected is None:
        return block("scenario_respiration_species_missing")
    selected_value, selected_status = correct_rate(
        enriched, selected, temp, observation.initial_o2_pct, observation.initial_co2_pct,
    )
    if selected_value is None:
        return block(f"scenario_rate_out_of_scope:{selected_status}")
    if scenario.net_pack_quantity_unit != "g" or not isclose(
        scenario.net_pack_quantity, observation.fill_mass_g, rel_tol=1e-9, abs_tol=1e-9,
    ):
        return block("fill_mass_mismatch_or_volume_only")
    matching = [item for item in enriched.exposures if item.phase == phase]
    if len(matching) != 1 or not isclose(matching[0].temperature_c, temp, rel_tol=0, abs_tol=1e-6):
        return block("exposure_temperature_mismatch")
    o2, o2_status = project_source_rate(
        oxygen_rate, temp, observation.initial_o2_pct, observation.initial_co2_pct,
    )
    co2, co2_status = project_source_rate(
        carbon_dioxide_rate, temp, observation.initial_o2_pct, observation.initial_co2_pct,
    )
    if o2 is None or co2 is None:
        return block(f"respiration_out_of_scope:{o2_status}:{co2_status}")
    mass_kg = observation.fill_mass_g / 1000
    o2_consumption_mmol_h = o2 / O2_MOLAR_MASS_G_MOL * mass_kg
    co2_production_mmol_h = co2 / CO2_MOLAR_MASS_G_MOL * mass_kg
    o2_net = observation.o2_transfer_mmol_h - o2_consumption_mmol_h
    co2_net = observation.co2_transfer_mmol_h + co2_production_mmol_h
    warnings = []
    if observation.initial_o2_pct < observation.min_o2_pct:
        warnings.append("initial_o2_below_limit")
    if observation.initial_co2_pct > observation.max_co2_pct:
        warnings.append("initial_co2_above_limit")
    if observation.initial_o2_pct <= observation.min_o2_pct and o2_net < 0:
        warnings.append("o2_inventory_depleting_at_limit")
    if observation.initial_co2_pct >= observation.max_co2_pct and co2_net > 0:
        warnings.append("co2_inventory_rising_at_limit")
    status = "initial_limit_violation" if any(
        warning in ("initial_o2_below_limit", "initial_co2_above_limit") for warning in warnings
    ) else "local_balance_only"
    return GasBalanceResult(
        phase, temp, status,
        observation.headspace_mmol * observation.initial_o2_pct / 100,
        observation.headspace_mmol * observation.initial_co2_pct / 100,
        o2_net, co2_net, tuple(warnings),
        (oxygen_rate.rate_source_id, carbon_dioxide_rate.rate_source_id,
         observation.transfer_source_id, observation.gas_limit_source_id,
         observation.structure_approval_id, observation.approval_id),
        observation.record_id, observation.structure_id,
    )


def audit_gas_profile(
    enriched: EnrichedScenario,
    observations: tuple[FinishedPackageGasObservation, ...],
    oxygen_rate: KineticEvidence,
    carbon_dioxide_rate: KineticEvidence,
    *, structure_id: str,
) -> tuple[GasBalanceResult, ...]:
    """Demand a separate finished-package observation for every exposure."""
    if not isinstance(structure_id, str) or not structure_id.strip():
        raise ValueError("structure_id must be non-empty")
    by_phase = {}
    for observation in observations:
        if observation.structure_id != structure_id:
            raise ValueError("gas profile mixes structure IDs")
        if observation.phase in by_phase:
            raise ValueError("duplicate gas observation phase")
        by_phase[observation.phase] = observation
    return tuple(
        calculate_local_balance(enriched, by_phase[exposure.phase], oxygen_rate, carbon_dioxide_rate)
        if exposure.phase in by_phase
        else _unresolved(
            exposure.phase, exposure.temperature_c, "package_gas_observation_missing",
            enriched.scenario.record_id, structure_id,
        )
        for exposure in enriched.exposures
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_gas_observations(raw: bytes) -> tuple[FinishedPackageGasObservation, ...]:
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "observations"}:
        raise ValueError("gas register needs schema_version and observations only")
    if type(payload["schema_version"]) is not int or payload["schema_version"] not in (1, 2):
        raise ValueError("unsupported gas-register schema")
    if not isinstance(payload["observations"], list):
        raise ValueError("observations must be an array")
    fields = set(FinishedPackageGasObservation.__dataclass_fields__)
    if payload["schema_version"] == 1:
        fields.remove("structure_catalogue_sha256")
    accepted = []
    seen = set()
    for index, item in enumerate(payload["observations"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"observation {index}: missing or unexpected fields")
        if payload["schema_version"] == 2 and item["structure_catalogue_sha256"] is None:
            raise ValueError(f"observation {index}: structure catalogue hash is required")
        try:
            entry = FinishedPackageGasObservation(**{
                **item,
                "transfer_basis": EvidenceBasis(item["transfer_basis"]),
                "gas_limit_basis": EvidenceBasis(item["gas_limit_basis"]),
            })
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observation {index}: {exc}") from exc
        key = (entry.record_id, entry.structure_id, entry.phase)
        if key in seen:
            raise ValueError(f"observation {index}: duplicate record/structure/phase")
        seen.add(key)
        accepted.append(entry)
    return tuple(accepted)
