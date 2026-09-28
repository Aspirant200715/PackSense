"""TEST_ONLY batch objects verify the pipeline; they are not training records."""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.candidate_transfer import FinishedPackageTransferEvidence
from packsense.contracts import (
    EvidenceBasis, FoodReference, HandlingSeverity, PackageStructure,
    ScenarioInput, StorageType, StructureLayer,
)
from packsense.enrichment import enrich_scenarios
from packsense.gas_balance import FinishedPackageGasObservation
from packsense.ingestion import IngestionIssue, ParsedScenarioRow, ScenarioAudit
from packsense.masters import FoodMasterEntry, MasterAudit
from packsense.material_model import (
    MODEL_VERSION, MaterialTrainingResult, _engineering_baseline_agreement,
    score_exploratory_candidates,
)
from packsense.produce_route import ProduceRoute, RouteEvidence
from packsense.recommendation_batch import build_batch_recommendations
from packsense.recommendation import screen_package_candidates
from packsense.recommendation_output import summarize_batch
from packsense.respiration import KineticEvidence
from packsense.requirements import (
    AssessmentDecision, ProtectionAssessment, ProtectionMechanism,
    derive_requirement_card, scenario_fingerprint,
)
from packsense.structure_review import (
    CHECK_KINDS, EvidenceCheck, ReviewAttestedStructure, StructureReviewAudit,
)
from packsense.water_balance import FinishedPackageWaterObservation


FOOD_HASH = "a" * 64
MATERIAL_HASH = "b" * 64
CATALOGUE_HASH = "c" * 64
REVIEW_HASH = "d" * 64


def _scenario(record_id="TEST_ONLY_CASE"):
    return ScenarioInput(
        record_id=record_id, commodity_type="TEST_ONLY_FOOD",
        moisture_content_pct=5.0, oil_fat_content_pct=3.0, pH=6.0,
        desired_shelf_life_days=14.0, storage_type=StorageType.CHILLED,
        storage_temperature_c=4.0, storage_relative_humidity_pct=80.0,
        transport_mode="TEST_ONLY_MODE", transport_duration_hours=12.0,
        transport_temperature_c=6.0, transport_max_temperature_c=9.0,
        transport_handling_severity=HandlingSeverity.HIGH,
        net_pack_quantity=100.0, net_pack_quantity_unit="g",
        food_reference_id="TEST_ONLY_FOOD_ID",
    )


def _sources(*scenarios):
    rows = tuple(ParsedScenarioRow(
        index, {"record_id": scenario.record_id}, scenario, (),
    ) for index, scenario in enumerate(scenarios, start=2))
    scenario_audit = ScenarioAudit("TEST_ONLY.csv", "e" * 64, None, (), rows)
    food = FoodReference(
        "TEST_ONLY_FOOD_ID", "TEST_ONLY_FOOD", None, 5.0, 3.0, 6.0,
        "TEST_ONLY_REFERENCE", None, None, None, "TEST_ONLY_SOURCE",
    )
    foods = MasterAudit(
        "TEST_ONLY_food.xlsx", FOOD_HASH, "Food inputs", 1,
        (FoodMasterEntry(2, food, "reported_reference"),), (),
    )
    # The batch function uses the audited material hash. Grade parsing is
    # tested separately by the material importer.
    materials = MasterAudit("TEST_ONLY_material.xlsx", MATERIAL_HASH,
                            "Materials", 1, (object(),), ())
    return scenario_audit, foods, materials


def _route():
    return RouteEvidence(
        "TEST_ONLY_FOOD_ID", ProduceRoute.NON_RESPIRING,
        "TEST_ONLY_ROUTE_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_ROUTE_REVIEW",
    )


def _assessments():
    result = []
    for mechanism, limit in (
        (ProtectionMechanism.OXYGEN_INGRESS, 20.0),
        (ProtectionMechanism.MOISTURE_GAIN, 12.0),
        (ProtectionMechanism.MOISTURE_LOSS, None),
    ):
        result.append(ProtectionAssessment(
            food_reference_id="TEST_ONLY_FOOD_ID", mechanism=mechanism,
            decision=(AssessmentDecision.LIMIT if limit is not None
                      else AssessmentDecision.NOT_REQUIRED),
            max_cumulative_transfer=limit,
            transfer_unit=("mmol_o2_per_pack" if mechanism is ProtectionMechanism.OXYGEN_INGRESS
                           else "g_h2o_per_pack") if limit is not None else None,
            pack_quantity=100.0, pack_quantity_unit="g",
            valid_temperature_min_c=0.0, valid_temperature_max_c=10.0,
            valid_rh_min_pct=0.0, valid_rh_max_pct=100.0,
            assessment_rationale="TEST_ONLY reviewed mechanism",
            source_id=f"TEST_ONLY_{mechanism.value}", source_locator="TEST_ONLY_LOCATOR",
            approval_id=f"TEST_ONLY_APPROVAL_{mechanism.value}",
            evidence_basis=EvidenceBasis.MEASURED,
        ))
    return tuple(result)


def _review():
    structure = PackageStructure(
        "TEST_ONLY_STRUCTURE", "TEST_ONLY pouch",
        (StructureLayer("TEST_ONLY_GRADE", 20.0, "sealant", True),),
        "TEST_ONLY_GRADE", "TEST_ONLY_CONSTRUCTION", "TEST_ONLY_CONTACT",
        ("TEST_ONLY_FOOD",), 0.0, 10.0,
    )
    checks = tuple(EvidenceCheck(
        kind, (structure.structure_source_id if kind == "construction" else
               structure.food_contact_evidence_id if kind == "food_contact" else
               f"TEST_ONLY_{kind.upper()}_SOURCE"),
        "TEST_ONLY_LOCATOR", "e" * 64, "TEST_ONLY_REVIEW",
        "TEST_ONLY_RIGHTS", "pass",
    ) for kind in sorted(CHECK_KINDS))
    reviewed = ReviewAttestedStructure(
        structure, CATALOGUE_HASH, MATERIAL_HASH, REVIEW_HASH,
        "TEST_ONLY_REVIEW", tuple(check.review_id for check in checks), (), checks,
        HandlingSeverity.HIGH,
    )
    return StructureReviewAudit(
        "review_attested", CATALOGUE_HASH, REVIEW_HASH, (reviewed,), (),
    )


def _transfer(card, mechanism, amount):
    unit = ("mmol_o2_per_pack" if mechanism is ProtectionMechanism.OXYGEN_INGRESS
            else "g_h2o_per_pack")
    return FinishedPackageTransferEvidence(
        card.record_id, card.food_reference_id, "TEST_ONLY_STRUCTURE",
        CATALOGUE_HASH, scenario_fingerprint(card), mechanism, amount, unit,
        card.target_shelf_life_days, card.net_pack_quantity,
        card.net_pack_quantity_unit, 0.0, 10.0, 0.0, 100.0,
        f"TEST_ONLY_TRANSFER_{mechanism.value}", "TEST_ONLY_LOCATOR",
        "TEST_ONLY_TRANSFER_REVIEW", EvidenceBasis.MEASURED, None, None,
    )


def _produce_sources(*, catalogue_hash=CATALOGUE_HASH):
    scenario = replace(
        _scenario(), respiration_rate=10.0, respiration_rate_unit="mg CO2/kg/h",
        respiration_reference_temperature_c=4.0,
    )
    scenarios, foods, materials = _sources(scenario)
    original = foods.entries[0]
    foods = replace(foods, entries=(replace(
        original, reference=replace(
            original.reference, respiration_rate=10.0,
            respiration_rate_unit="mg CO2/kg/h",
            respiration_reference_temperature_c=4.0,
        ),
    ),))
    route = RouteEvidence(
        "TEST_ONLY_FOOD_ID", ProduceRoute.RESPIRING,
        "TEST_ONLY_ROUTE_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_REVIEW",
    )
    kinetics = tuple(KineticEvidence(
        "TEST_ONLY_FOOD_ID", value, unit, 4.0, 2.0, 0.0, 10.0,
        5.0, 5.0, f"TEST_ONLY_{unit}", "TEST_ONLY_Q10",
        "TEST_ONLY_LOCATOR", "TEST_ONLY_KINETICS_REVIEW",
        EvidenceBasis.MEASURED, EvidenceBasis.VALIDATED_CORRECTION,
    ) for unit, value in (("mg O2/kg/h", 12.0), ("mg CO2/kg/h", 10.0)))
    exposures = (("storage", 4.0), ("transport", 6.0),
                 ("transport_max_excursion", 9.0))
    gas = tuple(FinishedPackageGasObservation(
        "TEST_ONLY_CASE", "TEST_ONLY_FOOD_ID", "TEST_ONLY_STRUCTURE",
        phase, temperature, 100.0, 100.0, 5.0, 5.0, 20.0, 0.1,
        1.0, -0.5, 3.0, 10.0, "TEST_ONLY_GAS_TRANSFER",
        "TEST_ONLY_GAS_LIMIT", "TEST_ONLY_STRUCTURE_APPROVAL",
        "TEST_ONLY_LOCATOR", "TEST_ONLY_GAS_REVIEW",
        EvidenceBasis.MEASURED, EvidenceBasis.MEASURED, catalogue_hash,
    ) for phase, temperature in exposures)
    water = tuple(FinishedPackageWaterObservation(
        "TEST_ONLY_CASE", "TEST_ONLY_FOOD_ID", "TEST_ONLY_STRUCTURE",
        phase, temperature, 100.0, 0.2, 0.01, -0.3, False, 0.0,
        0.5, 80.0, 1.0, 2.0, "TEST_ONLY_TRANS", "TEST_ONLY_RESP",
        "TEST_ONLY_WATER_TRANSFER", "TEST_ONLY_HEADSPACE",
        "TEST_ONLY_LOCATOR", "TEST_ONLY_WATER_REVIEW", EvidenceBasis.MEASURED,
        catalogue_hash,
    ) for phase, temperature in exposures)
    return scenarios, foods, materials, route, kinetics, gas, water


class BatchRecommendationTests(unittest.TestCase):
    def test_produce_diagnostics_bind_only_to_exact_reviewed_catalogue(self):
        scenarios, foods, materials, route, kinetics, gas, water = _produce_sources()
        materials = replace(materials, entries=(
            SimpleNamespace(grade=SimpleNamespace(material_id="TEST_ONLY_GRADE")),
        ))
        candidates, candidate_hash = load_candidate_catalogue(
            Path(__file__).resolve().parents[1] / "data" /
            "public_catalogue_candidates.v1.json"
        )
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="1" * 64, structure_review=_review(),
            include_grade_reference_comparison=True,
            include_produce_diagnostics=True, kinetics=kinetics,
            kinetics_register_sha256="2" * 64, gas_observations=gas,
            gas_observation_register_sha256="3" * 64,
            water_observations=water, water_observation_register_sha256="4" * 64,
            public_candidates=candidates,
            public_candidate_catalogue_sha256=candidate_hash,
        )
        diagnostic = report["rows"][0]["produce_local_diagnostics"]
        binding = diagnostic["structures"][0]["structure_review_binding"]
        self.assertEqual(binding["status"], "joined")
        self.assertEqual(binding["reason_codes"], [])
        self.assertEqual(binding["catalogue_sha256"], CATALOGUE_HASH)
        self.assertTrue(report["produce_diagnostic_structure_review_joined"])
        self.assertEqual(report["produce_review_bound_structure_count"], 1)
        self.assertEqual(report["rows"][0]["status"], "not_ready")
        self.assertIsNotNone(report["rows"][0]["grade_reference_comparison"])
        self.assertIsNotNone(report["rows"][0]["supplier_application_lookup"])
        self.assertFalse(report["produce_safety_certified"])
        self.assertFalse(binding["produce_safety_certified"])

    def test_legacy_or_changed_produce_observations_do_not_bind(self):
        scenarios, foods, materials, route, kinetics, gas, water = _produce_sources()
        for gas_hash, water_hash, expected in (
            (None, None, "gas_catalogue_binding_missing"),
            ("e" * 64, CATALOGUE_HASH, "gas_catalogue_version_mismatch"),
        ):
            with self.subTest(expected=expected):
                report = build_batch_recommendations(
                    scenarios, foods, materials, routes=(route,),
                    route_register_sha256="1" * 64, structure_review=_review(),
                    include_produce_diagnostics=True, kinetics=kinetics,
                    kinetics_register_sha256="2" * 64,
                    gas_observations=tuple(replace(
                        item, structure_catalogue_sha256=gas_hash,
                    ) for item in gas),
                    gas_observation_register_sha256="3" * 64,
                    water_observations=tuple(replace(
                        item, structure_catalogue_sha256=water_hash,
                    ) for item in water),
                    water_observation_register_sha256="4" * 64,
                )
                binding = report["rows"][0]["produce_local_diagnostics"]["structures"][0][
                    "structure_review_binding"
                ]
                self.assertEqual(binding["status"], "unresolved")
                self.assertIn(expected, binding["reason_codes"])
                self.assertFalse(report["produce_diagnostic_structure_review_joined"])
                self.assertEqual(report["produce_review_unresolved_structure_count"], 1)

    def test_review_scope_and_phase_coverage_are_required_for_binding(self):
        scenarios, foods, materials, route, kinetics, gas, water = _produce_sources()
        narrower = _review()
        reviewed = narrower.reviewed[0]
        narrowed_structure = replace(
            reviewed.structure, service_temperature_max_c=8.0,
        )
        narrower = replace(narrower, reviewed=(replace(
            reviewed, structure=narrowed_structure,
        ),))
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="1" * 64, structure_review=narrower,
            include_produce_diagnostics=True, kinetics=kinetics,
            kinetics_register_sha256="2" * 64, gas_observations=gas[:-1],
            gas_observation_register_sha256="3" * 64,
            water_observations=water, water_observation_register_sha256="4" * 64,
        )
        binding = report["rows"][0]["produce_local_diagnostics"]["structures"][0][
            "structure_review_binding"
        ]
        self.assertIn("reviewed_service_temperature_out_of_scope", binding["reason_codes"])
        self.assertIn("gas_observation_missing", binding["reason_codes"])
        self.assertFalse(report["produce_diagnostic_structure_review_joined"])

    def test_reviewed_food_and_material_version_must_match(self):
        scenarios, foods, materials, route, kinetics, gas, water = _produce_sources()
        original = _review()
        reviewed = original.reviewed[0]
        changed = replace(original, reviewed=(replace(
            reviewed,
            structure=replace(reviewed.structure,
                              compatible_food_scope=("TEST_ONLY_OTHER_FOOD",)),
            material_master_sha256="f" * 64,
        ),))
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="1" * 64, structure_review=changed,
            include_produce_diagnostics=True, kinetics=kinetics,
            kinetics_register_sha256="2" * 64, gas_observations=gas,
            gas_observation_register_sha256="3" * 64,
            water_observations=water, water_observation_register_sha256="4" * 64,
        )
        binding = report["rows"][0]["produce_local_diagnostics"]["structures"][0][
            "structure_review_binding"
        ]
        self.assertIn("reviewed_food_scope_mismatch", binding["reason_codes"])
        self.assertIn("material_master_version_mismatch", binding["reason_codes"])
        self.assertFalse(report["produce_diagnostic_structure_review_joined"])

    def test_observed_gas_limit_breach_is_visible_without_approving_package(self):
        scenarios, foods, materials, route, kinetics, gas, water = _produce_sources()
        kinetics = tuple(replace(item, reference_o2_pct=2.0) for item in kinetics)
        gas = tuple(replace(item, initial_o2_pct=2.0) for item in gas)
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="1" * 64, structure_review=_review(),
            include_produce_diagnostics=True, kinetics=kinetics,
            kinetics_register_sha256="2" * 64, gas_observations=gas,
            gas_observation_register_sha256="3" * 64,
            water_observations=water, water_observation_register_sha256="4" * 64,
        )
        diagnostic = report["rows"][0]["produce_local_diagnostics"]
        self.assertTrue(diagnostic["observed_initial_gas_limit_violation"])
        self.assertEqual(diagnostic["structures"][0]["violating_phases"], [
            "storage", "transport", "transport_max_excursion",
        ])
        self.assertEqual(report["produce_observed_initial_gas_limit_violation_rows"], 1)
        self.assertTrue(report["produce_diagnostic_structure_review_joined"])
        self.assertEqual(report["rows"][0]["status"], "not_ready")
        self.assertFalse(report["produce_safety_certified"])

    def test_optional_produce_audit_keeps_route_and_package_status_separate(self):
        scenarios, foods, materials = _sources(_scenario())
        unresolved = build_batch_recommendations(
            scenarios, foods, materials, include_produce_diagnostics=True,
        )
        self.assertEqual(unresolved["rows"][0]["produce_local_diagnostics"]["status"],
                         "unresolved_route")
        self.assertEqual(unresolved["rows"][0]["status"], "not_ready")
        self.assertFalse(unresolved["produce_safety_certified"])
        self.assertFalse(unresolved["produce_diagnostic_structure_review_joined"])

        non_respiring = build_batch_recommendations(
            scenarios, foods, materials, routes=(_route(),),
            route_register_sha256="1" * 64, include_produce_diagnostics=True,
        )
        self.assertEqual(non_respiring["rows"][0]["produce_local_diagnostics"]["status"],
                         "not_applicable")
        self.assertEqual(non_respiring["rows"][0]["status"], "not_ready")
        self.assertEqual(non_respiring["produce_local_unresolved_rows"], 0)

    def test_respiring_water_observation_stays_local_and_unresolved_without_gas(self):
        scenario = replace(
            _scenario(), respiration_rate=10.0, respiration_rate_unit="mg CO2/kg/h",
            respiration_reference_temperature_c=4.0,
        )
        scenarios, foods, materials = _sources(scenario)
        original = foods.entries[0]
        foods = replace(foods, entries=(replace(
            original, reference=replace(
                original.reference, respiration_rate=10.0,
                respiration_rate_unit="mg CO2/kg/h",
                respiration_reference_temperature_c=4.0,
            ),
        ),))
        route = RouteEvidence(
            "TEST_ONLY_FOOD_ID", ProduceRoute.RESPIRING,
            "TEST_ONLY_ROUTE_SOURCE", "TEST_ONLY_LOCATOR", "TEST_ONLY_REVIEW",
        )
        water = FinishedPackageWaterObservation(
            "TEST_ONLY_CASE", "TEST_ONLY_FOOD_ID", "TEST_ONLY_STRUCTURE",
            "storage", 4.0, 100.0, 0.2, 0.01, -0.1, False, 0.0, 0.5,
            80.0, 2.0, 1.0, "TEST_ONLY_TRANS", "TEST_ONLY_RESP",
            "TEST_ONLY_PACK", "TEST_ONLY_HEADSPACE", "TEST_ONLY_LOCATOR",
            "TEST_ONLY_APPROVAL", EvidenceBasis.MEASURED,
        )
        report = build_batch_recommendations(
            scenarios, foods, materials, routes=(route,),
            route_register_sha256="1" * 64,
            include_produce_diagnostics=True, water_observations=(water,),
            water_observation_register_sha256="2" * 64,
        )
        diagnostic = report["rows"][0]["produce_local_diagnostics"]
        self.assertEqual(diagnostic["status"], "unresolved")
        storage = diagnostic["structures"][0]["phases"][0]
        self.assertEqual(storage["gas"]["status"], "unresolved")
        self.assertAlmostEqual(storage["water"]["local_vapor_input_g_h"], 0.11)
        self.assertEqual(report["rows"][0]["status"], "not_ready")
        self.assertFalse(report["package_feasible"])
        self.assertFalse(report["shelf_life_predicted"])

    def test_produce_evidence_needs_hash_and_opt_in(self):
        sources = _sources(_scenario())
        with self.assertRaisesRegex(ValueError, "source register hash"):
            build_batch_recommendations(
                *sources, include_produce_diagnostics=True,
                water_observations=(object(),),
            )
        with self.assertRaisesRegex(ValueError, "include_produce_diagnostics"):
            build_batch_recommendations(
                *sources, water_observation_register_sha256="2" * 64,
            )

    def test_public_supplier_lookup_does_not_change_recommendation_gate(self):
        scenario = replace(
            _scenario(), commodity_type="Broccoli, raw",
            net_pack_quantity=400.0, transport_temperature_c=8.0,
            transport_max_temperature_c=25.0, transport_duration_hours=8.0,
        )
        scenarios, foods, materials = _sources(scenario)
        original = foods.entries[0]
        foods = replace(foods, entries=(replace(
            original, reference=replace(original.reference,
                                        commodity_type="Broccoli, raw"),
        ),))
        catalogue_path = (Path(__file__).resolve().parents[1] / "data" /
                          "public_catalogue_candidates.v1.json")
        candidates, digest = load_candidate_catalogue(catalogue_path)
        report = build_batch_recommendations(
            scenarios, foods, materials, public_candidates=candidates,
            public_candidate_catalogue_sha256=digest,
            pilot_candidate_id="SUMITOMO-PPLUS-VY7K9",
        )
        self.assertEqual("not_ready", report["rows"][0]["status"])
        self.assertEqual(1, report["supplier_application_lead_count"])
        lead = report["rows"][0]["supplier_application_lookup"]["leads"][0]
        self.assertEqual("SUMITOMO-PPLUS-VY7K9", lead["candidate_id"])
        self.assertIn("food_identity_requires_review", lead["reason_codes"])
        pilot = report["rows"][0]["pilot_candidate_audit"]
        self.assertEqual("SUMITOMO-PPLUS-VY7K9", report["pilot_candidate_id"])
        self.assertEqual(1, report["pilot_candidate_audit_rows"])
        self.assertEqual("published_use_unresolved_or_outside_scope",
                         pilot["application_status"])
        self.assertFalse(pilot["recommendation_eligible"])
        self.assertIsNone(report["rows"][0]["recommendation"][
            "preliminary_preferred_structure_id"])

    def test_pilot_candidate_requires_catalogue_and_exact_id(self):
        with self.assertRaisesRegex(ValueError, "requires a public candidate catalogue"):
            build_batch_recommendations(
                *_sources(_scenario()), pilot_candidate_id="POUCHDIRECT-SKU179",
            )
        catalogue_path = (Path(__file__).resolve().parents[1] / "data" /
                          "public_catalogue_candidates.v1.json")
        candidates, digest = load_candidate_catalogue(catalogue_path)
        with self.assertRaisesRegex(ValueError, "unknown public candidate_id"):
            build_batch_recommendations(
                *_sources(_scenario()), public_candidates=candidates,
                public_candidate_catalogue_sha256=digest,
                pilot_candidate_id="TEST_ONLY_UNKNOWN",
            )

    def test_no_external_registers_reports_not_ready(self):
        report = build_batch_recommendations(*_sources(_scenario()))
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(report["not_ready_rows"], 1)
        self.assertEqual(report["preliminary_shortlist_rows"], 0)
        self.assertEqual(report["rows"][0]["status"], "not_ready")
        self.assertIn("food_requirements_or_produce_route_incomplete",
                      report["rows"][0]["recommendation"]["reason_codes"])
        self.assertFalse(report["package_feasible"])
        self.assertFalse(report["shelf_life_predicted"])

    def test_complete_food_card_still_requires_structure_review(self):
        report = build_batch_recommendations(
            *_sources(_scenario()), routes=(_route(),), route_register_sha256="1" * 64,
            assessments=_assessments(), assessment_register_sha256="2" * 64,
        )
        self.assertEqual(report["rows"][0]["recommendation"]["reason_codes"],
                         ["complete_structure_review_missing"])
        self.assertEqual(report["structure_review_status"], "missing")

    def test_batch_joins_exact_scenario_and_preserves_input_exception(self):
        first, second = _scenario(), _scenario("TEST_ONLY_OTHER_CASE")
        scenarios, foods, materials = _sources(first, second)
        issue = IngestionIssue(4, "TEST_ONLY_INVALID", "pH", "missing_value", "required")
        scenarios = replace(scenarios, rows=(*scenarios.rows, ParsedScenarioRow(
            4, {"record_id": "TEST_ONLY_INVALID"}, None, (issue,),
        )))
        assessments = _assessments()
        enriched = enrich_scenarios(scenarios, foods, (_route(),), "1" * 64)
        first_card = derive_requirement_card(enriched.rows[0].enriched, assessments)
        transfers = (
            _transfer(first_card, ProtectionMechanism.OXYGEN_INGRESS, 5.0),
            _transfer(first_card, ProtectionMechanism.MOISTURE_GAIN, 6.0),
        )
        catalogue_path = (Path(__file__).resolve().parents[1] / "data" /
                          "public_catalogue_candidates.v1.json")
        candidates, digest = load_candidate_catalogue(catalogue_path)
        report = build_batch_recommendations(
            scenarios, foods, materials,
            routes=(_route(),), route_register_sha256="1" * 64,
            assessments=assessments, assessment_register_sha256="2" * 64,
            structure_review=_review(), transfer_evidence=transfers,
            transfer_register_sha256="3" * 64,
            public_candidates=candidates, public_candidate_catalogue_sha256=digest,
            pilot_candidate_id="POUCHDIRECT-SKU179",
        )
        self.assertEqual(report["total_rows"], 3)
        self.assertEqual(report["preliminary_shortlist_rows"], 1)
        self.assertEqual(report["not_ready_rows"], 1)
        self.assertEqual(report["exception_rows"], 1)
        self.assertEqual(report["preliminary_preferred_rows"], 1)
        self.assertEqual(report["rows"][0]["recommendation"]
                         ["preliminary_preferred_structure_id"], "TEST_ONLY_STRUCTURE")
        self.assertEqual(report["rows"][0]["recommendation"]
                         ["scenario_source_sha256"], scenarios.source_sha256)
        self.assertEqual(report["rows"][0]["food_reference_row"], 2)
        self.assertEqual(report["rows"][1]["recommendation"]["candidates"][0]
                         ["reason_codes"], ["finished_package_transfer_missing"])
        self.assertIsNone(report["rows"][2]["recommendation"])
        self.assertIsNone(report["rows"][2]["pilot_candidate_audit"])
        self.assertEqual(2, report["pilot_candidate_audit_rows"])
        self.assertFalse(report["rows"][0]["pilot_candidate_audit"]["recommendation_eligible"])
        self.assertEqual(report["rows"][2]["issues"][0]["code"], "missing_value")
        self.assertEqual(report["transfer_register_sha256"], "3" * 64)
        json.dumps(report, allow_nan=False)
        summary = summarize_batch(report)
        self.assertEqual([row["status"] for row in summary],
                         ["preliminary_shortlist", "not_ready", "exception"])
        self.assertEqual(summary[0]["preliminary_preferred_total_thickness_um"], 20.0)

    def test_rejected_master_rows_and_unversioned_evidence_are_refused(self):
        scenarios, foods, materials = _sources(_scenario())
        with self.assertRaisesRegex(ValueError, "no rejected rows"):
            build_batch_recommendations(
                scenarios, replace(foods, issues=(object(),)), materials,
            )
        with self.assertRaisesRegex(ValueError, "register hash"):
            build_batch_recommendations(
                scenarios, foods, materials, routes=(_route(),),
            )


class _TestOnlyEstimator:
    classes_ = (0, 1)

    def predict_proba(self, matrix):
        return np.asarray([[0.1, 0.9]] * len(matrix))


class ExploratoryScoringBoundaryTests(unittest.TestCase):
    def _inputs(self):
        scenarios, foods, _ = _sources(_scenario())
        enriched = enrich_scenarios(scenarios, foods, (_route(),), "1" * 64).rows[0].enriched
        card = derive_requirement_card(enriched, _assessments())
        transfers = (
            _transfer(card, ProtectionMechanism.OXYGEN_INGRESS, 5.0),
            _transfer(card, ProtectionMechanism.MOISTURE_GAIN, 6.0),
        )
        review = _review()
        shortlist = screen_package_candidates(
            card, "TEST_ONLY_FOOD", review, transfers,
            current_material_master_sha256=MATERIAL_HASH,
            scenario_source_sha256=scenarios.source_sha256,
        )
        training = MaterialTrainingResult({
            "model_version": MODEL_VERSION,
            "status": "exploratory_test_evaluated",
            "model_trained": True,
            "model_evaluated": True,
            "model_validated": False,
            "source_and_rights_review_approved": True,
            "release_status": "withheld_pending_external_performance_and_gate_review",
            "test": {"brier_baseline_beaten": True},
            "register_sha256": "a" * 64,
            "split_manifest_sha256": "b" * 64,
            "source_hashes": {
                "scenario_sha256": scenarios.source_sha256,
                "food_master_sha256": FOOD_HASH,
                "material_master_sha256": MATERIAL_HASH,
                "structure_catalogue_sha256": CATALOGUE_HASH,
                "structure_review_sha256": REVIEW_HASH,
            },
        }, _TestOnlyEstimator())
        grades = {"TEST_ONLY_GRADE": SimpleNamespace(material_family="TEST_ONLY_FILM")}
        return training, enriched, card, shortlist, review, grades

    def _score(self, values):
        return score_exploratory_candidates(
            *values, material_master_sha256=MATERIAL_HASH,
        )

    def test_offline_score_cannot_change_engineering_preference(self):
        values = self._inputs()
        preferred = values[3].preferred_structure_id
        report = self._score(values)
        self.assertEqual("exploratory_scores_withheld", report["status"])
        self.assertEqual(0.9, report["scores"][0]["exploratory_suitable_label_score"])
        self.assertEqual(preferred, report["engineering_preferred_structure_id"])
        self.assertIsNone(report["model_preferred_structure_id"])
        self.assertFalse(report["recommendation_changed"])
        self.assertFalse(report["package_feasible"])
        self.assertEqual(preferred, values[3].preferred_structure_id)

    def test_actual_card_fingerprint_binds_offline_engineering_comparison(self):
        training, enriched, _, shortlist, review, _ = self._inputs()
        label = SimpleNamespace(
            scenario_record_id="TEST_ONLY_CASE", food_reference_id="TEST_ONLY_FOOD_ID",
            structure_id="TEST_ONLY_STRUCTURE", decision="suitable",
        )
        result = _engineering_baseline_agreement(
            [(label, {})], {label.scenario_record_id: enriched},
            {label.scenario_record_id: shortlist},
            {item.structure.structure_id: item for item in review.reviewed},
            training.report["source_hashes"],
        )
        self.assertEqual(result["status"], "complete_explicit_pair_coverage")
        self.assertEqual(result["cross_tab_counts"]["eligible_for_shortlist_suitable"], 1)
        self.assertTrue(result["full_scenario_batch_version_verified_by_code"])

    def test_no_model_or_failed_test_baseline_refuses_scoring(self):
        values = self._inputs()
        values = (replace(values[0], estimator=None), *values[1:])
        self.assertEqual("not_ready", self._score(values)["status"])
        values = self._inputs()
        training = replace(values[0], report={
            **values[0].report, "test": {"brier_baseline_beaten": False},
        })
        self.assertEqual("not_ready", self._score((training, *values[1:]))["status"])

    def test_changed_source_or_scenario_refuses_scoring(self):
        values = self._inputs()
        source_changed = score_exploratory_candidates(
            *values, material_master_sha256="f" * 64,
        )
        self.assertEqual("model_and_current_source_versions_differ",
                         source_changed["reason_codes"][0])
        changed = (*values[:3], replace(values[3], scenario_fingerprint="f" * 64),
                   *values[4:])
        self.assertEqual("engineering_shortlist_scenario_mismatch",
                         self._score(changed)["reason_codes"][0])
        stale_batch = (*values[:3], replace(values[3], scenario_source_sha256="f" * 64),
                       *values[4:])
        self.assertEqual("model_and_current_source_versions_differ",
                         self._score(stale_batch)["reason_codes"][0])

    def test_unresolved_transfer_cannot_be_scored(self):
        values = self._inputs()
        candidate = replace(values[3].candidates[0], transfer_checks=())
        changed = (*values[:3], replace(values[3], candidates=(candidate,)),
                   *values[4:])
        self.assertEqual("eligible_candidate_transfer_gate_mismatch",
                         self._score(changed)["reason_codes"][0])

    def test_invalid_probability_cannot_be_reported(self):
        class InvalidEstimator(_TestOnlyEstimator):
            def predict_proba(self, matrix):
                return np.asarray([[float("nan"), 1.0]] * len(matrix))

        values = self._inputs()
        changed = (replace(values[0], estimator=InvalidEstimator()), *values[1:])
        self.assertEqual("model_probability_output_invalid",
                         self._score(changed)["reason_codes"][0])


if __name__ == "__main__":
    unittest.main()
