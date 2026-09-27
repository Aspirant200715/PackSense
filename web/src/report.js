// The browser accepts only the conservative backend projection. These checks
// protect the UI from accidentally displaying a preliminary screen as a
// released prediction; they are not a substitute for backend validation.

const ROW_STATUSES = new Set(["exception", "not_ready", "preliminary_shortlist"]);
const CANDIDATE_STATUSES = new Set(["excluded", "unresolved", "eligible_for_shortlist"]);
const TRACE_FIELDS = [
  "scenario_sha256", "food_master_sha256", "material_master_sha256",
  "route_register_sha256", "assessment_register_sha256",
  "structure_catalogue_sha256", "structure_review_register_sha256",
  "transfer_register_sha256", "public_candidate_catalogue_sha256",
];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function isTextOrNull(value) {
  return value === null || typeof value === "string";
}

function isFiniteOrNull(value) {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

export function validateDecisionReport(report) {
  requireCondition(isObject(report), "The selected file must contain a JSON object.");
  requireCondition(report.contract_version === "frontend-decision-v1", "This is not a frontend-decision-v1 report.");
  requireCondition(report.source_batch_version === "basic-recommendation-batch-v1", "The source batch version is unsupported.");
  requireCondition(isObject(report.model) && report.model.task === "material_suitability_ranking" && report.model.status === "not_deployed" && report.model.prediction_available === false && report.model.model_version === null, "The model state is unsupported by this frontend.");
  requireCondition(report.recommendation_release_status === "withheld", "This frontend cannot display a released recommendation.");
  requireCondition(isObject(report.trace), "The report is missing source trace information.");
  for (const field of TRACE_FIELDS) {
    requireCondition(report.trace[field] === null || (typeof report.trace[field] === "string" && /^[0-9a-f]{64}$/i.test(report.trace[field])), `The ${field} source fingerprint is invalid.`);
  }
  requireCondition(Array.isArray(report.rows) && report.rows.length > 0, "The report has no decision rows.");
  requireCondition(Number.isInteger(report.total_rows) && report.total_rows === report.rows.length, "The report row count does not match its contents.");

  const sourceRows = new Set();
  report.rows.forEach((row, index) => {
    const location = `Row ${index + 1}`;
    requireCondition(isObject(row), `${location} is not a decision object.`);
    requireCondition(Number.isInteger(row.source_row_number) && row.source_row_number > 0, `${location} has an invalid source row number.`);
    requireCondition(!sourceRows.has(row.source_row_number), `${location} duplicates a source row number.`);
    sourceRows.add(row.source_row_number);
    requireCondition(ROW_STATUSES.has(row.status), `${location} has an unsupported status.`);
    requireCondition(isTextOrNull(row.record_id) && isTextOrNull(row.food_reference_id), `${location} has an invalid identity.`);
    requireCondition(row.scenario === undefined || row.scenario === null || isObject(row.scenario), `${location} has an invalid scenario summary.`);
    if (isObject(row.scenario)) {
      requireCondition(typeof row.scenario.commodity_type === "string" && row.scenario.commodity_type.trim().length > 0, `${location} has no commodity name.`);
      for (const field of ["moisture_content_pct", "oil_fat_content_pct", "pH", "net_pack_quantity", "respiration_rate", "respiration_reference_temperature_c"]) {
        requireCondition(isFiniteOrNull(row.scenario[field]), `${location} has an invalid ${field} value.`);
      }
    }
    requireCondition(isFiniteOrNull(row.target_shelf_life_days), `${location} has an invalid requested shelf-life target.`);
    requireCondition(Array.isArray(row.input_issues) && Array.isArray(row.requirement_gaps) && Array.isArray(row.screening_reason_codes) && Array.isArray(row.warnings), `${location} is missing a reason list.`);
    requireCondition(Array.isArray(row.temperature_exposures) && Array.isArray(row.screened_candidates), `${location} is missing its exposure or candidate list.`);
    requireCondition(row.package_feasible === false && row.recommended_structure_id === null && row.material_prediction === null && row.predicted_shelf_life_days === null, `${location} makes a prediction or feasibility claim this contract cannot display.`);

    row.temperature_exposures.forEach((exposure) => {
      requireCondition(isObject(exposure) && typeof exposure.phase === "string" && typeof exposure.temperature_c === "number" && Number.isFinite(exposure.temperature_c), `${location} has an invalid temperature exposure.`);
      requireCondition(exposure.relative_humidity_pct === undefined || isFiniteOrNull(exposure.relative_humidity_pct), `${location} has an invalid exposure humidity.`);
      requireCondition(exposure.duration_hours === undefined || isFiniteOrNull(exposure.duration_hours), `${location} has an invalid exposure duration.`);
    });

    const eligibleIds = new Set();
    const candidateIds = new Set();
    row.screened_candidates.forEach((candidate) => {
      requireCondition(isObject(candidate) && typeof candidate.structure_id === "string" && candidate.structure_id.length > 0, `${location} has an invalid candidate.`);
      requireCondition(!candidateIds.has(candidate.structure_id), `${location} duplicates a candidate.`);
      candidateIds.add(candidate.structure_id);
      requireCondition(CANDIDATE_STATUSES.has(candidate.status) && Array.isArray(candidate.reason_codes) && Array.isArray(candidate.layers), `${location} has an unsupported candidate shape.`);
      if (candidate.status === "eligible_for_shortlist") eligibleIds.add(candidate.structure_id);
    });

    if (row.status === "exception") {
      requireCondition(row.input_issues.length > 0 && row.requirement_gaps.length === 0 && row.screening_reason_codes.length === 0 && row.warnings.length === 0 && row.screened_candidates.length === 0 && row.temperature_exposures.length === 0 && row.preliminary_preferred_structure_id === null && row.scenario == null && row.food_reference_id === null && row.target_shelf_life_days === null, `${location} is an inconsistent input exception.`);
    } else {
      requireCondition(row.input_issues.length === 0, `${location} mixes input exceptions with screening.`);
      requireCondition(row.status === "preliminary_shortlist" ? eligibleIds.size > 0 : eligibleIds.size === 0, `${location} has an inconsistent shortlist status.`);
      requireCondition(row.preliminary_preferred_structure_id === null || eligibleIds.has(row.preliminary_preferred_structure_id), `${location} has an unsupported preliminary preference.`);
    }
  });
  return report;
}

export function parseDecisionReport(text) {
  let report;
  try {
    report = JSON.parse(text);
  } catch {
    throw new Error("The selected file is not valid JSON.");
  }
  if (isObject(report) && report.batch_version === "basic-recommendation-batch-v1") {
    throw new Error("This is a backend batch report. Convert it with packsense.frontend_contract before importing.");
  }
  return validateDecisionReport(report);
}

export function summarizeReport(report) {
  const counts = { total: report.rows.length, exception: 0, not_ready: 0, preliminary_shortlist: 0 };
  for (const row of report.rows) counts[row.status] += 1;
  return counts;
}

export function readableCode(code) {
  if (typeof code !== "string") return "Unspecified reason";
  const normalized = code.replaceAll("_", " ").replace(/\s+/g, " ").trim();
  return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : "Unspecified reason";
}
