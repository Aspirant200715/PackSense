"""Canonical input units; conversion and validation belong to ingestion (Stop 1)."""

from types import MappingProxyType

# Input columns retain the architecture's spelling, including ``pH``.
SCENARIO_REQUIRED_COLUMNS = (
    "record_id",
    "commodity_type",
    "moisture_content_pct",
    "oil_fat_content_pct",
    "pH",
    "desired_shelf_life_days",
    "storage_type",
    "storage_temperature_c",
    "storage_relative_humidity_pct",
    "transport_mode",
    "transport_duration_hours",
    "transport_temperature_c",
    "transport_max_temperature_c",
    "transport_handling_severity",
    "net_pack_quantity",
    "net_pack_quantity_unit",
)

SCENARIO_RESPIRATION_COLUMNS = (
    "respiration_rate",
    "respiration_rate_unit",
    "respiration_reference_temperature_c",
)

# A source-row key disambiguates commodities that share the same display name.
# It is optional for a unique exact name match and is never a model feature.
SCENARIO_REFERENCE_COLUMNS = ("food_reference_id",)

# A unit is None for an identifier or a controlled category. Percentages are
# stored as values from 0 to 100, not fractions from 0 to 1.
SCENARIO_UNITS = MappingProxyType(
    {
        "record_id": None,
        "commodity_type": None,
        "food_reference_id": None,
        "moisture_content_pct": "% wet basis, source basis retained",
        "oil_fat_content_pct": "% of food mass, source basis retained",
        "pH": "dimensionless",
        "respiration_rate": "as declared by respiration_rate_unit",
        "respiration_rate_unit": None,
        "respiration_reference_temperature_c": "°C",
        "desired_shelf_life_days": "days",
        "storage_type": None,
        "storage_temperature_c": "°C",
        "storage_relative_humidity_pct": "% RH",
        "transport_mode": None,
        "transport_duration_hours": "hours",
        "transport_temperature_c": "°C",
        "transport_max_temperature_c": "°C",
        "transport_handling_severity": None,
        "net_pack_quantity": "as declared by net_pack_quantity_unit",
        "net_pack_quantity_unit": None,
    }
)

PACK_QUANTITY_UNITS = frozenset({"g", "kg", "mL", "L"})

# The present food reference sheet reports CO2 evolution in this unit. It is
# not an O2-consumption measurement and must not be substituted for one.
REFERENCE_RESPIRATION_UNIT = "mg CO2/kg/h"

# These names match the available material reference workbook. Its values are
# grade/film observations, not finished-package performance guarantees.
MATERIAL_RATE_UNITS = MappingProxyType(
    {
        "otr_cm3_m2_day": "cm³/(m²·day), source test conditions",
        "co2tr_cm3_m2_day": "cm³/(m²·day), source test conditions",
        "wvtr_g_m2_day": "g/(m²·day), source test conditions",
        "thickness_um": "µm",
        "tensile_md_mpa": "MPa",
        "tensile_td_mpa": "MPa",
    }
)
