"""Exact reference joins required before exploratory shelf-life fitting.

This is a structural audit, not proof that a cited trial or review is genuine.
It never creates outcomes from reference storage-life values or material grades.
"""

from collections import Counter
from dataclasses import dataclass
from math import isclose
from typing import Any

from packsense.masters import FoodMasterEntry, MasterAudit, MaterialMasterEntry
from packsense.splits import ReviewRegister
from packsense.structure_review import StructureReviewAudit, attestation_integrity_gaps
from packsense.structures import StructureCatalogueAudit
from packsense.trials import TrialAudit


LINK_VERSION = "trial-reference-link-v1"


@dataclass(frozen=True, slots=True)
class TrialLinkIssue:
    trial_id: str | None
    code: str


@dataclass(frozen=True, slots=True)
class TrialLinkAudit:
    status: str
    issues: tuple[TrialLinkIssue, ...]
    linked_trial_rows: int
    food_master_sha256: str
    material_master_sha256: str
    structure_catalogue_sha256: str
    structure_review_register_sha256: str

    def report(self) -> dict[str, Any]:
        counts = Counter(issue.code for issue in self.issues)
        return {
            "link_version": LINK_VERSION,
            "status": self.status,
            "linked_trial_rows": self.linked_trial_rows,
            "food_master_sha256": self.food_master_sha256,
            "material_master_sha256": self.material_master_sha256,
            "structure_catalogue_sha256": self.structure_catalogue_sha256,
            "structure_review_register_sha256": self.structure_review_register_sha256,
            "issue_counts": [
                {"code": code, "count": count} for code, count in sorted(counts.items())
            ],
            "issues": [
                {"trial_id": issue.trial_id, "code": issue.code}
                for issue in self.issues
            ],
            "evidence_authenticity_verified_by_code": False,
            "model_trained": False,
            "model_validated": False,
        }


def _scope_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def audit_trial_reference_links(
    trials: TrialAudit,
    trial_reviews: ReviewRegister,
    foods: MasterAudit[FoodMasterEntry],
    materials: MasterAudit[MaterialMasterEntry],
    catalogue: StructureCatalogueAudit,
    structure_reviews: StructureReviewAudit,
) -> TrialLinkAudit:
    """Refuse trial/model joins unless food and complete package IDs resolve.

    A trial review must name the exact attested structure review. The service
    range must cover recorded storage and transport exposure; no generic
    material-name or catalogue-life fallback is allowed.
    """
    issues: list[TrialLinkIssue] = []

    def issue(trial_id: str | None, code: str) -> None:
        issues.append(TrialLinkIssue(trial_id, code))

    if trials.issues or trials.total_rows != len(trials.entries) or not trials.entries:
        issue(None, "trial_intake_not_clean")
    if trial_reviews.trial_source_sha256 != trials.source_sha256:
        issue(None, "trial_review_source_hash_mismatch")
    if foods.issues or foods.total_rows != len(foods.entries) or not foods.entries:
        issue(None, "food_master_not_clean")
    if materials.issues or materials.total_rows != len(materials.entries) or not materials.entries:
        issue(None, "material_master_not_clean")
    if (catalogue.issues or catalogue.total_rows != len(catalogue.entries)
            or not catalogue.entries):
        issue(None, "structure_catalogue_not_clean")
    if catalogue.material_master_sha256 != materials.source_sha256:
        issue(None, "catalogue_material_master_hash_mismatch")
    if (structure_reviews.status != "review_attested" or structure_reviews.issues
            or not structure_reviews.reviewed
            or attestation_integrity_gaps(structure_reviews)):
        issue(None, "structure_review_not_consistently_attested")
    if structure_reviews.catalogue_sha256 != catalogue.source_sha256:
        issue(None, "structure_review_catalogue_hash_mismatch")
    if any(reviewed.material_master_sha256 != materials.source_sha256
           for reviewed in structure_reviews.reviewed):
        issue(None, "structure_review_material_master_hash_mismatch")

    food_by_id = {entry.reference.food_id: entry.reference for entry in foods.entries}
    grades_by_id = {entry.grade.material_id: entry.grade for entry in materials.entries}
    drafts_by_id = {draft.structure_id: draft for draft in catalogue.entries}
    structures_by_id = {
        entry.structure.structure_id: entry for entry in structure_reviews.reviewed
    }
    reviews_by_trial = {review.trial_id: review for review in trial_reviews.reviews}
    if len(food_by_id) != len(foods.entries):
        issue(None, "duplicate_food_reference_id")
    if len(grades_by_id) != len(materials.entries):
        issue(None, "duplicate_material_grade_id")
    if len(drafts_by_id) != len(catalogue.entries):
        issue(None, "duplicate_structure_draft_id")
    if len(structures_by_id) != len(structure_reviews.reviewed):
        issue(None, "duplicate_reviewed_structure_id")
    if len(reviews_by_trial) != len(trial_reviews.reviews):
        issue(None, "duplicate_trial_review_id")
    if set(drafts_by_id) != set(structures_by_id):
        issue(None, "catalogue_review_structure_set_mismatch")

    linked = 0
    for entry in trials.entries:
        outcome = entry.outcome
        trial_id = outcome.trial_id
        start = len(issues)
        food = food_by_id.get(outcome.food_id)
        reviewed = structures_by_id.get(outcome.structure_id)
        review = reviews_by_trial.get(trial_id)
        if food is None:
            issue(trial_id, "trial_food_id_not_in_master")
        if reviewed is None:
            issue(trial_id, "trial_structure_id_not_reviewed")
        if review is None:
            issue(trial_id, "trial_review_missing")
        if outcome.structure_catalogue_version != catalogue.catalogue_version:
            issue(trial_id, "trial_catalogue_version_mismatch")
        if reviewed is not None:
            structure = reviewed.structure
            draft = drafts_by_id.get(outcome.structure_id)
            if (draft is None or structure.pack_format != draft.pack_format
                    or structure.layers != draft.layers
                    or structure.sealant_grade_id != draft.sealant_grade_id
                    or structure.structure_source_id != draft.structure_source_id
                    or structure.food_contact_evidence_id
                    != draft.food_contact_evidence_id):
                issue(trial_id, "trial_structure_draft_binding_mismatch")
            if review is not None and review.structure_review_id != reviewed.review_id:
                issue(trial_id, "trial_structure_review_id_mismatch")
            if food is not None and _scope_key(food.commodity_type) not in {
                _scope_key(scope) for scope in structure.compatible_food_scope
            }:
                issue(trial_id, "trial_structure_food_scope_mismatch")
            if any(layer.grade_id not in grades_by_id for layer in structure.layers):
                issue(trial_id, "trial_structure_grade_not_in_master")
            elif any(not isclose(layer.thickness_um, grades_by_id[layer.grade_id].thickness_um,
                                 rel_tol=0, abs_tol=1e-9)
                     for layer in structure.layers):
                issue(trial_id, "trial_structure_gauge_not_in_material_master")
            temperatures = [outcome.storage_temperature_c]
            if outcome.transport_temperature_c is not None:
                temperatures.append(outcome.transport_temperature_c)
            if outcome.transport_max_temperature_c is not None:
                temperatures.append(outcome.transport_max_temperature_c)
            if (structure.service_temperature_min_c is None
                    or structure.service_temperature_max_c is None
                    or min(temperatures) < structure.service_temperature_min_c
                    or max(temperatures) > structure.service_temperature_max_c):
                issue(trial_id, "trial_structure_temperature_out_of_scope")
        if len(issues) == start:
            linked += 1
    return TrialLinkAudit(
        "ready_for_split" if not issues else "not_ready", tuple(issues), linked,
        foods.source_sha256, materials.source_sha256, catalogue.source_sha256,
        structure_reviews.review_register_sha256,
    )
