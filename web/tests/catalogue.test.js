import test from "node:test";
import assert from "node:assert/strict";
import { validatePublishedApplications } from "../src/catalogue.js";

function catalogue() {
  return {
    contract_version: "published-applications-v1",
    catalogue_id: "TEST_ONLY_CATALOGUE",
    catalogue_sha256: "a".repeat(64),
    model_prediction_available: false,
    package_approval_available: false,
    applications: [{
      candidate_id: "TEST_ONLY_BAG", product_code: "TEST_ONLY_CODE",
      pack_format: "heat-seal bag", food: "TEST_ONLY_FOOD",
      quantity: 400, quantity_unit: "g",
      storage_temperature_min_c: 1, storage_temperature_max_c: 10,
      excursion_max_c: 25, excursion_max_hours: 8,
      source_publisher: "TEST_ONLY_PUBLISHER", source_url: "https://example.org/product",
      source_locator: "TEST_ONLY_ROW", source_rights_review_status: "pending",
    }],
  };
}

test("accepts a sourced published use without claiming prediction", () => {
  assert.equal(validatePublishedApplications(catalogue()).applications[0].quantity, 400);
});

test("rejects claims, unsafe links and incomplete use conditions", () => {
  const source = catalogue();
  source.model_prediction_available = true;
  assert.throws(() => validatePublishedApplications(source), /unsupported claim/);
  source.model_prediction_available = false;
  source.applications[0].source_url = "javascript:alert(1)";
  assert.throws(() => validatePublishedApplications(source), /unsafe source URL/);
  source.applications[0].source_url = "https://example.org/product";
  source.applications[0].excursion_max_hours = null;
  assert.throws(() => validatePublishedApplications(source), /excursion conditions/);
});
