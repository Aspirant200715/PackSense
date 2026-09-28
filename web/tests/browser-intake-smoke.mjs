// Optional end-to-end check against a local backend configured with real masters.
// The entered operating conditions below are TEST_ONLY browser fixtures: they
// are never written to the reference workbooks or used as training labels.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";

const cdpUrl = process.env.PACKSENSE_CDP_URL || "http://127.0.0.1:9333";
const appUrl = process.env.PACKSENSE_WEB_URL || "http://127.0.0.1:4173/";
const width = Number(process.env.PACKSENSE_VIEWPORT_WIDTH || 390);
const height = Number(process.env.PACKSENSE_VIEWPORT_HEIGHT || 844);
const foodId = process.env.PACKSENSE_TEST_FOOD_ID || "FND-2710823";
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

async function until(expression, message, attempts = 80) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(message);
}

async function screenshot(fileName) {
  if (!fileName) return;
  const result = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(fileName, Buffer.from(result.data, "base64"));
}

try {
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Network.setCacheDisabled", { cacheDisabled: true });
  await command("Emulation.setDeviceMetricsOverride", {
    width, height, deviceScaleFactor: 1, mobile: width < 700,
  });
  await command("Page.navigate", { url: appUrl });
  await until("document.readyState === 'complete' && document.querySelector('#start-evaluation')?.hidden === false", "interactive backend did not connect");
  assert.equal(await evaluate("document.querySelector('#backend-indicator').dataset.state"), "interactive_scenario");
  await evaluate("document.querySelector('#start-evaluation').click()");
  assert.equal(await evaluate("document.querySelector('#view-evaluate').hidden"), false);
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "form overflows viewport");

  await evaluate("(() => { const input = document.querySelector('#food-search'); input.value = 'asparagus'; input.dispatchEvent(new Event('input', { bubbles: true })); })()");
  await until("document.querySelector('#food-search-results [data-food-id=\"SR-169207\"]') !== null", "incomplete reference was not shown");
  await evaluate("document.querySelector('#food-search-results [data-food-id=\"SR-169207\"]').click()");
  assert.equal(await evaluate("document.querySelector('#evaluate-submit').disabled"), true, "missing source pH blocks evaluation");
  assert.match(await evaluate("document.querySelector('#selected-food').textContent"), /lacks|missing/i);

  await evaluate(`(() => { const input = document.querySelector('#food-search'); input.value = ${JSON.stringify(foodId)}; input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await until("document.querySelectorAll('#food-search-results [data-food-id]').length > 0", "food reference lookup did not return a row");
  assert.equal(await evaluate("document.querySelector('#food-search-results [data-food-id]').dataset.foodId"), foodId);
  await evaluate("document.querySelector('#food-search-results [data-food-id]').click()");
  assert.equal(await evaluate("document.querySelector('#evaluate-submit').disabled"), false);
  assert.match(await evaluate("document.querySelector('#selected-food').textContent"), /pH evidence|Reference citations/);
  assert.equal(await evaluate("document.querySelector('#scenario-form [name=pH]')"), null, "reference pH cannot be overwritten in form");
  await screenshot(process.env.PACKSENSE_INTAKE_SCREENSHOT);

  await evaluate(`(() => {
    const values = {
      desired_shelf_life_days: '5', storage_type: 'chilled',
      storage_temperature_c: '4', storage_relative_humidity_pct: '90',
      transport_mode: 'road', transport_duration_hours: '8',
      transport_temperature_c: '4', transport_max_temperature_c: '8',
      transport_handling_severity: 'low', net_pack_quantity: '150',
      net_pack_quantity_unit: 'g',
    };
    const form = document.querySelector('#scenario-form');
    for (const [name, value] of Object.entries(values)) {
      form.elements.namedItem(name).value = value;
    }
    form.requestSubmit();
  })()`);
  await until("document.querySelector('#decisions-loaded').hidden === false || document.querySelector('#evaluation-error').hidden === false", "scenario evaluation did not finish", 180);
  const error = await evaluate("document.querySelector('#evaluation-error').hidden ? null : document.querySelector('#evaluation-error').textContent");
  assert.equal(error, null, `scenario evaluation failed: ${error}`);
  assert.equal(await evaluate("document.querySelector('#view-decisions').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#record-filter-count').textContent"), "1 of 1 rows");
  assert.equal(await evaluate("document.querySelector('[data-filter=not_ready] span').textContent"), "1", "the test-only scenario remains evidence-gated");
  assert.match(await evaluate("document.querySelector('#record-inspector').textContent"), /source|submitted|evidence/i);
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "result overflows viewport");
  await screenshot(process.env.PACKSENSE_RESULT_SCREENSHOT);
  assert.deepEqual(exceptions, []);
  console.log(`Browser intake smoke passed at ${width}px: source ${foodId}, one evidence-gated decision.`);
} finally {
  const closed = new Promise((resolve) => socket.addEventListener("close", resolve, { once: true }));
  await fetch(`${cdpUrl}/json/close/${tab.id}`).catch(() => {});
  if (socket.readyState !== WebSocket.CLOSED) socket.close();
  await Promise.race([closed, new Promise((resolve) => setTimeout(resolve, 1000))]);
}
