import assert from "node:assert/strict";
import test from "node:test";
import { groupSourceOptions } from "../src/options.js";

const lead = (candidate_id, food_name_match, reason_codes, application_status) => ({
  candidate_id, food_name_match, reason_codes, application_status,
});

test("source options separate exact conditions, name review, and mismatches", () => {
  const exact = lead("TEST_ONLY_EXACT", "exact_name", [], "published_food_quantity_temperature_match_unverified");
  const related = lead("TEST_ONLY_RELATED", "raw_name_variant_unreviewed", ["food_identity_requires_review"], "unresolved_or_outside_published_use");
  const outside = lead("TEST_ONLY_OUTSIDE", "exact_name", ["pack_quantity_outside_published_use"], "unresolved_or_outside_published_use");
  const mixed = lead("TEST_ONLY_MIXED", "raw_name_variant_unreviewed", ["food_identity_requires_review", "storage_temperature_outside_published_use"], "unresolved_or_outside_published_use");
  const grouped = groupSourceOptions([outside, related, mixed, exact]);
  assert.deepEqual(grouped.exactConditions, [exact]);
  assert.deepEqual(grouped.relatedFoodName, [related]);
  assert.deepEqual(grouped.outsidePublishedUse, [outside, mixed]);
});

test("absence of source claims does not become an inferred option", () => {
  assert.deepEqual(groupSourceOptions(), {
    exactConditions: [], relatedFoodName: [], outsidePublishedUse: [],
  });
});
