import test from "node:test";
import assert from "node:assert/strict";
import { deriveReviewItems } from "../src/review.js";

test("review items are derived from actual report statuses", () => {
  const report = { rows: [
    { status: "exception" }, { status: "not_ready" }, { status: "not_ready" },
    { status: "preliminary_shortlist" },
  ] };
  const items = deriveReviewItems({ backendMode: "audited_report", report });
  assert.deepEqual(items.map((item) => item.action), ["exception", "not_ready", "preliminary_shortlist"]);
  assert.match(items[0].title, /1 input exception/);
  assert.match(items[1].title, /2 rows need evidence/);
  assert.match(items[2].detail, /unresolved approval boundary/);
});

test("a source catalogue is a research update, not a prediction", () => {
  const items = deriveReviewItems({ backendMode: "published_catalogue", publishedApplications: { applications: [{}, {}] } });
  assert.equal(items.length, 1);
  assert.equal(items[0].action, "published");
  assert.match(items[0].detail, /rights review is pending/);
  assert.doesNotMatch(items[0].detail, /recommendation|approved/);
});

test("unconfigured, offline and running states are described without invented results", () => {
  assert.equal(deriveReviewItems({ backendMode: "unconfigured" })[0].action, "setup");
  assert.equal(deriveReviewItems({ backendMode: "unavailable" })[0].action, "import");
  assert.equal(deriveReviewItems({ backendMode: "report_error" })[0].title, "Configured report could not load");
  assert.equal(deriveReviewItems({ backendMode: "scenario_batch", backendBusy: true })[0].title, "Scenario batch running");
  assert.deepEqual(deriveReviewItems({ backendMode: "checking" }), []);
});
