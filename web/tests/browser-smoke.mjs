// Optional no-dependency browser smoke check against a running local service.
// Start headless Chrome with --remote-debugging-port=9333 and set
// PACKSENSE_CDP_URL if it uses a different port.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";

const cdpUrl = process.env.PACKSENSE_CDP_URL || "http://127.0.0.1:9333";
const appUrl = process.env.PACKSENSE_WEB_URL || "http://127.0.0.1:4173/";
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

try {
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Network.setCacheDisabled", { cacheDisabled: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await command("Page.navigate", { url: appUrl });
  for (let tries = 0; tries < 30; tries += 1) {
    if (await evaluate("document.readyState === 'complete' && document.querySelector('#backend-banner-title')?.textContent !== 'Checking the backend'")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const layout = await evaluate("({viewport: innerWidth, page: document.documentElement.scrollWidth, nav: document.querySelector('.top-nav').getBoundingClientRect().width, banner: document.querySelector('#backend-banner-title').textContent})");
  assert.ok(layout.page <= layout.viewport, `mobile horizontal overflow: ${JSON.stringify(layout)}`);
  assert.ok(layout.nav > 0, "top icon navigation is visible");
  assert.notEqual(layout.banner, "Checking the backend", "backend status resolved");

  if (process.env.PACKSENSE_SCREENSHOT) {
    const screenshot = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(process.env.PACKSENSE_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }

  await evaluate("document.querySelector('[data-jump-stage=\"4\"]').click()");
  assert.equal(await evaluate("document.querySelector('#view-pipeline').hidden"), false);
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
  const previousTheme = await evaluate("document.documentElement.dataset.theme");
  await evaluate("document.querySelector('#theme-toggle').click()");
  assert.notEqual(await evaluate("document.documentElement.dataset.theme"), previousTheme);
  assert.deepEqual(exceptions, []);
  console.log(`Browser smoke passed: ${JSON.stringify(layout)}`);
} finally {
  const closed = new Promise((resolve) => socket.addEventListener("close", resolve, { once: true }));
  await fetch(`${cdpUrl}/json/close/${tab.id}`).catch(() => {});
  if (socket.readyState !== WebSocket.CLOSED) socket.close();
  await Promise.race([closed, new Promise((resolve) => setTimeout(resolve, 1000))]);
}
