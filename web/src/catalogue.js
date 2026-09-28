/** Validate research-only supplier applications before rendering source links. */
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const isText = (value) => typeof value === "string" && value.trim().length > 0;
const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

export function validatePublishedApplications(payload) {
  if (!isObject(payload) || payload.contract_version !== "published-applications-v1"
      || !isText(payload.catalogue_id)
      || !/^[0-9a-f]{64}$/i.test(payload.catalogue_sha256)
      || payload.model_prediction_available !== false
      || payload.package_approval_available !== false
      || !Array.isArray(payload.applications)) {
    throw new Error("The published-application response is invalid or makes an unsupported claim.");
  }
  const seen = new Set();
  for (const item of payload.applications) {
    if (!isObject(item) || !["candidate_id", "product_code", "pack_format", "food",
      "source_publisher", "source_url", "source_locator"].every((key) => isText(item[key]))
      || !isNumber(item.quantity) || item.quantity <= 0
      || !["g", "kg"].includes(item.quantity_unit)
      || !isNumber(item.storage_temperature_min_c)
      || !isNumber(item.storage_temperature_max_c)
      || item.storage_temperature_min_c > item.storage_temperature_max_c
      || item.source_rights_review_status !== "pending"
      || item.pack_format === "box inner liner") {
      throw new Error("A published package application has invalid source or use conditions.");
    }
    if ((item.excursion_max_c === null) !== (item.excursion_max_hours === null)
        || (item.excursion_max_c !== null && (
          !isNumber(item.excursion_max_c)
          || !isNumber(item.excursion_max_hours)
          || item.excursion_max_c < item.storage_temperature_max_c
          || item.excursion_max_hours <= 0))) {
      throw new Error("A published package application has invalid excursion conditions.");
    }
    let source;
    try { source = new URL(item.source_url); } catch {
      throw new Error("A published package application has an invalid source URL.");
    }
    if (source.protocol !== "https:" || !source.hostname || source.username || source.password) {
      throw new Error("A published package application has an unsafe source URL.");
    }
    const key = [item.candidate_id, item.food, item.quantity, item.quantity_unit,
      item.storage_temperature_min_c, item.storage_temperature_max_c,
      item.excursion_max_c, item.excursion_max_hours].join("\u0000");
    if (seen.has(key)) throw new Error("The published catalogue repeats a product application.");
    seen.add(key);
  }
  return payload;
}

/** Text discovery never infers suitability or compares use conditions. */
export function filterPublishedApplications(applications, query) {
  const term = String(query ?? "").trim().toLocaleLowerCase();
  if (!term) return applications.map((item, index) => ({ item, index }));
  return applications.map((item, index) => ({ item, index })).filter(({ item }) =>
    [item.food, item.product_code, item.pack_format, item.source_publisher]
      .some((value) => value.toLocaleLowerCase().includes(term)));
}
