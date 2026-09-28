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
  const rows = [row(2, "not_ready"), row(3, "exception"), row(4, "preliminary_shortlist")];
  rows[0].supplier_application_lookup = {
    lookup_version: "supplier-application-lookup-v1",
    catalogue_id: "TEST_ONLY_CATALOGUE",
    status: "published_food_application_found",
    approved_structure_count: 0,
    recommended_structure_id: null,
    model_prediction_available: false,
    leads: [{
      candidate_id: "TEST_ONLY_SUPPLIER", product_code: "TEST_ONLY_CODE",
      pack_format: "TEST_ONLY_BAG", supplier_application_food: "TEST_ONLY_FOOD",
      food_name_match: "exact_name", source_id: "TEST_ONLY_SOURCE",
      source_url: "https://example.org/product", source_locator: "TEST_ONLY_ROW",
      source_rights_review_status: "pending", published_quantity: 100,
      published_quantity_unit: "g", published_storage_temperature_min_c: 0,
      published_storage_temperature_max_c: 10, published_excursion_max_c: null,
      published_excursion_max_hours: null,
      application_status: "published_food_quantity_temperature_match_unverified",
      reason_codes: [], approval_blockers: ["food_package_suitability_unverified"],
    }],
  };
  rows[2].supplier_application_lookup = {
    lookup_version: "supplier-application-lookup-v1",
    catalogue_id: "TEST_ONLY_CATALOGUE",
    status: "no_published_food_application_match", leads: [],
    approved_structure_count: 0, recommended_structure_id: null,
    model_prediction_available: false,
  };
  return {
    contract_version: "frontend-decision-v1",
    source_batch_version: "basic-recommendation-batch-v1",
    model: { task: "material_suitability_ranking", status: "not_deployed", prediction_available: false, model_version: null },
    recommendation_release_status: "withheld",
    trace: Object.fromEntries([
      "scenario_sha256", "food_master_sha256", "material_master_sha256",
      "route_register_sha256", "assessment_register_sha256", "structure_catalogue_sha256",
      "structure_review_register_sha256", "transfer_register_sha256", "public_candidate_catalogue_sha256",
    ].map((key) => [key, key === "public_candidate_catalogue_sha256" ? "d".repeat(64) : null])),
    total_rows: 3,
    rows,
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
    if (await evaluate("document.readyState === 'complete' && document.querySelector('#backend-indicator-text')?.textContent !== 'Checking'")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const layout = await evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth, intro: !document.querySelector('#welcome-screen').hidden, appHidden: document.querySelector('.app-shell').hidden, connection: document.querySelector('#backend-indicator-text').textContent})");
  assert.ok(layout.page <= layout.viewport, `horizontal overflow: ${JSON.stringify(layout)}`);
  assert.equal(layout.intro, true, "dedicated introduction is visible first");
  assert.equal(layout.appHidden, true, "workspace is not crowded into the introduction");
  assert.notEqual(layout.connection, "Checking", "backend status resolved");
  const hasPublishedCatalogue = await evaluate("document.querySelector('#backend-indicator').dataset.state === 'published_catalogue'");

  if (hasPublishedCatalogue) {
    for (let tries = 0; tries < 30; tries += 1) {
      if (await evaluate("document.querySelector('#browse-real-applications').hidden === false")) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(await evaluate("document.querySelector('#browse-real-applications').hidden"), false, "source-listed catalogue loads");
    await evaluate("document.querySelector('#browse-real-applications').click()");
    assert.equal(await evaluate("document.querySelector('#overview-title').textContent"), "Explore package uses");
    assert.equal(await evaluate("document.querySelectorAll('.published-application-card').length"), 6, "six real standalone source uses are shown");
    assert.match(await evaluate("document.querySelector('#published-applications').textContent"), /not PackSense predictions or approved packaging/);
    assert.equal(await evaluate("document.querySelector('#review-count').textContent"), "1", "catalogue creates one real review update");
    await evaluate("document.querySelector('#review-toggle').click()");
    assert.match(await evaluate("document.querySelector('#review-items').textContent"), /rights review is pending/);
    if (process.env.PACKSENSE_REVIEW_SCREENSHOT) {
      const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      await writeFile(process.env.PACKSENSE_REVIEW_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
    }
    await evaluate("document.querySelector('#review-items [data-review-action=published]').click()");
    assert.equal(await evaluate("document.querySelector('#review-panel').hidden"), true, "review action closes the panel");
    await evaluate("(() => { const input = document.querySelector('#published-search'); input.value = 'broccoli'; input.dispatchEvent(new Event('input', {bubbles: true})); })()");
    assert.equal(await evaluate("document.querySelectorAll('.published-application-card').length"), 1, "source uses are searchable by food");
    assert.match(await evaluate("document.querySelector('.published-application-card').textContent"), /VY7K9/);
    await evaluate("document.querySelector('.published-application-card [data-compare-index]').click()");
    assert.equal(await evaluate("document.querySelector('#published-comparison').hidden"), false, "comparison explains the second selection");
    await evaluate("(() => { const input = document.querySelector('#published-search'); input.value = ''; input.dispatchEvent(new Event('input', {bubbles: true})); })()");
    await evaluate("document.querySelector('#published-applications-list [data-compare-index]:not([aria-pressed=true])').click()");
    assert.equal(await evaluate("document.querySelectorAll('.published-comparison-card').length"), 2, "comparison contains two actual source uses");
    assert.match(await evaluate("document.querySelector('#published-comparison').textContent"), /not interchangeable food uses or a package recommendation/);
    assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "catalogue tools and comparison have no horizontal overflow");
    if (process.env.PACKSENSE_CATALOGUE_SCREENSHOT) {
      const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      await writeFile(process.env.PACKSENSE_CATALOGUE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
    }
    await evaluate("document.querySelector('[data-clear-comparison]').click()");
    assert.equal(await evaluate("document.querySelector('#published-comparison').hidden"), true);
    await evaluate("document.querySelector('[data-welcome]').click()");
  }

  if (process.env.PACKSENSE_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }

  await evaluate("document.querySelector('[data-enter-app]').click()");
  assert.equal(await evaluate("document.querySelector('.app-shell').hidden"), false);
  await evaluate("document.querySelector('#review-toggle').click()");
  assert.equal(await evaluate("document.querySelector('#review-toggle').getAttribute('aria-expanded')"), "true");
  await evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))");
  assert.equal(await evaluate("document.querySelector('#review-panel').hidden"), true, "Escape closes review updates");
  await evaluate("document.querySelector('#review-toggle').click()");
  await evaluate("document.querySelector('#view-pipeline').click()");
  assert.equal(await evaluate("document.querySelector('#review-panel').hidden"), true, "clicking outside closes review updates");
  assert.equal(await evaluate("document.querySelector('#view-pipeline').hidden"), false);
  assert.equal(await evaluate("document.querySelectorAll('#pipeline-stage-list .studio-stage').length"), 8, "one compact timeline shows all eight stages");
  assert.equal(await evaluate("document.querySelector('#pipeline-stage-list .studio-stage.is-active').dataset.pipelineIndex"), "0");
  assert.equal(await evaluate("document.querySelector('#journey-map, #guide-progress')"), null, "duplicate progress displays were removed");
  assert.equal(await evaluate("document.querySelector('#studio-intake-action').hidden"), false, "intake explains where to add real data");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#backend-indicator')).display !== 'none'"), true, "single connection indicator is visible");
  assert.equal(await evaluate("document.querySelector('#pipeline-play').getAttribute('aria-pressed')"), "true", "guided tour starts from Explore");
  await evaluate("document.querySelector('#pipeline-play').click()");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.stage-traveler')).display"), "none", "timeline marker stops when paused");
  await evaluate("document.querySelector('#pipeline-play').click()");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.stage-traveler')).animationName"), "timeline-travel", "timeline marker follows playback");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.flow-connector'), '::after').content"), "none", "lower arrows have no moving square");
  const markerBefore = await evaluate("document.querySelector('.stage-traveler').getBoundingClientRect().left");
  await new Promise((resolve) => setTimeout(resolve, 600));
  const markerAfter = await evaluate("document.querySelector('.stage-traveler').getBoundingClientRect().left");
  const markerDetails = await evaluate("(() => { const marker = document.querySelector('.stage-traveler'); const style = getComputedStyle(marker); return {inline: marker.getAttribute('style'), start: style.getPropertyValue('--travel-start'), end: style.getPropertyValue('--travel-end'), animation: style.animationName, display: style.display, left: style.left, width: marker.parentElement.clientWidth, currentTime: marker.getAnimations()[0]?.currentTime}; })()");
  assert.ok(markerAfter > markerBefore + 2, `timeline marker did not move forward: ${markerBefore} -> ${markerAfter}; ${JSON.stringify(markerDetails)}`);
  await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.stage-traveler')).display"), "none", "reduced motion hides the moving marker");
  await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  if (process.env.PACKSENSE_MOVING_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_MOVING_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }
  let advanced = false;
  for (let tries = 0; tries < 80; tries += 1) {
    if (await evaluate("document.querySelector('#guide-stage-caption').textContent !== 'Step 1 of 8'")) { advanced = true; break; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(advanced, true, "tour advances to the next stage");
  await evaluate("document.querySelector('#pipeline-play').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-play').getAttribute('aria-pressed')"), "false");
  await evaluate("document.querySelector('[data-pipeline-index=\"2\"]').click()");
  assert.equal(await evaluate("document.querySelector('#guide-stage-caption').textContent"), "Step 3 of 8");
  assert.equal(await evaluate("document.querySelector('#studio-title').textContent"), "Food requirements");
  await evaluate("document.querySelector('[data-pipeline-index=\"4\"]').click()");
  assert.equal(await evaluate("document.querySelector('#guide-stage-caption').textContent"), "Step 5 of 8");
  const stageLayout = await evaluate("(() => { const list = document.querySelector('#pipeline-stage-list'); const active = list.querySelector('.is-active'); return {client: list.clientWidth, scroll: list.scrollWidth, left: active.getBoundingClientRect().left, right: active.getBoundingClientRect().right, viewportLeft: list.getBoundingClientRect().left, viewportRight: list.getBoundingClientRect().right}; })()");
  assert.ok(stageLayout.scroll <= stageLayout.client && stageLayout.left >= stageLayout.viewportLeft && stageLayout.right <= stageLayout.viewportRight, `timeline overflows: ${JSON.stringify(stageLayout)}`);
  if (process.env.PACKSENSE_PIPELINE_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_PIPELINE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }
  await evaluate("document.querySelector('[data-route=\"fresh_produce\"]').click()");
  assert.equal(await evaluate("document.querySelector('[data-route=\"fresh_produce\"]').getAttribute('aria-pressed')"), "true");
  await evaluate("document.querySelector('[data-pipeline-index=\"7\"]').click()");
  assert.equal(await evaluate("document.querySelector('#studio-finish').hidden"), false);
  await evaluate("document.querySelector('#studio-finish [data-show-setup]').click()");
  assert.equal(await evaluate("document.querySelector('#run-path').open"), true, "setup steps open from the end of the tour");
  const setupPosition = await evaluate("({summary: document.querySelector('#run-path > summary').getBoundingClientRect().top, topbarBottom: document.querySelector('.topbar').getBoundingClientRect().bottom})");
  assert.ok(setupPosition.summary >= setupPosition.topbarBottom - 5, `setup summary is obscured by navigation: ${JSON.stringify(setupPosition)}`);
  assert.match(await evaluate("document.querySelector('#startup-command').textContent"), /--scenarios/);
  assert.equal(await evaluate("document.querySelector('#run-path a[download]').getAttribute('href')"), "/api/scenario-template");
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "setup instructions have no horizontal overflow");
  await evaluate("document.querySelector('[data-pipeline-mode=\"actual\"]').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-empty').hidden"), false);
  await evaluate("document.querySelector('[data-nav=\"overview\"]').click()");
  assert.equal(await evaluate("document.querySelector('#view-overview').hidden"), false);
  assert.equal(await evaluate("document.querySelectorAll('[data-nav].is-active').length"), 1);
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "workspace has no horizontal overflow");
  assert.equal(await evaluate("document.querySelector('#overview-empty').hidden"), hasPublishedCatalogue);
  assert.equal(await evaluate("document.querySelector('#backend-banner, #overview-empty-status')"), null, "overview repeats no connection message");
  await new Promise((resolve) => setTimeout(resolve, 200));
  if (process.env.PACKSENSE_OVERVIEW_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_OVERVIEW_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }
  if (hasPublishedCatalogue) {
    await evaluate("document.querySelector('[data-nav=pipeline]').click()");
    await evaluate("document.querySelector('[data-pipeline-index=\"4\"]').click()");
  } else {
    await evaluate("document.querySelector('#overview-empty [data-enter-stage=\"4\"]').click()");
  }
  assert.equal(await evaluate("document.querySelector('#view-pipeline').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#guide-stage-caption').textContent"), "Step 5 of 8");
  await evaluate("document.querySelector('[data-nav=\"overview\"]').click()");
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
  assert.equal(await evaluate("document.querySelector('#review-count').textContent"), "3", "report statuses drive review items");
  await evaluate("document.querySelector('#review-toggle').click()");
  assert.match(await evaluate("document.querySelector('#review-items').textContent"), /input exception/);
  await evaluate("document.querySelector('#review-items [data-review-action=not_ready]').click()");
  assert.equal(await evaluate("document.querySelector('#record-filter-count').textContent"), "1 of 3 rows", "review update opens the relevant filtered records");
  await evaluate("document.querySelector('[data-filter=all]').click()");
  await evaluate("document.querySelector('#record-inspector [data-trace-row]').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-guide-bar').hidden"), false, "a real report has a playable trace");
  assert.equal(await evaluate("document.querySelector('#guide-play-label').textContent"), "Play report trace");
  await evaluate("document.querySelector('#pipeline-play').click()");
  assert.equal(await evaluate("document.querySelector('#pipeline-play').getAttribute('aria-pressed')"), "true");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.stage-traveler')).animationName"), "timeline-travel", "real report playback uses the same moving route marker");
  let traceAdvanced = false;
  for (let tries = 0; tries < 80; tries += 1) {
    if (await evaluate("document.querySelector('#guide-stage-caption').textContent !== 'Step 1 of 8'")) { traceAdvanced = true; break; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(traceAdvanced, true, "actual report playback advances through the recorded stages");
  await evaluate("document.querySelector('[data-pipeline-index=\"7\"]').click()");
  assert.equal(await evaluate("document.querySelector('#studio-actual-finish').hidden"), false);
  assert.match(await evaluate("document.querySelector('#studio-output').textContent"), /not ready/);
  await evaluate("document.querySelector('#studio-actual-finish [data-go=\"decisions\"]').click()");
  assert.equal(await evaluate("document.querySelector('#record-inspector .published-match-callout strong')?.textContent.trim()"), "TEST_ONLY_CODE TEST_ONLY_BAG");
  assert.match(await evaluate("document.querySelector('#record-inspector .published-match-callout p')?.textContent"), /not approved these packages or made a model prediction/);
  assert.equal(await evaluate("document.querySelector('#record-inspector .supplier-lead-heading strong')?.textContent"), "TEST_ONLY_CODE");
  assert.equal(await evaluate("document.querySelector('#record-inspector .supplier-source a')?.getAttribute('href')"), "https://example.org/product");
  assert.match(await evaluate("document.querySelector('#record-inspector .supplier-boundary')?.textContent"), /not a material prediction/);
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "supplier research lead has no horizontal overflow");
  await evaluate("document.querySelector('[data-filter=\"preliminary_shortlist\"]').click()");
  assert.equal(await evaluate("document.querySelector('#record-filter-count').textContent"), "1 of 3 rows");
  assert.equal(await evaluate("document.querySelectorAll('#record-list .record-list-row').length"), 1);
  assert.equal(await evaluate("Boolean(document.querySelector('#record-inspector .inspector-disclosure[open] .candidate-list'))"), true);
  await evaluate("document.querySelector('[data-filter=\"exception\"]').click()");
  assert.equal(await evaluate("Boolean(document.querySelector('#record-inspector .inspector-disclosure[open] .reason-stack'))"), true);
  await evaluate("document.querySelector('[data-nav=\"overview\"]').click()");
  assert.equal(await evaluate("document.querySelector('#overview-results').hidden"), false);
  assert.equal(await evaluate("document.querySelectorAll('#backend-indicator').length"), 1);
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
