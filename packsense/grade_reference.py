"""Compare sourced film-grade barriers without asserting package suitability.

Only grades tested under identical conditions for every requested property are
compared.  This is a reference-level Pareto screen, not condition-corrected
finished-package performance or a learned food-to-material recommendation.
"""

from collections import defaultdict
from math import isfinite
from typing import Any

from packsense.contracts import BarrierObservation, EvidenceBasis
from packsense.masters import MasterAudit, MaterialMasterEntry
from packsense.requirements import ProtectionMechanism, RequirementCard, scenario_fingerprint
from packsense.units import MATERIAL_RATE_UNITS


COMPARISON_VERSION = "grade-barrier-reference-v1"
_OBSERVATION_UNITS = {
    "otr": MATERIAL_RATE_UNITS["otr_cm3_m2_day"],
    "wvtr": MATERIAL_RATE_UNITS["wvtr_g_m2_day"],
}
_ACCEPTED_BASES = frozenset({EvidenceBasis.MEASURED, EvidenceBasis.SUPPLIER_REPORTED})


def _objectives(card: RequirementCard) -> tuple[str, ...]:
    mechanisms = {budget.mechanism for budget in card.transfer_budgets}
    return tuple(
        name for name, needed in (
            ("otr", ProtectionMechanism.OXYGEN_INGRESS in mechanisms),
            ("wvtr", bool(mechanisms & {
                ProtectionMechanism.MOISTURE_GAIN, ProtectionMechanism.MOISTURE_LOSS,
            })),
        ) if needed
    )


def _usable(observation: BarrierObservation | None, objective: str) -> bool:
    if observation is None or observation.basis not in _ACCEPTED_BASES:
        return False
    return (
        observation.unit == _OBSERVATION_UNITS[objective]
        and isfinite(observation.value) and observation.value > 0
        and observation.test_temperature_c is not None
        and isfinite(observation.test_temperature_c)
        and observation.test_relative_humidity_pct is not None
        and isfinite(observation.test_relative_humidity_pct)
        and 0 <= observation.test_relative_humidity_pct <= 100
        and isinstance(observation.test_method, str)
        and bool(observation.test_method.strip())
        and isinstance(observation.source_url, str)
        and bool(observation.source_url.strip())
    )


def _dominates(left: MaterialMasterEntry, right: MaterialMasterEntry,
               objectives: tuple[str, ...]) -> bool:
    values = ((getattr(left.grade, name).value, getattr(right.grade, name).value)
              for name in objectives)
    comparisons = tuple(values)
    return (all(a <= b for a, b in comparisons)
            and any(a < b for a, b in comparisons))


def _observation_report(observation: BarrierObservation) -> dict[str, Any]:
    return {
        "value": observation.value,
        "unit": observation.unit,
        "test_temperature_c": observation.test_temperature_c,
        "test_relative_humidity_pct": observation.test_relative_humidity_pct,
        "test_method": observation.test_method,
        "evidence_basis": observation.basis.value,
        "source_url": observation.source_url,
    }


def compare_grade_barriers(
    card: RequirementCard,
    materials: MasterAudit[MaterialMasterEntry],
) -> dict[str, Any]:
    """Return lab-condition Pareto fronts for source-reviewed food mechanisms.

    Lower OTR/WVTR is compared only for a mechanism with an applicable
    source-reviewed food limit.  The numerical food budget is deliberately not
    compared with a film's area rate: area, driving gradients, complete
    construction, and condition correction are absent here.
    """
    if materials.issues or not materials.entries:
        raise ValueError("material master needs accepted rows without issues")
    ids = [entry.grade.material_id for entry in materials.entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate material IDs in comparison input")

    objectives = _objectives(card) if card.candidate_screening_allowed else ()
    reasons = []
    if card.produce_route_status != "confirmed_non_respiring":
        reasons.append("non_respiring_route_not_confirmed")
    if not card.candidate_screening_allowed:
        reasons.append("food_protection_assessments_incomplete")
    elif not objectives:
        reasons.append("no_source_limited_barrier_objective")

    base: dict[str, Any] = {
        "comparison_version": COMPARISON_VERSION,
        "record_id": card.record_id,
        "food_reference_id": card.food_reference_id,
        "food_master_sha256": card.food_master_sha256,
        "scenario_fingerprint": scenario_fingerprint(card),
        "material_master_sha256": materials.source_sha256,
        "status": "not_ready",
        "reason_codes": reasons,
        "objectives": list(objectives),
        "food_limit_sources": [
            {"mechanism": budget.mechanism.value, "source_id": budget.source_id,
             "approval_id": budget.approval_id}
            for budget in card.transfer_budgets
        ],
        "reference_cohorts": [],
        "grades_missing_comparable_evidence": [],
        "grades_in_singleton_cohorts": [],
        "preferred_material_id": None,
        "scenario_condition_performance_verified": False,
        "finished_package_verified": False,
        "material_suitability_established": False,
        "model_trained": False,
        "package_feasible": False,
    }
    if reasons:
        return base

    cohorts: dict[tuple[tuple[Any, ...], ...], list[MaterialMasterEntry]] = defaultdict(list)
    for entry in materials.entries:
        observations = tuple(getattr(entry.grade, name) for name in objectives)
        if not all(_usable(obs, name) for obs, name in zip(observations, objectives)):
            base["grades_missing_comparable_evidence"].append(entry.grade.material_id)
            continue
        # Each objective keeps its *own* test conditions and method.  OTR and
        # WVTR are not silently transformed to a common scenario condition.
        key = tuple((name, obs.unit, obs.test_temperature_c,
                     obs.test_relative_humidity_pct, obs.test_method)
                    for name, obs in zip(objectives, observations))
        cohorts[key].append(entry)

    for key, entries in sorted(cohorts.items()):
        if len(entries) < 2:
            base["grades_in_singleton_cohorts"].append(entries[0].grade.material_id)
            continue
        ordered = sorted(entries, key=lambda item: item.grade.material_id)
        frontier = [entry for entry in ordered if not any(
            _dominates(other, entry, objectives)
            for other in ordered if other.grade.material_id != entry.grade.material_id
        )]
        base["reference_cohorts"].append({
            "test_conditions": [
                {"property": name, "unit": unit, "temperature_c": temperature,
                 "relative_humidity_pct": humidity, "method": method}
                for name, unit, temperature, humidity, method in key
            ],
            "compared_grade_count": len(ordered),
            "frontier_grades": [
                {
                    "material_id": entry.grade.material_id,
                    "source_row_number": entry.source_row_number,
                    "manufacturer": entry.grade.manufacturer,
                    "grade": entry.grade.grade,
                    "material_family": entry.grade.material_family,
                    "film_structure": entry.grade.film_structure,
                    "film_role": entry.grade.film_role,
                    "thickness_um": entry.grade.thickness_um,
                    "observations": {
                        name: _observation_report(getattr(entry.grade, name))
                        for name in objectives
                    },
                }
                for entry in frontier
            ],
            "dominated_grade_ids": [
                entry.grade.material_id for entry in ordered if entry not in frontier
            ],
        })
    base["grades_missing_comparable_evidence"].sort()
    base["grades_in_singleton_cohorts"].sort()
    if base["reference_cohorts"]:
        base["status"] = "reference_comparison"
        base["reason_codes"] = ["laboratory_conditions_only_no_package_suitability"]
    else:
        base["reason_codes"] = ["no_multi_grade_comparable_test_cohort"]
    return base
