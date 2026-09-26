"""Version-one domain shapes for the eight-stop backend.

The classes separate recommendation scenarios, source references, measured
trial outcomes, and outputs. Ingestion, engineering rules, and prediction are
not implemented by this module.
"""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from packsense.units import PACK_QUANTITY_UNITS


class StorageType(StrEnum):
    AMBIENT = "ambient"
    CHILLED = "chilled"
    FROZEN = "frozen"


class HandlingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceBasis(StrEnum):
    MEASURED = "measured"
    SUPPLIER_REPORTED = "supplier_reported"
    VALIDATED_CORRECTION = "validated_correction"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class RecommendationStatus(StrEnum):
    EXCEPTION = "exception"
    NO_FEASIBLE_PACKAGE = "no_feasible_package"
    ENGINEERING_REVIEW = "engineering_review"
    VALIDATED_PILOT = "validated_pilot"


@dataclass(frozen=True, slots=True)
class ScenarioInput:
    """One food, pack size, storage and transport recommendation case.

    Respiration fields are conditionally required after the commodity master
    identifies a respiring food. No default value may be inferred for a
    missing required scenario field.
    """

    record_id: str
    commodity_type: str
    moisture_content_pct: float
    oil_fat_content_pct: float
    pH: float
    desired_shelf_life_days: float
    storage_type: StorageType
    storage_temperature_c: float
    storage_relative_humidity_pct: float
    transport_mode: str
    transport_duration_hours: float
    transport_temperature_c: float
    transport_max_temperature_c: float
    transport_handling_severity: HandlingSeverity
    net_pack_quantity: float
    net_pack_quantity_unit: str
    respiration_rate: float | None = None
    respiration_rate_unit: str | None = None
    respiration_reference_temperature_c: float | None = None
    food_reference_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not isinstance(self.commodity_type, str):
            raise TypeError("record_id and commodity_type must be strings")
        if not self.record_id.strip() or not self.commodity_type.strip():
            raise ValueError("record and commodity identifiers cannot be empty")
        if self.food_reference_id is not None and (
            not isinstance(self.food_reference_id, str) or not self.food_reference_id.strip()
        ):
            raise ValueError("food_reference_id must be non-empty text when supplied")
        if not isinstance(self.storage_type, StorageType):
            raise TypeError("storage_type must be a StorageType")
        if not isinstance(self.transport_handling_severity, HandlingSeverity):
            raise TypeError("transport_handling_severity must be a HandlingSeverity")
        if self.net_pack_quantity_unit not in PACK_QUANTITY_UNITS:
            raise ValueError("net_pack_quantity_unit is not a supported canonical unit")
        respiration = (
            self.respiration_rate,
            self.respiration_rate_unit,
            self.respiration_reference_temperature_c,
        )
        if any(value is not None for value in respiration) and not all(
            value is not None for value in respiration
        ):
            raise ValueError("respiration rate, unit, and reference temperature travel together")


@dataclass(frozen=True, slots=True)
class FoodReference:
    """A commodity master row, which is not a complete scenario or trial."""

    food_id: str
    commodity_type: str
    food_group: str | None
    moisture_content_pct: float | None
    oil_fat_content_pct: float | None
    pH: float | None
    pH_basis: str | None
    respiration_rate: float | None
    respiration_rate_unit: str | None
    respiration_reference_temperature_c: float | None
    source_citations: str
    composition_method: str | None = None
    pH_ref_min: float | None = None
    pH_ref_max: float | None = None
    pH_source_food: str | None = None
    reference_storage_min_c: float | None = None
    reference_storage_max_c: float | None = None
    reference_storage_rh_min_pct: float | None = None
    reference_storage_rh_max_pct: float | None = None
    reference_life_min: float | None = None
    reference_life_max: float | None = None
    reference_life_unit: str | None = None
    reference_storage_basis: str | None = None


@dataclass(frozen=True, slots=True)
class BarrierObservation:
    """One reported grade property at its original test conditions."""

    value: float
    unit: str
    test_temperature_c: float | None
    test_relative_humidity_pct: float | None
    test_method: str | None
    basis: EvidenceBasis
    source_url: str
    source_note: str | None = None


@dataclass(frozen=True, slots=True)
class MaterialGrade:
    """A supplier grade/film reference, not an approved finished package."""

    material_id: str
    manufacturer: str
    grade: str | None
    material_family: str
    film_structure: str
    film_role: str
    thickness_um: float
    otr: BarrierObservation | None
    co2tr: BarrierObservation | None
    wvtr: BarrierObservation | None
    co2_training_label: bool
    seal_status: str
    food_contact_statement: str
    model_use_status: str
    source_url: str
    seal_min_c: float | None = None
    seal_max_c: float | None = None
    tensile_md_mpa: float | None = None
    tensile_td_mpa: float | None = None
    evidence_note: str | None = None

    def __post_init__(self) -> None:
        if self.co2_training_label and (
            self.co2tr is None
            or self.co2tr.basis is not EvidenceBasis.MEASURED
            or self.co2tr.test_temperature_c is None
            or self.co2tr.test_relative_humidity_pct is None
        ):
            raise ValueError("CO2 training labels require a measured grade observation with test conditions")


@dataclass(frozen=True, slots=True)
class StructureLayer:
    grade_id: str
    thickness_um: float
    role: str
    is_food_contact: bool


@dataclass(frozen=True, slots=True)
class PackageStructure:
    """A separately verified manufacturable package, not a material row."""

    structure_id: str
    pack_format: str
    layers: tuple[StructureLayer, ...]
    sealant_grade_id: str
    structure_source_id: str
    food_contact_evidence_id: str | None
    compatible_food_scope: tuple[str, ...]
    service_temperature_min_c: float | None
    service_temperature_max_c: float | None


@dataclass(frozen=True, slots=True)
class TrialOutcome:
    """Measured independent trial; desired life is never the observed label."""

    trial_id: str
    trial_group_id: str
    batch_id: str
    source_id: str
    food_id: str
    structure_id: str
    fill_mass_g: float
    package_area_m2: float
    headspace_ml: float
    storage_temperature_c: float
    storage_relative_humidity_pct: float
    observed_days: float
    failure_observed: bool
    failure_criterion: str
    failure_mechanism: str | None = None
    failure_threshold: str | None = None
    exposure_profile_id: str | None = None
    structure_catalogue_version: str | None = None
    transport_temperature_c: float | None = None
    transport_max_temperature_c: float | None = None
    transport_duration_hours: float | None = None


@dataclass(frozen=True, slots=True)
class ProduceGasSpecification:
    oxygen_min_pct: float
    oxygen_max_pct: float
    carbon_dioxide_min_pct: float
    carbon_dioxide_max_pct: float
    map_suitability: str
    gas_limit_source_id: str
    perforation_diameter_um: float | None = None
    perforation_count: int | None = None


@dataclass(frozen=True, slots=True)
class PackageSpecification:
    structure_id: str
    pack_format: str
    layers: tuple[StructureLayer, ...]
    total_thickness_um: float
    otr_at_conditions: BarrierObservation | None
    co2tr_at_conditions: BarrierObservation | None
    wvtr_at_conditions: BarrierObservation | None
    seal_window_min_c: float | None
    seal_window_max_c: float | None
    max_verified_temperature_c: float | None
    evidence_ids: tuple[str, ...]
    mechanical_requirements: tuple[str, ...] = ()
    produce_gas: ProduceGasSpecification | None = None


@dataclass(frozen=True, slots=True)
class ShelfLifeResult:
    predicted_days: float
    interval_low_days: float
    interval_high_days: float
    limiting_mechanism: str
    model_version: str
    validation_scope_id: str
    confidence_status: str
    interval_method: str

    def __post_init__(self) -> None:
        values = (self.interval_low_days, self.predicted_days, self.interval_high_days)
        if not all(isfinite(value) for value in values) or not (
            0 < self.interval_low_days <= self.predicted_days <= self.interval_high_days
        ):
            raise ValueError("shelf-life prediction must lie inside a positive interval")
        if not self.model_version or not self.validation_scope_id:
            raise ValueError("a shelf-life claim requires model and validation scope IDs")


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    record_id: str
    status: RecommendationStatus
    preferred: PackageSpecification | None
    alternatives: tuple[PackageSpecification, ...]
    shelf_life: ShelfLifeResult | None
    warnings: tuple[str, ...]
    exception_reasons: tuple[str, ...]
    operating_limits: tuple[str, ...]
    food_source_id: str | None
    material_data_version: str | None
    structure_catalogue_version: str | None
    rule_set_version: str | None
    scoring_config_version: str | None

    def __post_init__(self) -> None:
        if self.status in (
            RecommendationStatus.EXCEPTION,
            RecommendationStatus.NO_FEASIBLE_PACKAGE,
        ) and (self.preferred is not None or self.shelf_life is not None):
            raise ValueError("unsuccessful records cannot contain a preferred package or life claim")
        if self.status is RecommendationStatus.VALIDATED_PILOT and (
            self.preferred is None or self.shelf_life is None
        ):
            raise ValueError("a validated pilot requires a package and supported life result")
