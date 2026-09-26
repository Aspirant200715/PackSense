"""Stop 4: local produce-water ledger and measured dew-point warning.

These exact-condition observations cannot be integrated across an unknown
storage or excursion duration. A local balance or dew-point comparison is not
proof of product mass loss, condensation amount, or package safety.
"""

import json
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any

from packsense.contracts import EvidenceBasis
from packsense.enrichment import EnrichedScenario
from packsense.gas_balance import GasBalanceResult, PHASES


WATER_BALANCE_VERSION = "local-water-balance-v1"


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _nonnegative(value: object) -> bool:
    return _finite(value) and value >= 0


@dataclass(frozen=True, slots=True)
class FinishedPackageWaterObservation:
    """One reviewed water observation for a whole finished package."""

    record_id: str
    food_reference_id: str
    structure_id: str
    phase: str
    temperature_c: float
    fill_mass_g: float
    produce_transpiration_g_h: float
    respiratory_water_g_h: float
    package_water_transfer_g_h: float
    sorbent_present: bool
    sorbent_uptake_g_h: float
    initial_headspace_water_g: float
    external_relative_humidity_pct: float
    headspace_dew_point_c: float
    coldest_internal_surface_c: float
    transpiration_source_id: str
    respiratory_water_source_id: str
    package_transfer_source_id: str
    headspace_source_id: str
    source_locator: str
    approval_id: str
    evidence_basis: EvidenceBasis

    def __post_init__(self) -> None:
        for name in (
            "record_id", "food_reference_id", "structure_id", "transpiration_source_id",
            "respiratory_water_source_id", "package_transfer_source_id",
            "headspace_source_id", "source_locator", "approval_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")
        if self.phase not in PHASES:
            raise ValueError("phase is not a known exposure")
        if self.evidence_basis is not EvidenceBasis.MEASURED:
            raise ValueError("this water-observation contract requires measured evidence")
        if not isinstance(self.sorbent_present, bool):
            raise ValueError("sorbent_present must be boolean")
        for name in (
            "fill_mass_g", "produce_transpiration_g_h", "respiratory_water_g_h",
            "sorbent_uptake_g_h", "initial_headspace_water_g",
        ):
            if not _nonnegative(getattr(self, name)):
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.fill_mass_g == 0:
            raise ValueError("fill_mass_g must be positive")
        if not self.sorbent_present and self.sorbent_uptake_g_h != 0:
            raise ValueError("no sorbent cannot have a positive uptake rate")
        if not _finite(self.package_water_transfer_g_h):
            raise ValueError("package_water_transfer_g_h must be finite")
        if not _finite(self.external_relative_humidity_pct) or not (
            0 <= self.external_relative_humidity_pct <= 100
        ):
            raise ValueError("external RH must be within 0..100 percent")
        for name in ("temperature_c", "headspace_dew_point_c", "coldest_internal_surface_c"):
            value = getattr(self, name)
            if not _finite(value) or value < -273.15:
                raise ValueError(f"{name} must be physical and finite")
        if self.headspace_dew_point_c > self.temperature_c:
            raise ValueError("headspace dew point exceeds headspace temperature")


@dataclass(frozen=True, slots=True)
class WaterBalanceResult:
    record_id: str
    structure_id: str
    phase: str
    temperature_c: float
    status: str
    initial_headspace_water_g: float | None
    local_vapor_input_g_h: float | None
    surface_above_dew_point_c: float | None
    warning_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def report(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "structure_id": self.structure_id,
            "phase": self.phase,
            "temperature_c": self.temperature_c,
            "status": self.status,
            "initial_headspace_water_g": self.initial_headspace_water_g,
            "local_vapor_input_g_h": self.local_vapor_input_g_h,
            "surface_above_dew_point_c": self.surface_above_dew_point_c,
            "warning_codes": list(self.warning_codes),
            "evidence_ids": list(self.evidence_ids),
            "condensation_amount_predicted": False,
            "water_safety_certified": False,
        }


def _unresolved(
    record_id: str, structure_id: str, phase: str, temperature_c: float, code: str,
) -> WaterBalanceResult:
    return WaterBalanceResult(
        record_id, structure_id, phase, temperature_c, "unresolved",
        None, None, None, (code,), (),
    )


def calculate_local_water(
    enriched: EnrichedScenario, observation: FinishedPackageWaterObservation,
) -> WaterBalanceResult:
    """Report local vapor input and measured dew-point margin, no time forecast."""
    record_id = observation.record_id
    structure_id = observation.structure_id
    phase = observation.phase
    temp = observation.temperature_c

    def block(code: str) -> WaterBalanceResult:
        return _unresolved(record_id, structure_id, phase, temp, code)

    if enriched.produce_route_status != "confirmed_respiring":
        return block("route_not_confirmed_respiring")
    if (
        record_id != enriched.scenario.record_id
        or observation.food_reference_id != enriched.food_reference.food_id
    ):
        return block("scenario_or_food_mismatch")
    if enriched.scenario.net_pack_quantity_unit != "g" or not isclose(
        enriched.scenario.net_pack_quantity, observation.fill_mass_g,
        rel_tol=1e-9, abs_tol=1e-9,
    ):
        return block("fill_mass_mismatch_or_volume_only")
    exposures = [item for item in enriched.exposures if item.phase == phase]
    if len(exposures) != 1 or not isclose(exposures[0].temperature_c, temp, rel_tol=0, abs_tol=1e-6):
        return block("exposure_temperature_mismatch")
    if phase == "storage" and not isclose(
        observation.external_relative_humidity_pct,
        enriched.scenario.storage_relative_humidity_pct, rel_tol=0, abs_tol=1e-6,
    ):
        return block("storage_humidity_mismatch")
    vapor_input = (
        observation.produce_transpiration_g_h
        + observation.respiratory_water_g_h
        + observation.package_water_transfer_g_h
        - observation.sorbent_uptake_g_h
    )
    margin = observation.coldest_internal_surface_c - observation.headspace_dew_point_c
    warnings = []
    if margin <= 0:
        warnings.append("surface_at_or_below_measured_dew_point")
    if vapor_input > 0:
        warnings.append("local_vapor_inventory_increasing_before_condensation")
    return WaterBalanceResult(
        record_id, structure_id, phase, temp, "local_water_balance_only",
        observation.initial_headspace_water_g, vapor_input, margin,
        tuple(warnings),
        (observation.transpiration_source_id, observation.respiratory_water_source_id,
         observation.package_transfer_source_id, observation.headspace_source_id,
         observation.approval_id),
    )


def audit_water_profile(
    enriched: EnrichedScenario,
    observations: tuple[FinishedPackageWaterObservation, ...],
    structure_id: str,
) -> tuple[WaterBalanceResult, ...]:
    """Require a separate observation at each storage/transport temperature."""
    if not isinstance(structure_id, str) or not structure_id.strip():
        raise ValueError("structure_id must be non-empty")
    by_phase = {}
    for observation in observations:
        if observation.structure_id != structure_id:
            raise ValueError("water profile mixes structure IDs")
        if observation.phase in by_phase:
            raise ValueError("duplicate water observation phase")
        by_phase[observation.phase] = observation
    return tuple(
        calculate_local_water(enriched, by_phase[exposure.phase])
        if exposure.phase in by_phase
        else _unresolved(
            enriched.scenario.record_id, structure_id, exposure.phase,
            exposure.temperature_c, "package_water_observation_missing",
        )
        for exposure in enriched.exposures
    )


@dataclass(frozen=True, slots=True)
class ProduceEnvironmentResult:
    record_id: str
    structure_id: str
    phase: str
    temperature_c: float
    gas_status: str
    water_status: str
    status: str
    warning_codes: tuple[str, ...]

    def report(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "structure_id": self.structure_id,
            "phase": self.phase,
            "temperature_c": self.temperature_c,
            "gas_status": self.gas_status,
            "water_status": self.water_status,
            "status": self.status,
            "warning_codes": list(self.warning_codes),
            "produce_safety_certified": False,
            "shelf_life_predicted": False,
        }


def combine_produce_profile(
    gas_results: tuple[GasBalanceResult, ...],
    water_results: tuple[WaterBalanceResult, ...],
) -> tuple[ProduceEnvironmentResult, ...]:
    """Combine audit states only; no local result becomes safety approval."""
    gas_by_phase = {item.phase: item for item in gas_results}
    if len(gas_by_phase) != len(gas_results):
        raise ValueError("duplicate gas phases")
    water_by_phase = {item.phase: item for item in water_results}
    if len(water_by_phase) != len(water_results) or set(gas_by_phase) != set(water_by_phase):
        raise ValueError("gas and water profiles have different or duplicate phases")
    combined = []
    for phase in ("storage", "transport", "transport_max_excursion"):
        if phase not in gas_by_phase:
            raise ValueError("produce profile is missing an exposure phase")
        gas, water = gas_by_phase[phase], water_by_phase[phase]
        if (
            gas.record_id != water.record_id
            or gas.structure_id != water.structure_id
            or not isclose(gas.temperature_c, water.temperature_c, rel_tol=0, abs_tol=1e-6)
        ):
            raise ValueError(
                "gas and water records refer to different scenarios, structures, or temperatures"
            )
        warnings = gas.warning_codes + water.warning_codes
        if gas.status == "unresolved" or water.status == "unresolved":
            status = "unresolved"
        elif warnings:
            status = "local_checks_with_warnings"
        else:
            status = "local_checks_only"
        combined.append(ProduceEnvironmentResult(
            water.record_id, water.structure_id, phase, water.temperature_c, gas.status,
            water.status, status, warnings,
        ))
    return tuple(combined)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_water_observations(raw: bytes) -> tuple[FinishedPackageWaterObservation, ...]:
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "observations"}:
        raise ValueError("water register needs schema_version and observations only")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported water-register schema")
    if not isinstance(payload["observations"], list):
        raise ValueError("observations must be an array")
    fields = set(FinishedPackageWaterObservation.__dataclass_fields__)
    accepted = []
    seen = set()
    for index, item in enumerate(payload["observations"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"observation {index}: missing or unexpected fields")
        try:
            entry = FinishedPackageWaterObservation(**{
                **item, "evidence_basis": EvidenceBasis(item["evidence_basis"]),
            })
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observation {index}: {exc}") from exc
        key = (entry.record_id, entry.structure_id, entry.phase)
        if key in seen:
            raise ValueError(f"observation {index}: duplicate record/structure/phase")
        seen.add(key)
        accepted.append(entry)
    return tuple(accepted)
