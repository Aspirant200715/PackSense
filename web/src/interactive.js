const NUMERIC_FIELDS = [
  "desired_shelf_life_days", "storage_temperature_c", "storage_relative_humidity_pct",
  "transport_duration_hours", "transport_temperature_c", "transport_max_temperature_c",
  "net_pack_quantity",
];
const TEXT_FIELDS = [
  "storage_type", "transport_mode", "transport_handling_severity", "net_pack_quantity_unit",
];
const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

export function validateFoodLookup(payload) {
  if (!payload || payload.contract_version !== "food-lookup-v1"
      || !/^[0-9a-f]{64}$/i.test(payload.food_master_sha256 ?? "")
      || !Number.isInteger(payload.total_matches) || payload.total_matches < 0
      || !Number.isInteger(payload.form_ready_matches)
      || payload.form_ready_matches < 0 || payload.form_ready_matches > payload.total_matches
      || !Array.isArray(payload.foods) || payload.foods.length > 15
      || payload.foods.length > payload.total_matches) {
    throw new Error("The food reference search response is invalid.");
  }
  const seen = new Set();
  for (const food of payload.foods) {
    if (!food || typeof food.food_reference_id !== "string" || !food.food_reference_id
        || seen.has(food.food_reference_id)
        || typeof food.commodity_type !== "string" || !food.commodity_type
        || typeof food.source_citations !== "string" || !food.source_citations
        || typeof food.form_ready !== "boolean"
        || !Array.isArray(food.missing_reference_properties)
        || !["missing", "proxy", "reported_reference", "unverified_reference"].includes(food.pH_evidence)) {
      throw new Error("A food reference search result is invalid.");
    }
    for (const field of ["moisture_content_pct", "oil_fat_content_pct", "pH",
      "respiration_rate", "respiration_reference_temperature_c"]) {
      if (food[field] !== null && !isNumber(food[field])) {
        throw new Error("A food reference property is invalid.");
      }
    }
    const missing = ["moisture_content_pct", "oil_fat_content_pct", "pH"]
      .filter((field) => food[field] === null);
    if (food.form_ready !== (missing.length === 0)
        || missing.join("|") !== food.missing_reference_properties.join("|")) {
      throw new Error("A food reference completeness flag is inconsistent.");
    }
    seen.add(food.food_reference_id);
  }
  return payload;
}

export function scenarioPayload(values, food, foodMasterSha256) {
  if (!food?.form_ready || !/^[0-9a-f]{64}$/i.test(foodMasterSha256 ?? "")) {
    throw new Error("Select a complete food reference before evaluating.");
  }
  const payload = {
    food_reference_id: food.food_reference_id,
    food_master_sha256: foodMasterSha256,
  };
  for (const field of NUMERIC_FIELDS) {
    const value = values[field];
    if (value === "" || value === undefined || !Number.isFinite(Number(value))) {
      throw new Error(`Enter a valid ${field.replaceAll("_", " ")}.`);
    }
    payload[field] = Number(value);
  }
  for (const field of TEXT_FIELDS) payload[field] = values[field];
  return payload;
}
