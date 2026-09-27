"""Audit public supplier claims before any package-structure or label intake.

These records describe source documents and product claims. They are never
`StructureDraft` objects, approved packages, or suitability training labels.
"""

import argparse
import json
from collections import Counter
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from packsense.ingestion import InputSchemaError, _sha256


ROOT_FIELDS = frozenset({"schema_version", "catalogue_id", "sources", "candidates"})
SOURCE_FIELDS = frozenset({
    "source_id", "publisher", "title", "url", "accessed_on", "rights_review_status",
})
CANDIDATE_FIELDS = frozenset({
    "candidate_id", "source_id", "source_locator", "product_code", "record_kind",
    "pack_format", "layers", "reported_total_gauge", "barrier_observations",
    "seal_observation", "food_contact_claim", "claimed_food_scope",
    "service_temperature_c", "applications", "source_note",
})
LAYER_FIELDS = frozenset({"material", "gauge_min", "gauge_max", "gauge_unit"})
GAUGE_FIELDS = frozenset({"value", "unit", "basis"})
BARRIER_FIELDS = frozenset({
    "property", "lower", "upper", "lower_inclusive", "upper_inclusive", "unit",
    "test_temperature_c", "test_rh_pct", "method", "basis",
})
SEAL_FIELDS = frozenset({
    "strength_lower", "strength_lower_inclusive", "strength_unit",
    "strength_method", "process_temperature_min_c", "process_temperature_max_c",
})
APPLICATION_FIELDS = frozenset({
    "commodity", "quantity", "quantity_unit", "storage_temperature_min_c",
    "storage_temperature_max_c", "excursion_max_c", "excursion_max_hours",
    "bag_width_mm", "bag_length_mm", "use_note",
})
TEMPERATURE_FIELDS = frozenset({"min_c", "max_c"})
RECORD_KINDS = frozenset({"laminate_film", "tray_component", "produce_bag"})
BARRIER_UNITS = {
    "otr": frozenset({"cm3/m2/24h", "cm3/100in2/24h"}),
    "co2tr": frozenset({"cm3/m2/24h", "cm3/100in2/24h"}),
    "wvtr": frozenset({"g/m2/24h", "g/100in2/24h"}),
}
BARRIER_BASES = frozenset({
    "supplier_typical", "supplier_reported_range", "supplier_450um_test_result",
    "supplier_indicative",
})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputSchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InputSchemaError(f"non-finite JSON number: {value}")


def _fields(value: Any, expected: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        found = set(value) if isinstance(value, dict) else set()
        raise InputSchemaError(
            f"{name} keys mismatch; missing={sorted(expected - found)}, "
            f"extra={sorted(found - expected)}"
        )
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise InputSchemaError(f"{name} must be non-empty, trimmed text")
    return value


def _number(value: Any, name: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputSchemaError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise InputSchemaError(f"{name} must be finite") from exc
    if not isfinite(number) or (positive and number <= 0) or (nonnegative and number < 0):
        requirement = "positive and finite" if positive else (
            "nonnegative and finite" if nonnegative else "finite"
        )
        raise InputSchemaError(f"{name} must be {requirement}")
    return number


def _temperature(value: Any, name: str) -> float:
    number = _number(value, name)
    if number < -273.15:
        raise InputSchemaError(f"{name} is below absolute zero")
    return number


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputSchemaError(f"{name} must be an array")
    return value


def _range(low: Any, high: Any, name: str, *, temperature: bool = False) -> None:
    read = _temperature if temperature else _number
    if read(low, f"{name}.min") > read(high, f"{name}.max"):
        raise InputSchemaError(f"{name} minimum exceeds maximum")


def _layer(raw: Any, name: str) -> None:
    row = _fields(raw, LAYER_FIELDS, name)
    _text(row["material"], f"{name}.material")
    low, high, unit = row["gauge_min"], row["gauge_max"], row["gauge_unit"]
    if low is None or high is None or unit is None:
        if (low, high, unit) != (None, None, None):
            raise InputSchemaError(f"{name} gauge must be fully stated or fully absent")
    else:
        if unit not in {"um", "mm", "mil", "ga"}:
            raise InputSchemaError(f"{name}.gauge_unit is unsupported")
        if _number(low, f"{name}.gauge_min", positive=True) > _number(
            high, f"{name}.gauge_max", positive=True
        ):
            raise InputSchemaError(f"{name} gauge minimum exceeds maximum")


def _barrier(raw: Any, name: str) -> None:
    row = _fields(raw, BARRIER_FIELDS, name)
    prop = _text(row["property"], f"{name}.property")
    if prop not in BARRIER_UNITS or row["unit"] not in BARRIER_UNITS[prop]:
        raise InputSchemaError(f"{name} property or unit is unsupported")
    if row["basis"] not in BARRIER_BASES:
        raise InputSchemaError(f"{name}.basis is unsupported")
    _text(row["method"], f"{name}.method")
    for end in ("lower", "upper"):
        value, inclusive = row[end], row[f"{end}_inclusive"]
        if value is None:
            if inclusive is not None:
                raise InputSchemaError(f"{name}.{end}_inclusive requires a bound")
        else:
            _number(value, f"{name}.{end}", nonnegative=True)
            if not isinstance(inclusive, bool):
                raise InputSchemaError(f"{name}.{end}_inclusive must be boolean")
    if row["lower"] is None and row["upper"] is None:
        raise InputSchemaError(f"{name} has no numeric bound")
    if row["lower"] is not None and row["upper"] is not None:
        _range(row["lower"], row["upper"], name)
        if row["lower"] == row["upper"] and not (
            row["lower_inclusive"] and row["upper_inclusive"]
        ):
            raise InputSchemaError(f"{name} has an empty numeric interval")
    temp, rh = row["test_temperature_c"], row["test_rh_pct"]
    if (temp is None) != (rh is None):
        raise InputSchemaError(f"{name} needs both test temperature and RH or neither")
    if temp is not None:
        _temperature(temp, f"{name}.test_temperature_c")
        if not 0 <= _number(rh, f"{name}.test_rh_pct") <= 100:
            raise InputSchemaError(f"{name}.test_rh_pct is outside 0-100")


def _application(raw: Any, name: str, scope: set[str]) -> None:
    row = _fields(raw, APPLICATION_FIELDS, name)
    commodity = _text(row["commodity"], f"{name}.commodity")
    if commodity.casefold() not in scope:
        raise InputSchemaError(f"{name}.commodity is absent from claimed_food_scope")
    _number(row["quantity"], f"{name}.quantity", positive=True)
    if row["quantity_unit"] not in {"g", "kg"}:
        raise InputSchemaError(f"{name}.quantity_unit is unsupported")
    _range(row["storage_temperature_min_c"], row["storage_temperature_max_c"],
           f"{name}.storage_temperature", temperature=True)
    excursion, hours = row["excursion_max_c"], row["excursion_max_hours"]
    if (excursion is None) != (hours is None):
        raise InputSchemaError(f"{name} excursion temperature and hours must be paired")
    if excursion is not None:
        if _temperature(excursion, f"{name}.excursion_max_c") < row["storage_temperature_max_c"]:
            raise InputSchemaError(f"{name} excursion is below storage maximum")
        _number(hours, f"{name}.excursion_max_hours", positive=True)
    _number(row["bag_width_mm"], f"{name}.bag_width_mm", positive=True)
    _number(row["bag_length_mm"], f"{name}.bag_length_mm", positive=True)
    _text(row["use_note"], f"{name}.use_note")


def load_candidate_catalogue(path: str | Path) -> tuple[dict[str, Any], str]:
    """Validate source facts; do not infer absent properties or suitability."""
    source_path = Path(path).resolve(strict=True)
    if source_path.suffix.lower() != ".json":
        raise InputSchemaError("candidate catalogue must be a .json file")
    with source_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream, object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)
    root = _fields(data, ROOT_FIELDS, "catalogue")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise InputSchemaError("unsupported schema_version")
    _text(root["catalogue_id"], "catalogue_id")
    sources = _list(root["sources"], "sources")
    candidates = _list(root["candidates"], "candidates")
    source_ids: set[str] = set()
    for index, raw in enumerate(sources):
        name = f"sources[{index}]"
        item = _fields(raw, SOURCE_FIELDS, name)
        source_id = _text(item["source_id"], f"{name}.source_id")
        if source_id in source_ids:
            raise InputSchemaError(f"duplicate source_id: {source_id}")
        source_ids.add(source_id)
        for key in ("publisher", "title"):
            _text(item[key], f"{name}.{key}")
        url = _text(item["url"], f"{name}.url")
        if urlparse(url).scheme != "https" or not urlparse(url).netloc:
            raise InputSchemaError(f"{name}.url must be an HTTPS source URL")
        try:
            date.fromisoformat(item["accessed_on"])
        except (TypeError, ValueError) as exc:
            raise InputSchemaError(f"{name}.accessed_on must be YYYY-MM-DD") from exc
        if item["rights_review_status"] != "pending":
            raise InputSchemaError(f"{name} must not claim rights approval in draft intake")
    candidate_ids: set[str] = set()
    product_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(candidates):
        name = f"candidates[{index}]"
        item = _fields(raw, CANDIDATE_FIELDS, name)
        candidate_id = _text(item["candidate_id"], f"{name}.candidate_id")
        if candidate_id in candidate_ids:
            raise InputSchemaError(f"duplicate candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        source_id = _text(item["source_id"], f"{name}.source_id")
        if source_id not in source_ids:
            raise InputSchemaError(f"{name}.source_id is absent from sources")
        product_code = _text(item["product_code"], f"{name}.product_code")
        product_key = (source_id, product_code)
        if product_key in product_keys:
            raise InputSchemaError(f"duplicate source/product_code: {product_key}")
        product_keys.add(product_key)
        for key in ("source_locator", "pack_format", "source_note"):
            _text(item[key], f"{name}.{key}")
        if item["record_kind"] not in RECORD_KINDS:
            raise InputSchemaError(f"{name}.record_kind is unsupported")
        for layer_index, layer in enumerate(_list(item["layers"], f"{name}.layers")):
            _layer(layer, f"{name}.layers[{layer_index}]")
        gauge = item["reported_total_gauge"]
        if gauge is not None:
            row = _fields(gauge, GAUGE_FIELDS, f"{name}.reported_total_gauge")
            _number(row["value"], f"{name}.reported_total_gauge.value", positive=True)
            if row["unit"] not in {"um", "mm", "mil"}:
                raise InputSchemaError(f"{name}.reported_total_gauge.unit is unsupported")
            if row["basis"] not in {
                "supplier_reported", "supplier_test_sample", "size_expression_interpretation"
            }:
                raise InputSchemaError(f"{name}.reported_total_gauge.basis is unsupported")
        seen_properties: set[str] = set()
        for barrier_index, observation in enumerate(_list(
            item["barrier_observations"], f"{name}.barrier_observations"
        )):
            _barrier(observation, f"{name}.barrier_observations[{barrier_index}]")
            prop = observation["property"]
            if prop in seen_properties:
                raise InputSchemaError(f"{name} repeats {prop} without a separate observation identity")
            seen_properties.add(prop)
        seal = item["seal_observation"]
        if seal is not None:
            row = _fields(seal, SEAL_FIELDS, f"{name}.seal_observation")
            _number(row["strength_lower"], f"{name}.seal_observation.strength_lower",
                    positive=True)
            if not isinstance(row["strength_lower_inclusive"], bool):
                raise InputSchemaError(f"{name}.seal_observation.strength_lower_inclusive must be boolean")
            if row["strength_unit"] not in {"N/15mm", "lb/in"}:
                raise InputSchemaError(f"{name}.seal_observation.strength_unit is unsupported")
            if row["strength_method"] is not None:
                _text(row["strength_method"], f"{name}.seal_observation.strength_method")
            _range(row["process_temperature_min_c"], row["process_temperature_max_c"],
                   f"{name}.seal_observation.process_temperature", temperature=True)
        if item["food_contact_claim"] is not None:
            _text(item["food_contact_claim"], f"{name}.food_contact_claim")
        scope = [_text(food, f"{name}.claimed_food_scope") for food in _list(
            item["claimed_food_scope"], f"{name}.claimed_food_scope"
        )]
        if len({food.casefold() for food in scope}) != len(scope):
            raise InputSchemaError(f"{name}.claimed_food_scope repeats a food")
        if any(food.casefold() in {"*", "all", "any", "all_foods"} for food in scope):
            raise InputSchemaError(f"{name}.claimed_food_scope cannot be a wildcard")
        service = item["service_temperature_c"]
        if service is not None:
            row = _fields(service, TEMPERATURE_FIELDS, f"{name}.service_temperature_c")
            _range(row["min_c"], row["max_c"], f"{name}.service_temperature_c",
                   temperature=True)
        application_keys: set[tuple[Any, ...]] = set()
        for app_index, app in enumerate(_list(item["applications"], f"{name}.applications")):
            _application(app, f"{name}.applications[{app_index}]",
                         {food.casefold() for food in scope})
            key = (
                app["commodity"].casefold(), float(app["quantity"]), app["quantity_unit"],
                app["storage_temperature_min_c"], app["storage_temperature_max_c"],
                app["excursion_max_c"], app["excursion_max_hours"],
            )
            if key in application_keys:
                raise InputSchemaError(f"{name} repeats an application for the same food and amount")
            application_keys.add(key)
    return root, _sha256(source_path)


def audit_candidate_catalogue(path: str | Path) -> dict[str, Any]:
    """Summarize source coverage and blockers without promoting any candidate."""
    catalogue, source_sha256 = load_candidate_catalogue(path)
    candidates = catalogue["candidates"]
    counts = Counter(item["record_kind"] for item in candidates)
    coverage = {
        "declared_layer_stacks": sum(bool(item["layers"]) for item in candidates),
        "all_layer_gauges_reported": sum(
            bool(item["layers"]) and all(layer["gauge_min"] is not None for layer in item["layers"])
            for item in candidates
        ),
        "with_otr": sum(any(obs["property"] == "otr" for obs in item["barrier_observations"])
                        for item in candidates),
        "with_wvtr": sum(any(obs["property"] == "wvtr" for obs in item["barrier_observations"])
                         for item in candidates),
        "with_co2tr": sum(any(obs["property"] == "co2tr" for obs in item["barrier_observations"])
                          for item in candidates),
        "with_food_contact_claim": sum(item["food_contact_claim"] is not None
                                       for item in candidates),
        "with_service_temperature_limit": sum(item["service_temperature_c"] is not None
                                              for item in candidates),
        "with_exact_food_quantity_temperature_use": sum(bool(item["applications"])
                                                        for item in candidates),
        "gauge_interpretations_needing_confirmation": sum(
            item["reported_total_gauge"] is not None and
            item["reported_total_gauge"]["basis"] == "size_expression_interpretation"
            for item in candidates
        ),
    }
    blockers = []
    for item in candidates:
        missing = ["exact_material_grade_join", "reviewed_food_contact_document",
                   "verified_service_temperature_limit", "reviewed_finished_package_seal_and_handling",
                   "tested_complete_package_transfer",
                   "reviewed_source_rights"]
        if not item["layers"] or any(layer["gauge_min"] is None for layer in item["layers"]):
            missing.append("complete_exact_layer_construction")
        if (item["reported_total_gauge"] is not None and
                item["reported_total_gauge"]["basis"] == "size_expression_interpretation"):
            missing.append("gauge_interpretation_needs_supplier_confirmation")
        if item["record_kind"] == "produce_bag":
            missing.append("sku_level_o2_and_co2_transfer_at_use_temperature")
        if item["seal_observation"] is None:
            missing.append("seal_strength_evidence")
        if item["pack_format"] == "box inner liner":
            missing.append("required_outer_package_definition")
        blockers.append({"candidate_id": item["candidate_id"], "missing_for_promotion": missing})
    return {
        "catalogue_id": catalogue["catalogue_id"],
        "catalogue_sha256": source_sha256,
        "source_count": len(catalogue["sources"]),
        "candidate_count": len(candidates),
        "candidate_kind_counts": dict(sorted(counts.items())),
        "coverage": coverage,
        "candidate_blockers": blockers,
        "approved_package_structures": 0,
        "suitability_training_labels": 0,
        "recommendation_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit public package-candidate claims")
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, help="new JSON report path")
    args = parser.parse_args()
    try:
        report = audit_candidate_catalogue(args.input)
        if args.report:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
    except (InputSchemaError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"input error: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
