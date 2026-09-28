// Optional no-dependency browser smoke check against a running local service.
// Start headless Chrome with --remote-debugging-port=9333 and set
// PACKSENSE_CDP_URL if it uses a different port.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";

const cdpUrl = process.env.PACKSENSE_CDP_URL || "http://127.0.0.1:9333";
const appUrl = process.env.PACKSENSE_WEB_URL || "http://127.0.0.1:4173/";
const viewportWidth = Number(process.env.PACKSENSE_VIEWPORT_WIDTH || 390);
const viewportHeight = Number(process.env.PACKSENSE_VIEWPORT_HEIGHT || 844);
const tabResponse = await fetch(`${cdpUrl}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" });
assert.equal(tabResponse.status, 200, "Chrome DevTools must be running");
const tab = await tabResponse.json();
const socket = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 0;
const pending = new Map();
const exceptions = [];
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails.text);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function command(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

function testOnlyReport() {
  const row = (sourceRow, status) => ({
    source_row_number: sourceRow,
    record_id: "TEST_ONLY_" + status,
    food_reference_id: status === "exception" ? null : "TEST_ONLY_FOOD",
    scenario: null,
    status,
    input_issues: status === "exception" ? [{ field: "pH", code: "missing_value", message: "TEST_ONLY required" }] : [],
    requirement_gaps: status === "not_ready" ? ["oxygen_limit_missing"] : [],
    screening_reason_codes: [], warnings: [], target_shelf_life_days: null,
    produce_route_status: status === "exception" ? null : "unclassified",
    candidate_screening_allowed: status === "exception" ? null : status === "preliminary_shortlist",
    temperature_exposures: [],
    screened_candidates: status === "preliminary_shortlist" ? [{ structure_id: "TEST_ONLY_STRUCTURE", status: "eligible_for_shortlist", pack_format: "TEST_ONLY_FORMAT", reason_codes: [], layers: [] }] : [],
    preliminary_preferred_structure_id: status === "preliminary_shortlist" ? "TEST_ONLY_STRUCTURE" : null,
    recommended_structure_id: null, material_prediction: null,
    predicted_shelf_life_days: null, package_feasible: false,
  });
  return {
    contract_version: "frontend-decision-v1",
    source_batch_version: "basic-recommendation-batch-v1",
    model: { task: "material_suitability_ranking", status: "not_deployed", prediction_available: false, model_version: null },
    recommendation_release_status: "withheld",
    trace: Object.fromEntries([
      "scenario_sha256", "food_master_sha256", "material_master_sha256",
      "route_register_sha256", "assessment_register_sha256", "structure_catalogue_sha256",
      "structure_review_register_sha256", "transfer_register_sha256", "public_candidate_catalogue_sha256",
    ].map((key) => [key, null])),
    total_rows: 3,
    rows: [row(2, "not_ready"), row(3, "exception"), row(4, "preliminary_shortlist")],
  };
}

try {
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Network.setCacheDisabled", { cacheDisabled: true });
  await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await command("Emulation.setDeviceMetricsOverride", { width: viewportWidth, height: viewportHeight, deviceScaleFactor: 1, mobile: viewportWidth < 700 });
  await command("Page.navigate", { url: appUrl });
  await command("Page.bringToFront");
  for (let tries = 0; tries < 30; tries += 1) {
    if (await evaluate("document.readyState === 'complete' && document.querySelector('#backend-banner-title')?.textContent !== 'Checking the backend'")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const layout = await evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth, intro: !document.querySelector('#welcome-screen').hidden, appHidden: document.querySelector('.app-shell').hidden, banner: document.querySelector('#backend-banner-title').textContent})");
  assert.ok(layout.page <= layout.viewport, `horizontal overflow: ${JSON.stringify(layout)}`);
  assert.equal(layout.intro, true, "dedicated introduction is visible first");
  assert.equal(layout.appHidden, true, "workspace is not crowded into the introduction");
  assert.notEqual(layout.banner, "Checking the backend", "backend status resolved");

  if (process.env.PACKSENSE_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }

  await evaluate("document.querySelector('[data-enter-app]').click()");
  assert.equal(await evaluate("document.querySelector('.app-shell').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#view-pipeline').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#pipeline-play').getAttribute('aria-pressed')"), "true", "guided tour starts from Explore");
  let advanced = false;
  for (let tries = 0; tries < 80; tries += 1) {
    if (await evaluate("document.querySelector('#pipeline-heading-step').textContent !== '01'")) { advanced = true; break; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(advanced, true, "tour advances to the next stage");
  await evaluate("document.querySelector('#pipeline-play').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-play').getAttribute('aria-pressed')"), "false");
  await evaluate("document.querySelector('[data-pipeline-index=\"4\"]').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-heading-step').textContent"), "05");
  const stageLayout = await evaluate("(() => { const list = document.querySelector('#pipeline-stage-list'); const active = list.querySelector('.is-active'); return {client: list.clientWidth, scroll: list.scrollWidth, left: list.scrollLeft, activeLeft: active.getBoundingClientRect().left, activeRight: active.getBoundingClientRect().right, viewportLeft: list.getBoundingClientRect().left, viewportRight: list.getBoundingClientRect().right}; })()");
  assert.ok(stageLayout.activeLeft >= stageLayout.viewportLeft && stageLayout.activeRight <= stageLayout.viewportRight, `active stage not visible: ${JSON.stringify(stageLayout)}`);
  if (process.env.PACKSENSE_PIPELINE_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_PIPELINE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }
  await evaluate("document.querySelector('[data-route=\"fresh_produce\"]').click()");
  assert.equal(await evaluate("document.querySelector('[data-route=\"fresh_produce\"]').getAttribute('aria-pressed')"), "true");
  await evaluate("document.querySelector('[data-pipeline-mode=\"actual\"]').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-empty').hidden"), false);
  await evaluate("document.querySelector('[data-nav=\"overview\"]').click()");
  assert.equal(await evaluate("document.querySelector('#view-overview').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#overview-empty').hidden"), false);
  const previousTheme = await evaluate("document.documentElement.dataset.theme");
  await evaluate("document.querySelector('#theme-toggle').click()");
  assert.notEqual(await evaluate("document.documentElement.dataset.theme"), previousTheme);
  // TEST_ONLY UI fixture exercises filters and disclosure panels; it is never training data.
  const reportText = JSON.stringify(testOnlyReport());
  await evaluate("(() => { const input = document.querySelector('#report-input'); const transfer = new DataTransfer(); transfer.items.add(new File([" + JSON.stringify(reportText) + "], 'TEST_ONLY_frontend.json', {type: 'application/json'})); input.files = transfer.files; input.dispatchEvent(new Event('change', {bubbles: true})); })()");
  for (let tries = 0; tries < 30; tries += 1) {
    if (await evaluate("document.querySelector('#decisions-loaded').hidden === false")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(await evaluate("document.querySelector('#decisions-loaded').hidden"), false);
  assert.equal(await evaluate("document.querySelector('[data-filter=\"all\"] span').textContent"), "3");
  await evaluate("document.querySelector('[data-filter=\"preliminary_shortlist\"]').click()");
  assert.equal(await evaluate("document.querySelector('#record-filter-count').textContent"), "1 of 3 rows");
  assert.equal(await evaluate("document.querySelectorAll('#record-list .record-list-row').length"), 1);
  assert.equal(await evaluate("Boolean(document.querySelector('#record-inspector .inspector-disclosure[open] .candidate-list'))"), true);
  await evaluate("document.querySelector('[data-filter=\"exception\"]').click()");
  assert.equal(await evaluate("Boolean(document.querySelector('#record-inspector .inspector-disclosure[open] .reason-stack'))"), true);
  await evaluate("document.querySelector('[data-welcome]').click()");
  assert.equal(await evaluate("document.querySelector('#welcome-screen').hidden"), false);
  assert.deepEqual(exceptions, []);
  console.log(`Browser smoke passed: ${JSON.stringify(layout)}`);
} finally {
  const closed = new Promise((resolve) => socket.addEventListener("close", resolve, { once: true }));
  await fetch(`${cdpUrl}/json/close/${tab.id}`).catch(() => {});
  if (socket.readyState !== WebSocket.CLOSED) socket.close();
  await Promise.race([closed, new Promise((resolve) => setTimeout(resolve, 1000))]);
}
