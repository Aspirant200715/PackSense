// TEST_ONLY UI contract objects. These are never packaging or training data.
import test from "node:test";
import assert from "node:assert/strict";
import { parseDecisionReport, readableCode, summarizeReport, validateDecisionReport } from "../src/report.js";

function decision(status = "not_ready") {
  return {
    source_row_number: 2,
    record_id: "TEST_ONLY_SCENARIO",
    food_reference_id: status === "exception" ? null : "TEST_ONLY_FOOD",
    scenario: status === "exception" ? null : {
      commodity_type: "TEST_ONLY_FOOD",
      moisture_content_pct: 5,
      oil_fat_content_pct: 3,
      pH: 6,
      net_pack_quantity: 100,
      net_pack_quantity_unit: "g",
      storage_type: "chilled",
      transport_mode: "road",
      transport_handling_severity: "medium",
      respiration_rate: null,
      respiration_rate_unit: null,
      respiration_reference_temperature_c: null,
    },
    status,
    input_issues: status === "exception" ? [{ field: "pH", code: "missing_value", message: "Required." }] : [],
    requirement_gaps: status === "not_ready" ? ["oxygen_limit_missing"] : [],
    screening_reason_codes: [],
    warnings: [],
    target_shelf_life_days: status === "exception" ? null : 30,
    produce_route_status: status === "exception" ? null : "unclassified",
    candidate_screening_allowed: status === "exception" ? null : false,
    temperature_exposures: status === "exception" ? [] : [{ phase: "storage", temperature_c: 4, relative_humidity_pct: 80 }],
    screened_candidates: status === "preliminary_shortlist" ? [{ structure_id: "TEST_ONLY_STRUCTURE", status: "eligible_for_shortlist", pack_format: "TEST_ONLY_FORMAT", reason_codes: [], layers: [], protection_rank: 1 }] : [],
    preliminary_preferred_structure_id: status === "preliminary_shortlist" ? "TEST_ONLY_STRUCTURE" : null,
    recommended_structure_id: null,
    material_prediction: null,
    predicted_shelf_life_days: null,
    package_feasible: false,
  };
}

function report(rows = [decision()]) {
  return {
    contract_version: "frontend-decision-v1",
    source_batch_version: "basic-recommendation-batch-v1",
    model: { task: "material_suitability_ranking", status: "not_deployed", prediction_available: false, model_version: null },
    recommendation_release_status: "withheld",
    trace: {
      scenario_sha256: "a".repeat(64),
      food_master_sha256: "b".repeat(64),
      material_master_sha256: "c".repeat(64),
      route_register_sha256: null,
      assessment_register_sha256: null,
      structure_catalogue_sha256: null,
      structure_review_register_sha256: null,
      transfer_register_sha256: null,
      public_candidate_catalogue_sha256: null,
    },
    total_rows: rows.length,
    rows,
  };
}

test("accepts a conservative backend-shaped report", () => {
  const source = report([decision("not_ready"), { ...decision("exception"), source_row_number: 3 }, { ...decision("preliminary_shortlist"), source_row_number: 4 }]);
  assert.equal(parseDecisionReport(JSON.stringify(source)).rows[0].scenario.commodity_type, "TEST_ONLY_FOOD");
  assert.deepEqual(summarizeReport(parseDecisionReport(JSON.stringify(source))), {
    total: 3, exception: 1, not_ready: 1, preliminary_shortlist: 1,
  });
});

test("rejects a false prediction or release claim", () => {
  const source = report();
  source.rows[0].material_prediction = "TEST_ONLY_STRUCTURE";
  assert.throws(() => validateDecisionReport(source), /prediction or feasibility claim/);
  source.rows[0].material_prediction = null;
  source.recommendation_release_status = "released";
  assert.throws(() => validateDecisionReport(source), /released recommendation/);
});

test("rejects an inconsistent shortlist and row count", () => {
  const source = report([decision("preliminary_shortlist")]);
  source.rows[0].screened_candidates = [];
  assert.throws(() => validateDecisionReport(source), /inconsistent shortlist/);
  source.rows[0] = decision();
  source.total_rows = 2;
  assert.throws(() => validateDecisionReport(source), /row count/);
});

test("rejects unsupported version, malformed JSON and duplicate source rows", () => {
  assert.throws(() => parseDecisionReport("not json"), /not valid JSON/);
  assert.throws(() => parseDecisionReport(JSON.stringify({ batch_version: "basic-recommendation-batch-v1" })), /Convert it with packsense.frontend_contract/);
  const source = report();
  source.contract_version = "frontend-decision-v2";
  assert.throws(() => validateDecisionReport(source), /not a frontend-decision-v1/);
  const duplicate = report([decision(), decision()]);
  assert.throws(() => validateDecisionReport(duplicate), /duplicates a source row/);
});

test("rejects a malformed food profile and accepts an older report without it", () => {
  const source = report();
  source.rows[0].scenario.commodity_type = "";
  assert.throws(() => validateDecisionReport(source), /no commodity name/);
  delete source.rows[0].scenario;
  assert.equal(validateDecisionReport(source).rows[0].scenario, undefined);
});

test("rejects an invalid source fingerprint", () => {
  const source = report();
  source.trace.food_master_sha256 = "unknown";
  assert.throws(() => validateDecisionReport(source), /source fingerprint is invalid/);
});

test("rejects unsupported route and screening permission values", () => {
  const source = report();
  source.rows[0].produce_route_status = "approved_produce";
  assert.throws(() => validateDecisionReport(source), /invalid produce route status/);
  source.rows[0].produce_route_status = "unclassified";
  source.rows[0].candidate_screening_allowed = "yes";
  assert.throws(() => validateDecisionReport(source), /invalid screening permission/);
});

test("turns machine reason codes into readable labels without changing the code", () => {
  assert.equal(readableCode("oxygen_limit_missing"), "Oxygen limit missing");
  assert.equal(readableCode(""), "Unspecified reason");
});
