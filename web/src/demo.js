const TRACE_FIELDS = [
  "scenario_sha256", "food_master_sha256", "material_master_sha256",
  "public_candidate_catalogue_sha256",
];

function isHttpsUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}

export function validateDemoEvidence(evidence, report) {
  if (!evidence || evidence.contract_version !== "packsense-demo-evidence-v1"
      || typeof evidence.input_note !== "string" || !evidence.input_note
      || !evidence.trace || !TRACE_FIELDS.every((field) => evidence.trace[field] === report.trace[field])
      || !Array.isArray(evidence.scenarios) || evidence.scenarios.length !== report.rows.length) {
    throw new Error("The demo evidence does not match its report.");
  }
  const cases = new Map();
  for (const item of evidence.scenarios) {
    if (!item || typeof item.record_id !== "string" || !item.record_id.startsWith("DEMO-")
        || cases.has(item.record_id) || typeof item.food_reference_id !== "string"
        || !["missing", "proxy", "reported_reference", "unverified_reference"].includes(item.pH_evidence)
        || typeof item.pH_basis !== "string"
        || !Array.isArray(item.food_source_links) || item.food_source_links.length === 0
        || !item.food_source_links.every((link) => typeof link.label === "string" && link.label
          && isHttpsUrl(link.url))
        || typeof item.supplier_product_code !== "string" || !item.supplier_product_code
        || !isHttpsUrl(item.supplier_source_url)
        || typeof item.supplier_source_locator !== "string" || !item.supplier_source_locator) {
      throw new Error("The demo contains an invalid evidence citation.");
    }
    cases.set(item.record_id, item);
  }
  for (const row of report.rows) {
    const item = cases.get(row.record_id);
    if (!item || item.food_reference_id !== row.food_reference_id
        || row.status !== "not_ready"
        || !row.supplier_application_lookup?.leads.some((lead) =>
          lead.product_code === item.supplier_product_code
          && lead.source_url === item.supplier_source_url
          && lead.source_locator === item.supplier_source_locator)) {
      throw new Error("The demo evidence is detached from a source-backed decision row.");
    }
  }
  return evidence;
}
