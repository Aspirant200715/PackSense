import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_SAVED_REPORT_CHARS, readReport, readWorkspace, writeReport, writeWorkspace,
} from "../src/persistence.js";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

test("workspace and report snapshots survive a new reader", () => {
  const storage = memoryStorage();
  const workspace = { entered: true, view: "evaluate", form: { desired_shelf_life_days: "5" } };
  const report = { origin: "browser", label: "Submitted scenario", report: { rows: [{ record_id: "A" }] } };
  assert.equal(writeWorkspace(storage, workspace), true);
  assert.equal(writeReport(storage, report), "saved");
  assert.deepEqual(readWorkspace(storage), { ...workspace, version: 1 });
  assert.deepEqual(readReport(storage), { ...report, version: 1 });
});

test("storage failure and oversized reports do not stop the workspace", () => {
  const unavailable = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(readWorkspace(unavailable), null);
  assert.equal(readReport(unavailable), null);
  assert.equal(writeWorkspace(unavailable, { entered: true }), false);
  assert.equal(writeReport(unavailable, { origin: "browser", report: {} }), "unavailable");
  const storage = memoryStorage();
  assert.equal(writeReport(storage, { origin: "browser", report: { rows: [] } }), "saved");
  assert.equal(writeReport(storage, {
    origin: "browser", report: { large: "x".repeat(MAX_SAVED_REPORT_CHARS) },
  }), "too_large");
  assert.equal(readReport(storage), null, "an unsaved new report must not restore an older result");
});
