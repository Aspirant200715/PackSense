// Optional browser regression: a cold-start sequence of gateway errors must
// recover without asking the visitor to refresh the page.
import assert from "node:assert/strict";

const cdpUrl = process.env.PACKSENSE_CDP_URL || "http://127.0.0.1:9333";
const appUrl = process.env.PACKSENSE_WEB_URL || "http://127.0.0.1:4173/";
const gatewayFailures = 7;
const tabResponse = await fetch(`${cdpUrl}/json/new?about:blank`, { method: "PUT" });
assert.equal(tabResponse.status, 200, "Chrome DevTools must be running");
const tab = await tabResponse.json();
const socket = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
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
  const result = await command("Runtime.evaluate", { expression, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

try {
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Network.setCacheDisabled", { cacheDisabled: true });
  await command("Page.addScriptToEvaluateOnNewDocument", { source: `
    (() => {
      const originalFetch = window.fetch.bind(window);
      let attempts = 0;
      window.fetch = (input, options) => {
        const url = new URL(typeof input === "string" ? input : input.url, location.href);
        if (url.pathname === "/api/status") {
          attempts += 1;
          if (attempts <= ${gatewayFailures}) return Promise.resolve(new Response("temporary gateway failure", { status: 502 }));
        }
        return originalFetch(input, options);
      };
      window.__statusAttempts = () => attempts;
    })();
  ` });
  await command("Page.navigate", { url: appUrl });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await evaluate("window.__statusAttempts?.() === 1")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(await evaluate("document.querySelector('#backend-indicator')?.dataset.state"), "checking");
  assert.match(await evaluate("document.querySelector('#hero-tour-hint')?.textContent"), /connecting to the evaluation service/i);
  let connected = false;
  for (let attempt = 0; attempt < 500; attempt += 1) {
    connected = await evaluate("document.querySelector('#backend-indicator-text')?.textContent === 'Connected'");
    if (connected) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const observed = await evaluate("({ mode: document.querySelector('#backend-indicator')?.dataset.state, attempts: window.__statusAttempts?.() })");
  assert.equal(connected, true, `workspace did not reconnect after cold-start gateway errors: ${JSON.stringify(observed)}`);
  assert.ok(await evaluate("window.__statusAttempts()") >= gatewayFailures + 1, "the status request did not survive the gateway errors");
  console.log("Browser reconnect smoke passed: cold-start gateway errors recovered without a reload.");
} finally {
  await fetch(`${cdpUrl}/json/close/${tab.id}`).catch(() => {});
  socket.close();
}
