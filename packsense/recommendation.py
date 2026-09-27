"""Evidence-gated preliminary package shortlist (architecture Stops 5–6).

This first recommendation slice is limited to reviewed non-respiring foods.
It filters complete, externally reviewed structures using exact food scope,
service temperature, and source-scoped whole-package transfer evidence. Any
preference is protection-margin-only; it is not package certification or a
shelf-life estimate.
"""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from math import isclose
from typing import Any, Iterable

from packsense.candidate_transfer import (
    FinishedPackageTransferEvidence,
    TransferCheck,
    TransferDecision,
    check_transfer_budget,
)
from packsense.requirements import (
    AppliedAssessment, ProtectionMechanism, RequirementCard, scenario_fingerprint,
)
from packsense.structure_review import (
    EvidenceCheck,
    ReviewAttestedStructure,
    StructureReviewAudit,
    attestation_integrity_gaps,
)


RECOMMENDATION_VERSION = "basic-recommendation-v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STRUCTURE_GAPS_RESOLVED_BY_REVIEW = frozenset({
    "seal_integrity_pending_structure",
    "mechanical_verification_pending_structure",
    "food_contact_pending_structure",
})
_NON_BLOCKING_WARNINGS = frozenset({"light_sensitivity_unassessed"})


class RecommendationStatus(StrEnum):
    NOT_READY = "not_ready"
    PRELIMINARY_SHORTLIST = "preliminary_shortlist"


class CandidateStatus(StrEnum):
    EXCLUDED = "excluded"
    UNRESOLVED = "unresolved"
    ELIGIBLE_FOR_SHORTLIST = "eligible_for_shortlist"


@dataclass(frozen=True, slots=True)
class CandidateScreen:
    structure_id: str
    pack_format: str
    status: CandidateStatus
    reason_codes: tuple[str, ...]
    transfer_checks: tuple[TransferCheck, ...]
    worst_case_budget_utilization: float | None
    protection_rank: int | None = None
    layers: tuple[tuple[str, float, str, bool], ...] = ()
    compatible_food_scope: tuple[str, ...] = ()
    service_temperature_min_c: float | None = None
    service_temperature_max_c: float | None = None
    sealant_grade_id: str | None = None
    catalogue_sha256: str | None = None
    material_master_sha256: str | None = None
    review_register_sha256: str | None = None
    review_id: str | None = None
    evidence_check_ids: tuple[str, ...] = ()
    review_evidence: tuple[EvidenceCheck, ...] = ()
    transfer_evidence: tuple[FinishedPackageTransferEvidence, ...] = ()

    def report(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "pack_format": self.pack_format,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "worst_case_budget_utilization": self.worst_case_budget_utilization,
            "protection_rank": self.protection_rank,
            "compatible_food_scope": list(self.compatible_food_scope),
            "service_temperature_min_c": self.service_temperature_min_c,
            "service_temperature_max_c": self.service_temperature_max_c,
            "layers": [
                {"grade_id": grade_id, "thickness_um": thickness,
                 "role": role, "is_food_contact": is_food_contact}
                for grade_id, thickness, role, is_food_contact in self.layers
            ],
            "sealant_grade_id": self.sealant_grade_id,
            "structure_review": {
                "catalogue_sha256": self.catalogue_sha256,
                "material_master_sha256": self.material_master_sha256,
                "review_register_sha256": self.review_register_sha256,
                "review_id": self.review_id,
                "evidence_check_ids": list(self.evidence_check_ids),
                "source_checks": [
                    {
                        "kind": item.kind,
                        "source_id": item.source_id,
                        "source_locator": item.source_locator,
                        "source_sha256": item.source_sha256,
                        "review_id": item.review_id,
                        "rights_review_id": item.rights_review_id,
                        "decision": item.decision,
                    }
                    for item in self.review_evidence
                ],
            },
            "provided_transfer_evidence": [
                {
                    "mechanism": item.mechanism.value,
                    "cumulative_transfer": item.cumulative_transfer,
                    "transfer_unit": item.transfer_unit,
                    "target_days": item.target_days,
                    "valid_temperature_min_c": item.valid_temperature_min_c,
                    "valid_temperature_max_c": item.valid_temperature_max_c,
                    "valid_rh_min_pct": item.valid_rh_min_pct,
                    "valid_rh_max_pct": item.valid_rh_max_pct,
                    "source_id": item.source_id,
                    "source_locator": item.source_locator,
                    "approval_id": item.approval_id,
                    "evidence_basis": item.evidence_basis.value,
                    "correction_model_id": item.correction_model_id,
                    "correction_model_version": item.correction_model_version,
                    "comparison_decision": next((check.decision.value
                        for check in self.transfer_checks
                        if check.mechanism is item.mechanism), None),
                }
                for item in self.transfer_evidence
            ],
            "transfer_checks": [item.report() for item in self.transfer_checks],
        }


@dataclass(frozen=True, slots=True)
class BasicRecommendation:
    record_id: str
    food_reference_id: str
    status: RecommendationStatus
    preferred_structure_id: str | None
    ranking_basis: str | None
    candidates: tuple[CandidateScreen, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    food_master_sha256: str | None = None
    scenario_fingerprint: str | None = None
    scenario_source_sha256: str | None = None
    food_requirement_evidence: tuple[AppliedAssessment, ...] = ()

    def report(self) -> dict[str, Any]:
        return {
            "recommendation_version": RECOMMENDATION_VERSION,
            "record_id": self.record_id,
            "food_reference_id": self.food_reference_id,
            "food_master_sha256": self.food_master_sha256,
            "scenario_fingerprint": self.scenario_fingerprint,
            "scenario_source_sha256": self.scenario_source_sha256,
            "status": self.status.value,
            "preliminary_preferred_structure_id": self.preferred_structure_id,
            "ranking_basis": self.ranking_basis,
            "candidates": [item.report() for item in self.candidates],
            "food_requirement_evidence": [
                {
                    "mechanism": item.mechanism.value,
                    "decision": item.decision.value,
                    "source_id": item.source_id,
                    "source_locator": item.source_locator,
                    "approval_id": item.approval_id,
                    "evidence_basis": item.evidence_basis.value,
                }
                for item in self.food_requirement_evidence
            ],
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "ranking_scope": "oxygen_and_moisture_protection_only",
            "cost_ranked": False,
            "sustainability_ranked": False,
            "review_evidence_authenticity_verified_by_code": False,
            "package_feasible": False,
            "shelf_life_predicted": False,
        }


def _scope_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _review_context(reviewed: ReviewAttestedStructure) -> dict[str, Any]:
    structure = reviewed.structure
    return {
        "layers": tuple((layer.grade_id, layer.thickness_um, layer.role,
                         layer.is_food_contact) for layer in structure.layers),
        "compatible_food_scope": structure.compatible_food_scope,
        "service_temperature_min_c": structure.service_temperature_min_c,
        "service_temperature_max_c": structure.service_temperature_max_c,
        "sealant_grade_id": structure.sealant_grade_id,
        "catalogue_sha256": reviewed.catalogue_sha256,
        "material_master_sha256": reviewed.material_master_sha256,
        "review_register_sha256": reviewed.review_register_sha256,
        "review_id": reviewed.review_id,
        "evidence_check_ids": reviewed.evidence_check_ids,
        "review_evidence": reviewed.evidence_checks,
    }


def _report_context(
    card: RequirementCard, scenario_source_sha256: str | None,
) -> dict[str, Any]:
    return {
        "food_master_sha256": card.food_master_sha256,
        "scenario_fingerprint": scenario_fingerprint(card),
        "scenario_source_sha256": scenario_source_sha256,
        "food_requirement_evidence": card.applied_assessments,
    }


def _unique_transfer_evidence(
    evidence: Iterable[FinishedPackageTransferEvidence],
) -> dict[tuple[str, str, str, ProtectionMechanism, str, str],
          FinishedPackageTransferEvidence]:
    indexed: dict[tuple[str, str, str, ProtectionMechanism, str, str],
                  FinishedPackageTransferEvidence] = {}
    for item in evidence:
        key = (item.record_id, item.food_reference_id, item.structure_id,
               item.mechanism, item.scenario_fingerprint,
               item.structure_catalogue_sha256)
        if key in indexed:
            raise ValueError("duplicate transfer evidence for one exact scenario/structure/mechanism")
        indexed[key] = item
    return indexed


def _transfer_key(
    card: RequirementCard, structure_id: str, mechanism: ProtectionMechanism,
    catalogue_sha256: str,
) -> tuple[str, str, str, ProtectionMechanism, str, str]:
    return (
        card.record_id, card.food_reference_id, structure_id, mechanism,
        scenario_fingerprint(card), catalogue_sha256,
    )


def _rank_candidates(
    candidates: tuple[CandidateScreen, ...],
) -> tuple[tuple[CandidateScreen, ...], str | None]:
    eligible = [item for item in candidates
                if item.status is CandidateStatus.ELIGIBLE_FOR_SHORTLIST]
    if not eligible or any(item.worst_case_budget_utilization is None for item in eligible):
        return candidates, None
    ordered = sorted(eligible, key=lambda item: item.worst_case_budget_utilization)
    ranks: dict[str, int] = {}
    last_score = None
    last_rank = 0
    for position, item in enumerate(ordered, start=1):
        score = item.worst_case_budget_utilization
        if last_score is None or not isclose(score, last_score, rel_tol=1e-12, abs_tol=1e-12):
            last_rank = position
            last_score = score
        ranks[item.structure_id] = last_rank
    ranked = tuple(replace(item, protection_rank=ranks.get(item.structure_id))
                   for item in candidates)
    winners = [item for item in ordered if ranks[item.structure_id] == 1]
    preferred = winners[0].structure_id if len(winners) == 1 else None
    return ranked, preferred


def screen_package_candidates(
    card: RequirementCard,
    commodity_type: str,
    structure_review: StructureReviewAudit | None,
    transfer_evidence: Iterable[FinishedPackageTransferEvidence],
    *,
    current_material_master_sha256: str,
    scenario_source_sha256: str | None = None,
) -> BasicRecommendation:
    """Return a preliminary shortlist only where each evidence gate is met.

    Food scope is an exact, case/whitespace-normalized match. The only numeric
    preference is the highest worst-case fraction of the source-approved
    oxygen/moisture transfer budgets (lower is better). Cost, sustainability,
    light protection, produce MAP, package feasibility, and shelf life are not
    inferred here.
    """
    if not isinstance(commodity_type, str) or not commodity_type.strip():
        raise ValueError("commodity_type must be non-empty text")
    if (not isinstance(current_material_master_sha256, str)
            or not _HASH.fullmatch(current_material_master_sha256)):
        raise ValueError("current_material_master_sha256 must be a lowercase SHA-256")
    if scenario_source_sha256 is not None and (
        not isinstance(scenario_source_sha256, str)
        or not _HASH.fullmatch(scenario_source_sha256)
    ):
        raise ValueError("scenario_source_sha256 must be a lowercase SHA-256")
    report_context = _report_context(card, scenario_source_sha256)
    evidence_by_key = _unique_transfer_evidence(transfer_evidence)
    warnings = tuple(sorted(
        gap for gap in card.gaps if gap in _NON_BLOCKING_WARNINGS
    )) + ("cost_and_sustainability_not_ranked",)

    if not card.candidate_screening_allowed:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), ("food_requirements_or_produce_route_incomplete",), warnings,
            **report_context,
        )
    if structure_review is None:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), ("complete_structure_review_missing",), warnings,
            **report_context,
        )
    if structure_review.status != "review_attested" or structure_review.issues:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), ("complete_structure_review_not_approved",), warnings,
            **report_context,
        )
    if not structure_review.reviewed:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), ("no_reviewed_complete_structures",), warnings,
            **report_context,
        )
    review_gaps = attestation_integrity_gaps(structure_review)
    if review_gaps:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), review_gaps, warnings,
            **report_context,
        )

    unresolved_card_gaps = tuple(sorted(
        gap for gap in card.gaps
        if gap not in _STRUCTURE_GAPS_RESOLVED_BY_REVIEW
        and gap not in _NON_BLOCKING_WARNINGS
    ))
    if unresolved_card_gaps:
        return BasicRecommendation(
            card.record_id, card.food_reference_id, RecommendationStatus.NOT_READY,
            None, None, (), unresolved_card_gaps, warnings,
            **report_context,
        )

    candidates: list[CandidateScreen] = []
    for reviewed in structure_review.reviewed:
        structure = reviewed.structure
        reasons: list[str] = []
        checks: list[TransferCheck] = []
        if reviewed.material_master_sha256 != current_material_master_sha256:
            candidates.append(CandidateScreen(
                structure.structure_id, structure.pack_format,
                CandidateStatus.UNRESOLVED, ("material_master_version_mismatch",),
                (), None, **_review_context(reviewed),
            ))
            continue
        if _scope_key(commodity_type) not in {
            _scope_key(scope) for scope in structure.compatible_food_scope
        }:
            candidates.append(CandidateScreen(
                structure.structure_id, structure.pack_format,
                CandidateStatus.EXCLUDED, ("food_scope_mismatch",), (), None,
                **_review_context(reviewed),
            ))
            continue
        if (structure.service_temperature_min_c is None
                or structure.service_temperature_max_c is None
                or structure.service_temperature_min_c > card.service_temperature_min_c
                or structure.service_temperature_max_c < card.service_temperature_max_c):
            candidates.append(CandidateScreen(
                structure.structure_id, structure.pack_format,
                CandidateStatus.EXCLUDED, ("service_temperature_out_of_scope",), (), None,
                **_review_context(reviewed),
            ))
            continue

        for mechanism in ProtectionMechanism:
            check = check_transfer_budget(
                card, structure.structure_id, mechanism,
                evidence_by_key.get(_transfer_key(
                    card, structure.structure_id, mechanism, reviewed.catalogue_sha256,
                )),
                structure_catalogue_sha256=reviewed.catalogue_sha256,
            )
            checks.append(check)
            if check.decision is TransferDecision.EXCEEDS_BUDGET:
                reasons.append(f"{mechanism.value}_exceeds_food_budget")
            elif check.decision is TransferDecision.UNRESOLVED:
                reasons.extend(check.reason_codes)

        if any(check.decision is TransferDecision.EXCEEDS_BUDGET for check in checks):
            status = CandidateStatus.EXCLUDED
        elif any(check.decision is TransferDecision.UNRESOLVED for check in checks):
            status = CandidateStatus.UNRESOLVED
        else:
            status = CandidateStatus.ELIGIBLE_FOR_SHORTLIST

        ratios = [check.observed_cumulative_transfer / check.maximum_cumulative_transfer
                  for check in checks
                  if check.decision is TransferDecision.WITHIN_BUDGET
                  and check.observed_cumulative_transfer is not None
                  and check.maximum_cumulative_transfer is not None
                  and check.maximum_cumulative_transfer > 0]
        worst_case = max(ratios) if ratios else None
        candidates.append(CandidateScreen(
            structure.structure_id, structure.pack_format, status,
            tuple(dict.fromkeys(reasons)), tuple(checks), worst_case,
            **_review_context(reviewed),
            transfer_evidence=tuple(
                evidence_by_key[key]
                for mechanism in ProtectionMechanism
                if (key := _transfer_key(
                    card, structure.structure_id, mechanism, reviewed.catalogue_sha256,
                )) in evidence_by_key
            ),
        ))

    result_candidates, preferred = _rank_candidates(tuple(candidates))
    eligible = any(item.status is CandidateStatus.ELIGIBLE_FOR_SHORTLIST
                   for item in result_candidates)
    return BasicRecommendation(
        card.record_id, card.food_reference_id,
        RecommendationStatus.PRELIMINARY_SHORTLIST if eligible
        else RecommendationStatus.NOT_READY,
        preferred,
        "lowest_worst_case_transfer_budget_utilization" if preferred else None,
        result_candidates,
        () if eligible else tuple(sorted({
            reason for item in result_candidates for reason in item.reason_codes
        })) or ("no_applicable_structure_candidates",),
        warnings,
        **report_context,
    )
