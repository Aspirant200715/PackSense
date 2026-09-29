import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { validateDemoEvidence } from "../src/demo.js";
import { parseDecisionReport } from "../src/report.js";

const report = parseDecisionReport(readFileSync(new URL("../demo/report.json", import.meta.url), "utf8"));
const evidence = JSON.parse(readFileSync(new URL("../demo/evidence.json", import.meta.url), "utf8"));

test("published demo decisions retain the reviewed food and supplier sources", () => {
  assert.equal(validateDemoEvidence(evidence, report), evidence);
  assert.deepEqual(report.rows.map((row) => [row.record_id, row.status]), [
    ["DEMO-ASPARAGUS-150G", "not_ready"],
    ["DEMO-BROCCOLI-400G", "not_ready"],
  ]);
  assert.equal(report.model.prediction_available, false);
  assert.equal(report.recommendation_release_status, "withheld");
});

test("a demo citation cannot be paired with a different report", () => {
  const changed = structuredClone(evidence);
  changed.trace.food_master_sha256 = "0".repeat(64);
  assert.throws(() => validateDemoEvidence(changed, report));
});
