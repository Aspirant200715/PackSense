// TEST_ONLY report rows exercise the visualization. They are not training data.
import test from "node:test";
import assert from "node:assert/strict";
import { actualContext, actualPipeline, STAGES, walkthroughStage } from "../src/pipeline.js";

const base = {
  source_row_number: 2,
  record_id: "TEST_ONLY_ROW",
  food_reference_id: "TEST_ONLY_FOOD",
  scenario: { commodity_type: "TEST_ONLY_COMMODITY" },
  status: "not_ready",
  input_issues: [],
  requirement_gaps: ["oxygen_limit_missing"],
  screening_reason_codes: ["food_needs_missing"],
  screened_candidates: [],
  target_shelf_life_days: 30,
  produce_route_status: "unclassified",
  candidate_screening_allowed: false,
  preliminary_preferred_structure_id: null,
};

test("walkthrough has eight steps and branches without numeric invented outcomes", () => {
  assert.equal(STAGES.length, 8);
  assert.match(walkthroughStage(3, "fresh_produce").output, /no MAP safety certification/);
  assert.match(walkthroughStage(3, "non_respiring").output, /Continue/);
  assert.match(walkthroughStage(6).output, /No material prediction/);
  assert.throws(() => walkthroughStage(8), RangeError);
});

test("actual not-ready row exposes gates rather than claiming approval", () => {
  const stages = actualPipeline(base);
  assert.equal(stages.length, 8);
  assert.equal(stages[2].state, "gaps_recorded");
  assert.deepEqual(stages[2].evidence, ["oxygen_limit_missing"]);
  assert.equal(stages[4].state, "held");
  assert.equal(stages[6].state, "withheld");
});

test("supplier applications appear in the actual trace only as unapproved leads", () => {
  const row = {
    ...base,
    supplier_application_lookup: {
      leads: [{ candidate_id: "TEST_ONLY_SUPPLIER" }],
    },
  };
  const stages = actualPipeline(row);
  assert.equal(stages[4].state, "held");
  assert.match(stages[4].statement, /research leads/);
  assert.match(stages[4].output, /1 unapproved supplier lead/);
  assert.equal(stages[6].state, "withheld");
});

test("actual trace uses reported food, quantity, composition and temperature only", () => {
  const row = {
    ...base,
    scenario: {
      commodity_type: "TEST_ONLY_COMMODITY", net_pack_quantity: 100,
      net_pack_quantity_unit: "g", moisture_content_pct: 8,
      oil_fat_content_pct: 2, pH: 6,
    },
    temperature_exposures: [
      { phase: "storage", temperature_c: 4 },
      { phase: "transport", temperature_c: 8 },
    ],
  };
  const context = actualContext(row);
  assert.deepEqual(context.map(({ value }) => value), [
    "TEST_ONLY_COMMODITY", "100 g", "30 days", "storage 4°C · transport 8°C",
  ]);
  const stages = actualPipeline(row);
  assert.match(stages[0].input, /TEST_ONLY_COMMODITY · 100 g/);
  assert.match(stages[0].check, /storage 4°C · transport 8°C/);
  assert.match(stages[2].input, /Moisture 8% · Fat 2% · pH 6/);
  assert.match(stages[2].check, /transport 8°C/);
});

test("missing source facts remain visibly unreported", () => {
  const row = { ...base, scenario: null, target_shelf_life_days: null, temperature_exposures: [] };
  assert.deepEqual(actualContext(row).map(({ value }) => value), [
    "Not validated or not reported", "Not reported", "Not reported", "Not reported",
  ]);
  assert.match(actualPipeline(row)[2].input, /food composition not projected/);
});

test("exception stops scenario-specific stages", () => {
  const stages = actualPipeline({ ...base, status: "exception", input_issues: [{ code: "missing_value" }] });
  assert.equal(stages[1].state, "held");
  assert.equal(stages[2].state, "not_reached");
  assert.equal(stages[5].state, "not_reached");
  assert.equal(stages[6].state, "withheld");
});

test("a shortlisted package remains preliminary", () => {
  const stages = actualPipeline({
    ...base,
    status: "preliminary_shortlist",
    produce_route_status: "confirmed_non_respiring",
    candidate_screening_allowed: true,
    screened_candidates: [{ structure_id: "TEST_ONLY_STRUCTURE", status: "eligible_for_shortlist" }],
    preliminary_preferred_structure_id: "TEST_ONLY_STRUCTURE",
  });
  assert.equal(stages[3].state, "bypassed");
  assert.equal(stages[4].state, "screened");
  assert.equal(stages[5].state, "preliminary");
  assert.equal(stages[6].state, "withheld");
});
