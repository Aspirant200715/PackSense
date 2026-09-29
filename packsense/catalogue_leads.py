"""Find supplier application leads without treating them as recommendations.

Only explicitly listed food/quantity/temperature applications are compared.
Film barrier claims, broad food scopes, and material-grade similarity never
become food/package suitability decisions here.
"""

import re
from math import isclose
from typing import Any, Mapping

from packsense.catalogue_candidates import candidate_promotion_gaps
from packsense.contracts import ScenarioInput


LOOKUP_VERSION = "supplier-application-lookup-v1"
PILOT_AUDIT_VERSION = "public-candidate-pilot-audit-v1"
_MASS_TO_GRAMS = {"g": 1.0, "kg": 1000.0}
_RAW_COLOUR_QUALIFIERS = frozenset({"green", "white", "red", "yellow", "purple"})


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _food_match(scenario_food: str, supplier_food: str) -> str | None:
    actual, published = _key(scenario_food), _key(supplier_food)
    if actual == published:
        return "exact_name"
    # A raw food-reference name is a possible lead, not a verified synonym.
    # Admit only a single colour qualifier; arbitrary middle terms might
    # describe processing (e.g. frozen) and must not inherit a fresh-food use.
    if actual == f"{published}, raw":
        return "raw_name_variant_unreviewed"
    prefix, suffix = f"{published}, ", ", raw"
    if actual.startswith(prefix) and actual.endswith(suffix):
        qualifier = actual[len(prefix):-len(suffix)]
        if qualifier in _RAW_COLOUR_QUALIFIERS:
            return "raw_name_variant_unreviewed"
    return None


def _quantity_matches(scenario: ScenarioInput, application: Mapping[str, Any]) -> bool:
    scenario_factor = _MASS_TO_GRAMS.get(scenario.net_pack_quantity_unit)
    application_factor = _MASS_TO_GRAMS.get(application["quantity_unit"])
    if scenario_factor is None or application_factor is None:
        return False
    return isclose(
        scenario.net_pack_quantity * scenario_factor,
        application["quantity"] * application_factor,
        rel_tol=0, abs_tol=1e-9,
    )


def _transport_matches(scenario: ScenarioInput, application: Mapping[str, Any]) -> bool:
    low = application["storage_temperature_min_c"]
    high = application["storage_temperature_max_c"]
    temperatures = (scenario.transport_temperature_c,
                    scenario.transport_max_temperature_c)
    if all(low <= temperature <= high for temperature in temperatures):
        return True
    excursion_max = application["excursion_max_c"]
    excursion_hours = application["excursion_max_hours"]
    # Treat the entire transit duration as a warm excursion. This is
    # conservative when the time spent at the maximum is not recorded.
    return (
        excursion_max is not None
        and excursion_hours is not None
        and all(low <= temperature <= excursion_max for temperature in temperatures)
        and scenario.transport_duration_hours <= excursion_hours
    )


def find_supplier_application_leads(
    scenario: ScenarioInput, validated_catalogue: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one actual scenario with published uses, never approve a pack.

    ``validated_catalogue`` must come from ``load_candidate_catalogue``. A
    reference food name ending in `, raw` is exposed as unreviewed identity,
    including one intervening colour qualifier;
    no other name parsing, fuzzy search, or family-level extrapolation occurs.
    """
    sources = {source["source_id"]: source for source in validated_catalogue["sources"]}
    leads: list[dict[str, Any]] = []
    for candidate in validated_catalogue["candidates"]:
        source = sources[candidate["source_id"]]
        for application in candidate["applications"]:
            identity = _food_match(scenario.commodity_type, application["commodity"])
            if identity is None:
                continue
            mismatches: list[str] = []
            if identity != "exact_name":
                mismatches.append("food_identity_requires_review")
            if not _quantity_matches(scenario, application):
                mismatches.append("pack_quantity_outside_published_use")
            if not (application["storage_temperature_min_c"]
                    <= scenario.storage_temperature_c
                    <= application["storage_temperature_max_c"]):
                mismatches.append("storage_temperature_outside_published_use")
            if not _transport_matches(scenario, application):
                mismatches.append("transport_exposure_outside_published_use")
            if candidate["pack_format"] == "box inner liner":
                mismatches.append("outer_package_not_specified")

            leads.append({
                "candidate_id": candidate["candidate_id"],
                "product_code": candidate["product_code"],
                "pack_format": candidate["pack_format"],
                "supplier_application_food": application["commodity"],
                "food_name_match": identity,
                "source_id": candidate["source_id"],
                "source_url": source["url"],
                "source_locator": candidate["source_locator"],
                "source_rights_review_status": source["rights_review_status"],
                "published_quantity": application["quantity"],
                "published_quantity_unit": application["quantity_unit"],
                "published_storage_temperature_min_c": application[
                    "storage_temperature_min_c"],
                "published_storage_temperature_max_c": application[
                    "storage_temperature_max_c"],
                "published_excursion_max_c": application["excursion_max_c"],
                "published_excursion_max_hours": application["excursion_max_hours"],
                "application_status": (
                    "published_food_quantity_temperature_match_unverified"
                    if not mismatches else "unresolved_or_outside_published_use"
                ),
                "reason_codes": mismatches,
                "approval_blockers": [
                    "source_rights_review_pending",
                    "exact_material_grade_join_missing",
                    "food_contact_and_service_limit_unverified",
                    "complete_package_transfer_and_seal_unverified",
                    "food_package_suitability_unverified",
                ],
            })
    leads.sort(key=lambda item: (item["candidate_id"], item["supplier_application_food"]))
    return {
        "lookup_version": LOOKUP_VERSION,
        "record_id": scenario.record_id,
        "catalogue_id": validated_catalogue["catalogue_id"],
        "status": "published_food_application_found" if leads else "no_published_food_application_match",
        "leads": leads,
        "approved_structure_count": 0,
        "recommended_structure_id": None,
        "model_prediction_available": False,
    }


def audit_pilot_candidate(
    scenario: ScenarioInput, validated_catalogue: Mapping[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    """Bind one public product lead to a scenario without approving it.

    The candidate catalogue contains supplier claims only. This view makes
    exact published-use mismatches and independent evidence gaps visible in
    the same batch row; it cannot create a structure review or suitability
    label from a similar food or polymer family.
    """
    candidates = {item["candidate_id"]: item for item in validated_catalogue["candidates"]}
    if candidate_id not in candidates:
        raise ValueError(f"unknown public candidate_id: {candidate_id}")
    candidate = candidates[candidate_id]
    source = next(item for item in validated_catalogue["sources"]
                  if item["source_id"] == candidate["source_id"])
    lookup = find_supplier_application_leads(scenario, validated_catalogue)
    matching = [lead for lead in lookup["leads"]
                if lead["candidate_id"] == candidate_id]
    if not candidate["applications"]:
        application_status = "no_published_food_application"
    elif not matching:
        application_status = "no_published_use_for_this_food"
    elif any(lead["application_status"] ==
             "published_food_quantity_temperature_match_unverified"
             for lead in matching):
        application_status = "published_use_match_unverified"
    else:
        application_status = "published_use_unresolved_or_outside_scope"

    return {
        "audit_version": PILOT_AUDIT_VERSION,
        "record_id": scenario.record_id,
        "candidate_id": candidate_id,
        "source_id": source["source_id"],
        "source_url": source["url"],
        "source_locator": candidate["source_locator"],
        "source_rights_review_status": source["rights_review_status"],
        "application_status": application_status,
        "published_application_leads": matching,
        "missing_for_promotion": candidate_promotion_gaps(candidate),
        "approved_structure_id": None,
        "recommendation_eligible": False,
        "model_training_label": False,
    }
