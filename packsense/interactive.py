"""One-browser-scenario adapter for the existing audited batch pipeline.

The food master supplies reference composition and, when present, reference
respiration. A browser supplies operating conditions only. Neither source is
silently promoted to a product measurement or a model training label.
"""

from __future__ import annotations

from math import isfinite
from typing import Any
from uuid import uuid4

from packsense.masters import FoodMasterEntry, MasterAudit


INPUT_FIELDS = frozenset({
    "food_reference_id", "food_master_sha256", "desired_shelf_life_days",
    "storage_type", "storage_temperature_c", "storage_relative_humidity_pct",
    "transport_mode", "transport_duration_hours", "transport_temperature_c",
    "transport_max_temperature_c", "transport_handling_severity",
    "net_pack_quantity", "net_pack_quantity_unit",
})
NUMBER_FIELDS = frozenset({
    "desired_shelf_life_days", "storage_temperature_c",
    "storage_relative_humidity_pct", "transport_duration_hours",
    "transport_temperature_c", "transport_max_temperature_c",
    "net_pack_quantity",
})
CHOICES = {
    "storage_type": frozenset({"ambient", "chilled", "frozen"}),
    "transport_mode": frozenset({"road", "rail", "air", "sea"}),
    "transport_handling_severity": frozenset({"low", "medium", "high"}),
    "net_pack_quantity_unit": frozenset({"g", "kg", "mL", "L"}),
}
REFERENCE_PROPERTIES = (
    "moisture_content_pct", "oil_fat_content_pct", "pH",
)


class IntakeError(ValueError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


def food_profile(entry: FoodMasterEntry) -> dict[str, Any]:
    reference = entry.reference
    missing = [name for name in REFERENCE_PROPERTIES if getattr(reference, name) is None]
    return {
        "food_reference_id": reference.food_id,
        "commodity_type": reference.commodity_type,
        "food_group": reference.food_group,
        "form_ready": not missing,
        "missing_reference_properties": missing,
        "moisture_content_pct": reference.moisture_content_pct,
        "oil_fat_content_pct": reference.oil_fat_content_pct,
        "pH": reference.pH,
        "pH_basis": reference.pH_basis,
        "pH_evidence": entry.pH_evidence,
        "respiration_rate": reference.respiration_rate,
        "respiration_rate_unit": reference.respiration_rate_unit,
        "respiration_reference_temperature_c": reference.respiration_reference_temperature_c,
        "source_citations": reference.source_citations,
    }


def search_foods(audit: MasterAudit[FoodMasterEntry], query: str, limit: int = 15) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 80 or any(ord(char) < 32 for char in query):
        raise IntakeError("Search text must be at most 80 visible characters.", "query")
    term = " ".join(query.split()).casefold()
    matches = [entry for entry in audit.entries if term and (
        term in entry.reference.commodity_type.casefold()
        or term in entry.reference.food_id.casefold()
    )]
    matches.sort(key=lambda entry: (
        not food_profile(entry)["form_ready"],
        entry.reference.commodity_type.casefold(), entry.reference.food_id,
    ))
    return {
        "contract_version": "food-lookup-v1",
        "food_master_sha256": audit.source_sha256,
        "total_matches": len(matches),
        "form_ready_matches": sum(food_profile(entry)["form_ready"] for entry in matches),
        "foods": [food_profile(entry) for entry in matches[:limit]],
    }


def scenario_row_from_submission(
    payload: Any, audit: MasterAudit[FoodMasterEntry],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise IntakeError("Submit one scenario as a JSON object.")
    extra = set(payload) - INPUT_FIELDS
    if extra:
        raise IntakeError(f"Unsupported input field: {sorted(extra)[0]}.")
    missing = INPUT_FIELDS - set(payload)
    if missing:
        raise IntakeError(f"Required input is missing: {sorted(missing)[0]}.", sorted(missing)[0])
    if payload["food_master_sha256"] != audit.source_sha256:
        raise IntakeError("The food reference changed. Search and select the food again.", "food_reference_id")
    food_id = payload["food_reference_id"]
    if not isinstance(food_id, str) or not food_id or len(food_id) > 128:
        raise IntakeError("Choose a food from the reference search.", "food_reference_id")
    entry = next((item for item in audit.entries if item.reference.food_id == food_id), None)
    if entry is None:
        raise IntakeError("The selected food is absent from the accepted reference rows.", "food_reference_id")
    profile = food_profile(entry)
    if not profile["form_ready"]:
        fields = ", ".join(profile["missing_reference_properties"])
        raise IntakeError(f"This food reference lacks {fields}; choose a complete reference.", "food_reference_id")

    for field in NUMBER_FIELDS:
        value = payload[field]
        try:
            finite = type(value) in (int, float) and isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise IntakeError(f"{field} must be a finite number.", field)
    for field, accepted in CHOICES.items():
        if not isinstance(payload[field], str) or payload[field] not in accepted:
            raise IntakeError(f"Choose a supported {field} value.", field)
    if payload["desired_shelf_life_days"] <= 0:
        raise IntakeError("Requested shelf life must be above zero days.", "desired_shelf_life_days")
    if payload["net_pack_quantity"] <= 0:
        raise IntakeError("Pack quantity must be above zero.", "net_pack_quantity")
    if payload["transport_duration_hours"] < 0:
        raise IntakeError("Transport duration cannot be negative.", "transport_duration_hours")
    if not 0 <= payload["storage_relative_humidity_pct"] <= 100:
        raise IntakeError("Storage humidity must be between 0 and 100%.", "storage_relative_humidity_pct")
    for field in ("storage_temperature_c", "transport_temperature_c", "transport_max_temperature_c"):
        if payload[field] < -273.15:
            raise IntakeError("Temperature cannot be below absolute zero.", field)
    if payload["transport_max_temperature_c"] < payload["transport_temperature_c"]:
        raise IntakeError("Highest transport temperature cannot be below its usual temperature.", "transport_max_temperature_c")
    if payload["storage_type"] == "frozen" and payload["storage_temperature_c"] > 0:
        raise IntakeError("Frozen storage cannot be above 0 °C.", "storage_temperature_c")

    reference = entry.reference
    row = {
        "record_id": f"WEB-{uuid4().hex[:12]}",
        "commodity_type": reference.commodity_type,
        "food_reference_id": reference.food_id,
        "moisture_content_pct": reference.moisture_content_pct,
        "oil_fat_content_pct": reference.oil_fat_content_pct,
        "pH": reference.pH,
        "respiration_rate": reference.respiration_rate,
        "respiration_rate_unit": reference.respiration_rate_unit,
        "respiration_reference_temperature_c": reference.respiration_reference_temperature_c,
    }
    row.update({field: payload[field] for field in INPUT_FIELDS - {"food_reference_id", "food_master_sha256"}})
    return row, profile
