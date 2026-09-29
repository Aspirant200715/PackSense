export const WORKSPACE_KEY = "packsense.workspace.v1";
export const REPORT_KEY = "packsense.report.v1";
export const MAX_SAVED_REPORT_CHARS = 2_000_000;

function readJson(storage, key) {
  try {
    const raw = storage?.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function readWorkspace(storage) {
  const snapshot = readJson(storage, WORKSPACE_KEY);
  return snapshot?.version === 1 && typeof snapshot.entered === "boolean"
    ? snapshot : null;
}

export function writeWorkspace(storage, snapshot) {
  try {
    storage?.setItem(WORKSPACE_KEY, JSON.stringify({ ...snapshot, version: 1 }));
    return Boolean(storage);
  } catch {
    return false;
  }
}

export function readReport(storage) {
  const snapshot = readJson(storage, REPORT_KEY);
  return snapshot?.version === 1 && ["browser", "local", "backend"].includes(snapshot.origin)
    && snapshot.report && typeof snapshot.report === "object" ? snapshot : null;
}

export function writeReport(storage, snapshot) {
  let serialized;
  try {
    serialized = JSON.stringify({ ...snapshot, version: 1 });
  } catch {
    return "unavailable";
  }
  if (serialized.length > MAX_SAVED_REPORT_CHARS) {
    try { storage?.removeItem?.(REPORT_KEY); } catch { /* Storage may be blocked. */ }
    return "too_large";
  }
  try {
    storage?.setItem(REPORT_KEY, serialized);
    return storage ? "saved" : "unavailable";
  } catch {
    try { storage?.removeItem?.(REPORT_KEY); } catch { /* Storage may be blocked. */ }
    return "unavailable";
  }
}
