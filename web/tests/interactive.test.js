import test from "node:test";
import assert from "node:assert/strict";
import { scenarioPayload, validateFoodLookup } from "../src/interactive.js";

function lookup() {
  return {
    contract_version: "food-lookup-v1", food_master_sha256: "a".repeat(64),
    total_matches: 1, form_ready_matches: 1,
    foods: [{
      food_reference_id: "TEST_ONLY_FOOD", commodity_type: "TEST_ONLY_NAME",
      food_group: "TEST_ONLY_GROUP", form_ready: true,
      missing_reference_properties: [], moisture_content_pct: 90,
      oil_fat_content_pct: 1, pH: 6.2,
      pH_basis: "Reported reference value; not product measurement",
      pH_evidence: "reported_reference", respiration_rate: 270,
      respiration_rate_unit: "mg CO2/kg/h", respiration_reference_temperature_c: 20,
      source_citations: "TEST_ONLY https://example.invalid/food",
    }],
  };
}

test("accepts a sourced food lookup with explicit reference completeness", () => {
  assert.equal(validateFoodLookup(lookup()).foods[0].food_reference_id, "TEST_ONLY_FOOD");
  const incomplete = lookup();
  incomplete.foods[0].pH = null;
  incomplete.foods[0].pH_evidence = "missing";
  incomplete.foods[0].form_ready = false;
  incomplete.foods[0].missing_reference_properties = ["pH"];
  incomplete.form_ready_matches = 0;
  assert.equal(validateFoodLookup(incomplete).foods[0].form_ready, false);
});

test("rejects invented readiness and invalid source values", () => {
  const invalid = lookup();
  invalid.foods[0].pH = null;
  assert.throws(() => validateFoodLookup(invalid), /completeness/);
  invalid.foods[0].pH = Infinity;
  assert.throws(() => validateFoodLookup(invalid), /property/);
});

test("form values become a one-scenario payload without editable food properties", () => {
  const values = {
    desired_shelf_life_days: "5", storage_type: "chilled", storage_temperature_c: "4",
    storage_relative_humidity_pct: "90", transport_mode: "road",
    transport_duration_hours: "8", transport_temperature_c: "5",
    transport_max_temperature_c: "9", transport_handling_severity: "medium",
    net_pack_quantity: "150", net_pack_quantity_unit: "g",
  };
  const payload = scenarioPayload(values, lookup().foods[0], "a".repeat(64));
  assert.equal(payload.net_pack_quantity, 150);
  assert.equal(payload.food_reference_id, "TEST_ONLY_FOOD");
  assert.equal(Object.hasOwn(payload, "pH"), false);
  assert.throws(() => scenarioPayload({ ...values, net_pack_quantity: "" }, lookup().foods[0], "a".repeat(64)), /valid net pack quantity/);
});
