/** An educational walkthrough and a conservative view of one real report row.
 * Neither path simulates material measurements or generates a recommendation.
 */

export const STAGES = Object.freeze([
  { number: "01", title: "Scenario intake", short: "Input" },
  { number: "02", title: "Validate & enrich", short: "Validate" },
  { number: "03", title: "Food requirements", short: "Needs" },
  { number: "04", title: "Produce branch", short: "Produce" },
  { number: "05", title: "Package screening", short: "Screen" },
  { number: "06", title: "Protection comparison", short: "Compare" },
  { number: "07", title: "Prediction gate", short: "Model gate" },
  { number: "08", title: "Decision record", short: "Output" },
]);

const WALKTHROUGH = [
  {
    statement: "Begin with one complete recommendation scenario, not just a food name.",
    input: "Food properties, pack quantity, desired life and temperature profile",
    check: "Preserve the submitted values and source row",
    output: "One traceable scenario record",
    boundary: "A missing critical condition does not receive a guessed value.",
  },
  {
    statement: "Validate the record and match its food to the reference master.",
    input: "Structured scenario and versioned food references",
    check: "Units, ranges, cross-field logic and exact food identity",
    output: "Enriched record or explicit input exception",
    boundary: "An unmatched or invalid food cannot continue to screening.",
  },
  {
    statement: "Translate food properties into protection needs using approved evidence.",
    input: "Food identity, pack mass and exposure conditions",
    check: "Oxygen and moisture mechanisms, service and handling needs",
    output: "Requirement card with source-linked limits or gaps",
    boundary: "Composition alone does not create a numeric OTR or WVTR target.",
  },
  {
    statement: "The food route determines whether the produce-specific branch applies.",
    input: "Reviewed respiration classification and exposure profile",
    check: "Route-specific gas and water evidence",
    output: "Branch decision or unresolved produce diagnostics",
    boundary: "A local gas snapshot is not proof of safe MAP over shelf life.",
  },
  {
    statement: "Only complete, reviewed package structures can be screened.",
    input: "Structure, food-contact review and whole-package transfer evidence",
    check: "Food scope, temperature, sealing, handling and transfer budgets",
    output: "Eligible, excluded or unresolved candidates",
    boundary: "A material-grade sheet or supplier application is not a finished package approval.",
  },
  {
    statement: "Compare only the candidates that survived the engineering gates.",
    input: "Eligible structures with comparable source-approved budgets",
    check: "Protection trade-offs without unsupported weights",
    output: "Preliminary frontier; possibly no unique preference",
    boundary: "This is not a cost, sustainability or certified performance ranking.",
  },
  {
    statement: "A learned prediction needs independently reviewed outcome labels.",
    input: "Suitable and unsuitable food–complete-package outcomes",
    check: "Frozen group split, held-out evaluation and release criteria",
    output: "No material prediction in the current release",
    boundary: "The 5,000-food and 81-grade references do not supply these labels.",
  },
  {
    statement: "Publish the status and the evidence trail together.",
    input: "Scenario, requirement card and candidate screen",
    check: "Contract version, source hashes and claim boundaries",
    output: "Exception, evidence gap or preliminary shortlist",
    boundary: "The output does not claim package feasibility or predicted shelf life.",
  },
];

export function walkthroughStage(index, route = "non_respiring") {
  if (!Number.isInteger(index) || index < 0 || index >= STAGES.length) {
    throw new RangeError("Unknown pipeline step.");
  }
  if (route !== "non_respiring" && route !== "fresh_produce") {
    throw new RangeError("Unknown food route.");
  }
  const stage = { ...STAGES[index], ...WALKTHROUGH[index] };
  if (index === 3) {
    return route === "fresh_produce"
      ? {
          ...stage,
          statement: "Fresh produce keeps respiring after harvest, so gas and water checks become essential.",
          check: "O₂ entry, CO₂ exit, respiration and condensation at each temperature",
          output: "Local diagnostic findings; no MAP safety certification",
          routeNote: "Fresh-produce branch — diagnostics only in the current backend.",
        }
      : {
          ...stage,
          statement: "A reviewed non-respiring route bypasses the produce-only calculation.",
          check: "Confirm the non-respiring route from reviewed evidence",
          output: "Continue to the complete-package screen",
          routeNote: "Non-respiring branch — this bypass requires route confirmation.",
        };
  }
  return stage;
}

function stage(state, statement, input, check, output, evidence = []) {
  return { state, statement, input, check, output, evidence };
}

function numberWithUnit(value, unit = "") {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value}${unit}`
    : null;
}

function packQuantity(scenario) {
  const quantity = numberWithUnit(scenario?.net_pack_quantity);
  return quantity ? `${quantity} ${scenario?.net_pack_quantity_unit || "(unit not reported)"}` : null;
}

function exposureSummary(exposures = []) {
  const parts = exposures.flatMap((exposure) => {
    const temperature = numberWithUnit(exposure?.temperature_c, "°C");
    return temperature ? [`${exposure.phase?.replaceAll("_", " ") || "Exposure"} ${temperature}`] : [];
  });
  return parts.length ? parts.join(" · ") : "Not reported";
}

/** Facts copied from the imported row, never estimated by the browser. */
export function actualContext(row) {
  const scenario = row.scenario;
  return [
    { label: "FOOD", value: scenario?.commodity_type || "Not validated or not reported" },
    { label: "PACK QUANTITY", value: packQuantity(scenario) || "Not reported" },
    { label: "REQUESTED LIFE", value: numberWithUnit(row.target_shelf_life_days, " days") || "Not reported" },
    { label: "TEMPERATURE PHASES", value: exposureSummary(row.temperature_exposures) },
  ];
}

export function actualPipeline(row) {
  if (!row || typeof row !== "object") throw new TypeError("A decision row is required.");
  const exception = row.status === "exception";
  const inputIssues = row.input_issues ?? [];
  const gaps = row.requirement_gaps ?? [];
  const reasons = row.screening_reason_codes ?? [];
  const candidates = row.screened_candidates ?? [];
  const supplierLookup = row.supplier_application_lookup;
  const supplierLeadCount = supplierLookup?.leads.length ?? 0;
  const eligible = candidates.filter((candidate) => candidate.status === "eligible_for_shortlist");
  const excluded = candidates.filter((candidate) => candidate.status === "excluded");
  const unresolved = candidates.filter((candidate) => candidate.status === "unresolved");
  const context = actualContext(row);
  const scenario = row.scenario;
  const composition = [
    ["Moisture", numberWithUnit(scenario?.moisture_content_pct, "%")],
    ["Fat", numberWithUnit(scenario?.oil_fat_content_pct, "%")],
    ["pH", numberWithUnit(scenario?.pH)],
  ].filter(([, value]) => value !== null).map(([label, value]) => `${label} ${value}`).join(" · ");
  const respiration = numberWithUnit(scenario?.respiration_rate);
  const respirationTemperature = numberWithUnit(scenario?.respiration_reference_temperature_c, "°C");
  const respirationInput = respiration
    ? `${respiration} ${scenario.respiration_rate_unit || "(unit not reported)"}${respirationTemperature ? ` at ${respirationTemperature}` : ""}`
    : "Respiration rate not reported";
  const notReached = stage("not_reached", "This step has no interpretable scenario to process.", "—", "—", "Stopped at validation");
  const screenState = row.candidate_screening_allowed === false
    ? "held" : candidates.length ? "screened" : "unresolved";
  const screeningPermission = row.candidate_screening_allowed === true
    ? "allowed" : row.candidate_screening_allowed === false ? "held" : "not reported";
  const supplierNote = supplierLookup
    ? `; ${supplierLeadCount} unapproved supplier lead${supplierLeadCount === 1 ? "" : "s"}`
    : "";
  const packageScreen = stage(
    screenState,
    supplierLookup
      ? "Supplier applications are research leads; only reviewed complete structures enter the package screen."
      : "The structure screen preserves eligible, excluded and unresolved outcomes.",
    `${candidates.length} reviewed candidate${candidates.length === 1 ? "" : "s"} shown; screening ${screeningPermission}`,
    supplierLookup
      ? `${supplierLeadCount} source-listed application${supplierLeadCount === 1 ? "" : "s"}; food scope, service range and exact transfer evidence`
      : "Food scope, service range and exact transfer evidence",
    `${eligible.length} eligible · ${excluded.length} excluded · ${unresolved.length} unresolved${supplierNote}`,
    reasons,
  );

  return [
    stage("recorded", "The source row is present in the audited batch.", exception ? `Source row ${row.source_row_number}` : `${context[0].value} · ${context[1].value}`, exception ? "Food and condition fields await validation" : `Source row ${row.source_row_number}; ${context[3].value}`, row.record_id || "Record ID not available"),
    exception
      ? stage("held", "Validation or exact food matching did not complete.", row.record_id || "Input row", "Required values and food-reference identity", `${inputIssues.length} input issue${inputIssues.length === 1 ? "" : "s"}`, inputIssues.map((item) => item.code))
      : stage("recorded", "The row was interpretable and matched to a food reference.", row.scenario?.commodity_type || row.record_id || "Scenario", "Validated input and exact reference join", row.food_reference_id || "Food reference not shown"),
    exception
      ? notReached
      : stage(gaps.length ? "gaps_recorded" : "recorded", "The food-needs card is present; open gaps remain visible.", `${context[2].value}; ${composition || "food composition not projected"}`, `Exposure: ${context[3].value}`, gaps.length ? `${gaps.length} requirement gap${gaps.length === 1 ? "" : "s"}` : "No requirement gaps reported", gaps),
    exception
      ? notReached
      : row.produce_route_status === "confirmed_non_respiring"
        ? stage("bypassed", "The reviewed route is non-respiring, so the produce-only branch is bypassed.", "Confirmed non-respiring route", `Recorded temperature phases: ${context[3].value}`, "Continue to package screening")
        : row.produce_route_status === "confirmed_respiring" || row.produce_route_status === "respiration_evidence_present"
          ? stage("limited", "A respiration-related route is present; this view cannot certify MAP safety.", `${row.produce_route_status}; ${respirationInput}`, `Gas and water diagnostics across ${context[3].value}`, "Produce safety not certified")
          : stage("unresolved", "The produce route is unclassified or not carried by this report.", `${row.produce_route_status || "Route not reported"}; ${respirationInput}`, "Reviewed route classification", "Route remains unresolved"),
    exception
      ? notReached
      : packageScreen,
    exception
      ? notReached
      : stage(eligible.length ? "preliminary" : "unavailable", "Only comparable, eligible structures can receive a protection-only preference.", `${eligible.length} eligible structure${eligible.length === 1 ? "" : "s"}`, "Non-dominated protection comparison", row.preliminary_preferred_structure_id || "No unique preliminary preference"),
    stage("withheld", "No trained material model is deployed; shelf-life prediction is deferred.", "Reviewed outcome labels not supplied", "Independent validation and release gate", "Prediction withheld"),
    stage("recorded", "This row's current status and trace are preserved in the report.", `Source row ${row.source_row_number}`, "Versioned decision contract", row.status.replaceAll("_", " ")),
  ];
}
