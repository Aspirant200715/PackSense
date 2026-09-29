import { parseDecisionReport, readableCode, summarizeReport } from "./report.js";
import { actualContext, actualPipeline, STAGES, walkthroughStage } from "./pipeline.js";
import { filterPublishedApplications, validatePublishedApplications } from "./catalogue.js";
import { deriveReviewItems } from "./review.js";
import { scenarioPayload, validateFoodLookup } from "./interactive.js";
import { groupSourceOptions } from "./options.js";

const VIEWS = new Set(["overview", "evaluate", "decisions", "pipeline", "evidence"]);
const PAGE_SIZE = 12;
const MAX_FILE_BYTES = 100 * 1024 * 1024;
const TRACE_LABELS = {
  scenario_sha256: "Scenario batch",
  food_master_sha256: "Food reference master",
  material_master_sha256: "Material reference master",
  route_register_sha256: "Produce route register",
  assessment_register_sha256: "Food assessment register",
  structure_catalogue_sha256: "Structure catalogue",
  structure_review_register_sha256: "Structure review register",
  transfer_register_sha256: "Transfer evidence register",
  public_candidate_catalogue_sha256: "Public candidate catalogue",
};

const state = {
  report: null,
  fileName: null,
  reportOrigin: null,
  publishedApplications: null,
  publishedSearch: "",
  publishedCompareIndices: [],
  foodSearchResults: [],
  foodMasterSha256: null,
  selectedFood: null,
  submittedFoodProfile: null,
  canEvaluate: false,
  evaluationBusy: false,
  view: "overview",
  search: "",
  filter: "all",
  page: 1,
  selectedIndex: null,
  pipelineMode: "walkthrough",
  pipelineRoute: "non_respiring",
  pipelineStep: 0,
  pipelineRowIndex: 0,
  pipelineOptionsFor: null,
  backendMode: "checking",
  backendBusy: false,
};
let playbackTimer = null;
let foodSearchTimer = null;
let foodSearchAbort = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function displayValue(value, fallback = "Not reported") {
  return value === null || value === undefined || value === "" ? fallback : escapeHtml(value);
}

function formatNumber(value, suffix = "") {
  return typeof value === "number" && Number.isFinite(value)
    ? `${new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(value)}${suffix}`
    : "Not reported";
}

function statusLabel(status) {
  return {
    exception: "Input exception",
    not_ready: "Needs evidence",
    preliminary_shortlist: "Preliminary shortlist",
    excluded: "Excluded",
    unresolved: "Unresolved",
    eligible_for_shortlist: "Shortlisted",
  }[status] ?? readableCode(status);
}

function statusBadge(status) {
  const kind = {
    exception: "red", not_ready: "amber", preliminary_shortlist: "teal",
    excluded: "red", unresolved: "amber", eligible_for_shortlist: "teal",
  }[status] ?? "neutral";
  return `<span class="status-badge status-${kind}">${escapeHtml(statusLabel(status))}</span>`;
}

function notify(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("is-error", error);
  toast.hidden = false;
  clearTimeout(notify.timeout);
  notify.timeout = setTimeout(() => { toast.hidden = true; }, 5200);
}

function setTheme(theme) {
  const selected = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = selected;
  $("#theme-toggle").setAttribute("aria-pressed", String(selected === "dark"));
  $("#theme-toggle").setAttribute("aria-label", `Switch to ${selected === "dark" ? "light" : "dark"} mode`);
  $("#theme-toggle-label").textContent = selected === "dark" ? "Light mode" : "Dark mode";
  $("meta[name='theme-color']").content = selected === "dark" ? "#0a1020" : "#edf1f7";
  try { localStorage.setItem("packsense-theme", selected); } catch { /* Private mode may block storage. */ }
}

function updatePlaybackControls() {
  const playing = playbackTimer !== null;
  const actualTrace = state.pipelineMode === "actual";
  const subject = actualTrace ? "report trace" : "guided tour";
  $(".pipeline-studio").classList.toggle("is-playing", playing);
  $("#guide-play-label").textContent = playing ? (actualTrace ? "Pause trace" : "Pause tour") : state.pipelineStep === STAGES.length - 1 ? (actualTrace ? "Replay trace" : "Replay tour") : `Play ${subject}`;
  $("#guide-play-icon").textContent = playing ? "Ⅱ" : "▶";
  $("#pipeline-play").setAttribute("aria-label", playing ? `Pause ${subject}` : state.pipelineStep === STAGES.length - 1 ? `Replay ${subject}` : `Play ${subject}`);
  $("#pipeline-play").setAttribute("aria-pressed", String(playing));
  $("#guide-playback-status").textContent = playing
    ? actualTrace ? "Following the reported row · pause to inspect any check." : "Playing automatically · select any stage or pause to inspect it."
    : state.pipelineStep === STAGES.length - 1 ? (actualTrace ? "Report trace complete · inspect the result or replay." : "Tour complete · replay or explore any stage.")
      : actualTrace ? "Press Play to follow this reported row through every check." : "Press Play to watch the stages advance automatically.";
}

function stopPlayback() {
  if (playbackTimer !== null) clearInterval(playbackTimer);
  playbackTimer = null;
  updatePlaybackControls();
}

function startPlayback() {
  if (state.view !== "pipeline" || playbackTimer !== null
      || (state.pipelineMode === "actual" && !state.report)) return;
  if (state.pipelineStep === STAGES.length - 1) state.pipelineStep = 0;
  playbackTimer = setInterval(() => {
    if (state.pipelineStep >= STAGES.length - 1) {
      stopPlayback();
      return;
    }
    state.pipelineStep += 1;
    renderPipeline();
    if (state.pipelineStep === STAGES.length - 1) stopPlayback();
  }, 4000);
  renderPipeline();
}

function enterWorkspace(stage = 0, autoplay = true) {
  $("#welcome-screen").hidden = true;
  $(".app-shell").hidden = false;
  state.pipelineMode = "walkthrough";
  state.pipelineStep = stage;
  goTo("pipeline");
  renderPipeline();
  if (autoplay && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) startPlayback();
}

function returnToWelcome() {
  stopPlayback();
  $(".app-shell").hidden = true;
  $("#welcome-screen").hidden = false;
  window.scrollTo(0, 0);
}

function goTo(view) {
  if (!VIEWS.has(view)) return;
  if (view !== "pipeline") stopPlayback();
  state.view = view;
  $$(".view").forEach((section) => {
    const active = section.id === `view-${view}`;
    section.hidden = !active;
    section.classList.toggle("is-visible", active);
  });
  $$("[data-nav]").forEach((button) => {
    const active = button.dataset.nav === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
}

function enterPublishedApplications() {
  $("#welcome-screen").hidden = true;
  $(".app-shell").hidden = false;
  goTo("overview");
}

function enterEvaluation() {
  $("#welcome-screen").hidden = true;
  $(".app-shell").hidden = false;
  goTo("evaluate");
  $("#food-search").focus();
}

function renderSelectedFood() {
  const food = state.selectedFood;
  const root = $("#selected-food");
  root.hidden = !food;
  $("#evaluate-submit").disabled = !food?.form_ready || state.evaluationBusy;
  $("#evaluate-submit").textContent = state.evaluationBusy ? "Evaluating…" : "Evaluate this scenario →";
  $("#intake-submit-note").textContent = !food
    ? "Select a complete food reference to continue."
    : !food.form_ready ? `Missing reference values: ${food.missing_reference_properties.join(", ")}.`
      : "The decision will show any unresolved evidence; it will not claim a trained prediction.";
  if (!food) { root.innerHTML = ""; return; }
  const sourceLines = food.source_citations.split(" | ").map((line) => `<span>${escapeHtml(line)}</span>`).join("");
  root.innerHTML = `<div class="selected-food-top"><span>SELECTED REFERENCE · ${escapeHtml(food.food_reference_id)}</span><button type="button" class="text-button" data-clear-food>Change food</button></div><h3>${escapeHtml(food.commodity_type)}</h3><p>${food.form_ready ? "These are source-reference properties, not measurements of your batch." : `This reference cannot run yet: ${food.missing_reference_properties.map(readableCode).join(", ")} is missing.`}</p><dl><div><dt>Moisture</dt><dd>${formatNumber(food.moisture_content_pct, "%")}</dd></div><div><dt>Oil / fat</dt><dd>${formatNumber(food.oil_fat_content_pct, "%")}</dd></div><div><dt>pH</dt><dd>${formatNumber(food.pH)}</dd></div>${food.respiration_rate === null ? "" : `<div><dt>Reference respiration</dt><dd>${formatNumber(food.respiration_rate)} ${escapeHtml(food.respiration_rate_unit)} at ${formatNumber(food.respiration_reference_temperature_c, " °C")}</dd></div>`}</dl><div class="selected-food-basis"><strong>pH evidence: ${escapeHtml(readableCode(food.pH_evidence))}</strong><span>${displayValue(food.pH_basis, "No pH basis reported")}</span></div><details><summary>Reference citations</summary><div class="selected-food-sources">${sourceLines}</div></details>`;
}

function renderFoodSearch() {
  const results = state.foodSearchResults;
  $("#food-search-results").innerHTML = results.map((food) => `
    <button type="button" class="food-search-option" data-food-id="${escapeHtml(food.food_reference_id)}"><span><strong>${escapeHtml(food.commodity_type)}</strong><small>${escapeHtml(food.food_reference_id)}${food.food_group ? ` · ${escapeHtml(food.food_group)}` : ""}</small></span><span class="food-search-state ${food.form_ready ? "is-ready" : ""}">${food.form_ready ? "Properties available" : "Missing source values"}</span></button>`).join("");
  renderSelectedFood();
}

async function searchFoods(query) {
  if (foodSearchAbort) foodSearchAbort.abort();
  foodSearchAbort = new AbortController();
  $("#food-search-status").textContent = "Searching the configured food reference…";
  try {
    const response = await fetch(`/api/foods?q=${encodeURIComponent(query)}`, {
      cache: "no-store", signal: foodSearchAbort.signal,
    });
    if (!response.ok) throw new Error(await responseError(response));
    const result = validateFoodLookup(await response.json());
    if ($("#food-search").value.trim() !== query) return;
    state.foodSearchResults = result.foods;
    state.foodMasterSha256 = result.food_master_sha256;
    $("#food-search-status").textContent = result.total_matches
      ? `${result.form_ready_matches.toLocaleString()} of ${result.total_matches.toLocaleString()} matching references have complete basic properties. Showing ${result.foods.length}.`
      : "No exact source food matches this search. Try a different name or reference ID.";
    renderFoodSearch();
  } catch (error) {
    if (error.name === "AbortError") return;
    state.foodSearchResults = [];
    state.foodMasterSha256 = null;
    $("#food-search-status").textContent = error instanceof Error ? error.message : "Food search failed.";
    renderFoodSearch();
  }
}

async function submitEvaluation(event) {
  event.preventDefault();
  const form = $("#scenario-form");
  if (!form.reportValidity()) return;
  $("#evaluation-error").hidden = true;
  let payload;
  try {
    payload = scenarioPayload(Object.fromEntries(new FormData(form)), state.selectedFood, state.foodMasterSha256);
  } catch (error) {
    $("#evaluation-error").textContent = error.message;
    $("#evaluation-error").hidden = false;
    return;
  }
  state.evaluationBusy = true;
  renderSelectedFood();
  try {
    const response = await fetch("/api/evaluate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) {
      const failure = new Error(typeof result.error === "string" ? result.error : `Backend returned ${response.status}.`);
      failure.field = result.field;
      throw failure;
    }
    if (result.contract_version !== "interactive-evaluation-v1"
        || result.input_origin !== "browser_submitted"
        || result.food_profile?.food_reference_id !== payload.food_reference_id) {
      throw new Error("The evaluation response is invalid.");
    }
    const report = parseDecisionReport(JSON.stringify(result.report));
    if (report.rows.length !== 1 || report.rows[0].food_reference_id !== payload.food_reference_id
        || report.trace.food_master_sha256 !== payload.food_master_sha256) {
      throw new Error("The result does not match the submitted food reference.");
    }
    acceptReport(report, "Your submitted scenario", "decisions", "browser", result.food_profile);
  } catch (error) {
    const errorBox = $("#evaluation-error");
    errorBox.textContent = error instanceof Error ? error.message : "The evaluation did not complete.";
    errorBox.hidden = false;
    const field = error.field ? form.elements.namedItem(error.field) : null;
    if (field?.focus) field.focus();
    else errorBox.scrollIntoView({ block: "center" });
  } finally {
    state.evaluationBusy = false;
    renderSelectedFood();
  }
}

function renderPublishedApplications() {
  const applications = state.publishedApplications.applications;
  const visible = filterPublishedApplications(applications, state.publishedSearch);
  const selected = state.publishedCompareIndices;
  $("#published-applications-count").textContent = `${visible.length} of ${applications.length} source-listed ${applications.length === 1 ? "use" : "uses"}`;
  $("#published-selection-hint").textContent = selected.length
    ? `${selected.length} of 2 selected · source uses are not suitability matches`
    : "Select two source uses to compare their listed conditions.";
  $("#published-applications-list").innerHTML = visible.length ? visible.map(({ item, index }) => `
    <article class="published-application-card">
      <div class="published-application-top"><span>MANUFACTURER-LISTED USE</span><span>${escapeHtml(item.source_publisher)}</span></div>
      <h3>${escapeHtml(item.food)}</h3>
      <div class="published-application-product"><strong>${escapeHtml(item.product_code)}</strong><span>${escapeHtml(item.pack_format)}</span></div>
      <dl><div><dt>Published fill</dt><dd>${formatNumber(item.quantity, ` ${escapeHtml(item.quantity_unit)}`)}</dd></div><div><dt>Storage</dt><dd>${formatNumber(item.storage_temperature_min_c, " °C")} to ${formatNumber(item.storage_temperature_max_c, " °C")}</dd></div>${item.excursion_max_c === null ? "" : `<div><dt>Listed excursion</dt><dd>Up to ${formatNumber(item.excursion_max_c, " °C")} for ${formatNumber(item.excursion_max_hours, " h")}</dd></div>`}</dl>
      <div class="published-application-actions"><button type="button" class="compare-button${selected.includes(index) ? " is-selected" : ""}" data-compare-index="${index}" aria-pressed="${selected.includes(index)}">${selected.includes(index) ? "Selected for comparison" : "Add to compare"}</button><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">View source ↗</a></div>
      <div class="published-application-source">${escapeHtml(item.source_locator)}</div>
    </article>`).join("") : `<div class="published-no-match"><strong>No published uses match “${escapeHtml(state.publishedSearch.trim())}”.</strong><p>Try another food, product code or package format. No suitability conclusion follows from an empty search.</p></div>`;
  $("#published-comparison").hidden = selected.length === 0;
  $("#published-comparison-content").innerHTML = selected.length < 2
    ? `<p class="published-comparison-waiting">Choose one more published use to compare its source-listed conditions.</p>`
    : `<div class="published-comparison-grid">${selected.map((index) => {
      const item = applications[index];
      return `<article class="published-comparison-card"><div><span>MANUFACTURER-LISTED</span><strong>${escapeHtml(item.product_code)}</strong><small>${escapeHtml(item.source_publisher)}</small></div><dl><div><dt>Food</dt><dd>${escapeHtml(item.food)}</dd></div><div><dt>Package</dt><dd>${escapeHtml(item.pack_format)}</dd></div><div><dt>Fill</dt><dd>${formatNumber(item.quantity, ` ${escapeHtml(item.quantity_unit)}`)}</dd></div><div><dt>Storage</dt><dd>${formatNumber(item.storage_temperature_min_c, " °C")} to ${formatNumber(item.storage_temperature_max_c, " °C")}</dd></div><div><dt>Excursion</dt><dd>${item.excursion_max_c === null ? "Not listed" : `Up to ${formatNumber(item.excursion_max_c, " °C")} for ${formatNumber(item.excursion_max_hours, " h")}`}</dd></div></dl><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">Check source ↗</a></article>`;
    }).join("")}</div>`;
}

function renderOverview() {
  $("#overview-results").hidden = !state.report;
  const showPublished = Boolean(state.publishedApplications) && !state.report;
  $("#overview-title").textContent = showPublished ? "Explore package uses" : "Overview";
  $("#overview-description").textContent = showPublished
    ? "Search manufacturer-listed food applications and compare the published conditions."
    : "Explore the method or inspect the evidence behind a real batch.";
  $("#overview-empty").hidden = Boolean(state.report) || showPublished;
  $("#published-applications").hidden = !showPublished;
  if (showPublished) renderPublishedApplications();
  if (!state.report) return;
  const counts = summarizeReport(state.report);
  $("#metric-total").textContent = counts.total.toLocaleString();
  $("#metric-not-ready").textContent = counts.not_ready.toLocaleString();
  $("#metric-shortlist").textContent = counts.preliminary_shortlist.toLocaleString();
  $("#metric-exception").textContent = counts.exception.toLocaleString();
  const root = $("#overview-records");
  root.innerHTML = `<div class="overview-record-list">${state.report.rows.slice(0, 5).map((row, index) => `
    <button type="button" class="overview-record" data-select-row="${index}">
      <span class="overview-record-id"><strong>${escapeHtml(row.scenario?.commodity_type || row.record_id || `Source row ${row.source_row_number}`)}</strong><small>${escapeHtml(row.record_id || `Row ${row.source_row_number}`)} · Row ${row.source_row_number}</small></span>
      ${statusBadge(row.status)}<span class="record-chevron" aria-hidden="true">→</span>
    </button>`).join("")}</div>`;
}

function filteredRows() {
  if (!state.report) return [];
  const query = state.search.trim().toLocaleLowerCase();
  return state.report.rows.map((row, index) => ({ row, index })).filter(({ row }) => {
    if (state.filter !== "all" && row.status !== state.filter) return false;
    if (!query) return true;
    return [row.record_id, row.food_reference_id, row.scenario?.commodity_type, String(row.source_row_number)]
      .some((value) => String(value ?? "").toLocaleLowerCase().includes(query));
  });
}

function renderReasonGroup(title, items, kind) {
  if (!items.length) return "";
  return `<details class="inspector-disclosure" ${kind === "red" || title === "Evidence gaps" ? "open" : ""}><summary><span>${escapeHtml(title)}</span><small>${items.length} recorded</small></summary><div class="reason-stack">${items.map((item) => {
    const isIssue = typeof item === "object" && item !== null;
    const code = isIssue ? item.code : item;
    const field = isIssue ? item.field : null;
    const message = isIssue ? item.message : null;
    return `<div class="reason-card reason-${kind}"><span class="reason-mark" aria-hidden="true"></span><div><strong>${escapeHtml(field ? `${field}: ${readableCode(code)}` : readableCode(code))}</strong>${message ? `<p>${escapeHtml(message)}</p>` : ""}<code>${escapeHtml(code ?? "unknown")}</code></div></div>`;
  }).join("")}</div></details>`;
}

function renderExposures(exposures) {
  if (!exposures.length) return "";
  return `<details class="inspector-disclosure"><summary><span>Temperature exposure</span><small>${exposures.length} phases</small></summary><div class="exposure-list">${exposures.map((item) => `
    <div class="exposure-row"><div><strong>${escapeHtml(readableCode(item.phase))}</strong>${item.safety_check_only ? `<small>Safety excursion check</small>` : item.duration_hours != null ? `<small>${formatNumber(item.duration_hours, " h")} duration</small>` : `<small>Duration not specified</small>`}</div><div class="exposure-values"><strong>${formatNumber(item.temperature_c, " °C")}</strong><small>RH ${formatNumber(item.relative_humidity_pct, "%")}</small></div></div>`).join("")}</div></details>`;
}

function renderCandidates(row) {
  if (!row.screened_candidates.length) return `<details class="inspector-disclosure"><summary><span>Package structures</span><small>None recorded</small></summary><div class="quiet-empty">No complete structure is available for this row in the current report.</div></details>`;
  return `<details class="inspector-disclosure" ${row.status === "preliminary_shortlist" ? "open" : ""}><summary><span>Screened structures</span><small>${row.screened_candidates.length} candidates</small></summary><div class="candidate-list">${row.screened_candidates.map((candidate) => `
    <details class="candidate-card"><summary><span class="candidate-main"><strong>${escapeHtml(candidate.structure_id)}</strong><small>${displayValue(candidate.pack_format, "Format not reported")}</small></span>${statusBadge(candidate.status)}<span class="candidate-expand" aria-hidden="true">+</span></summary><div class="candidate-body"><div class="candidate-facts"><div><span>PROTECTION RANK</span><strong>${candidate.protection_rank == null ? "Not ranked" : escapeHtml(candidate.protection_rank)}</strong></div><div><span>SERVICE RANGE</span><strong>${formatNumber(candidate.service_temperature_min_c, " °C")} to ${formatNumber(candidate.service_temperature_max_c, " °C")}</strong></div></div><div class="candidate-subhead">Layer structure</div>${candidate.layers.length ? `<div class="layer-list">${candidate.layers.map((layer, index) => `<div class="layer-row"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(layer.grade_id ?? "Unspecified grade")}</strong><small>${formatNumber(layer.thickness_um, " µm")}${layer.role ? ` · ${escapeHtml(layer.role)}` : ""}${layer.is_food_contact ? " · food contact" : ""}</small></div>`).join("")}</div>` : `<p class="candidate-empty">Layer details not supplied.</p>`}${candidate.reason_codes.length ? `<div class="candidate-subhead">Screening reasons</div><div class="candidate-reasons">${candidate.reason_codes.map((reason) => `<span>${escapeHtml(readableCode(reason))}</span>`).join("")}</div>` : ""}</div></details>`).join("")}</div></details>`;
}

function renderSourceOption(lead, state) {
  const labels = {
    exact: "Listed conditions align · unverified",
    related: "Related raw-food name · identity review needed",
    outside: "Outside listed use or needs review",
  };
  return `<article class="supplier-lead source-option-card" data-source-option-state="${state}">
    <div class="supplier-lead-heading"><div><strong>${escapeHtml(lead.product_code)}</strong><small>${escapeHtml(lead.candidate_id)} · ${escapeHtml(lead.pack_format)}</small></div><span class="supplier-match-state">${labels[state]}</span></div>
    <div class="supplier-conditions"><span>Supplier lists <strong>${escapeHtml(lead.supplier_application_food)}</strong></span><span>Fill <strong>${formatNumber(lead.published_quantity, ` ${escapeHtml(lead.published_quantity_unit)}`)}</strong></span><span>Storage <strong>${formatNumber(lead.published_storage_temperature_min_c, " °C")} to ${formatNumber(lead.published_storage_temperature_max_c, " °C")}</strong></span>${lead.published_excursion_max_c === null ? "" : `<span>Excursion <strong>up to ${formatNumber(lead.published_excursion_max_c, " °C")} for ${formatNumber(lead.published_excursion_max_hours, " h")}</strong></span>`}</div>
    ${lead.reason_codes.length ? `<p class="supplier-lead-reasons"><strong>Unresolved comparison:</strong> ${lead.reason_codes.map((code) => escapeHtml(readableCode(code))).join(" · ")}</p>` : ""}
    <details class="source-option-checks"><summary>Checks still needed (${lead.approval_blockers.length})</summary><ul>${lead.approval_blockers.map((code) => `<li>${escapeHtml(readableCode(code))}</li>`).join("")}</ul></details>
    <div class="supplier-source"><span>Source rights: ${escapeHtml(readableCode(lead.source_rights_review_status))} · ${escapeHtml(lead.source_id)} · ${escapeHtml(lead.source_locator)}</span><a href="${escapeHtml(lead.source_url)}" target="_blank" rel="noopener noreferrer">Open manufacturer source ↗</a></div>
  </article>`;
}

function renderPackagePathway(row) {
  const lookup = row.supplier_application_lookup;
  const groups = groupSourceOptions(lookup?.leads ?? []);
  const visible = [
    ...groups.exactConditions.map((lead) => renderSourceOption(lead, "exact")),
    ...groups.relatedFoodName.map((lead) => renderSourceOption(lead, "related")),
  ];
  const outside = groups.outsidePublishedUse.map((lead) => renderSourceOption(lead, "outside"));
  const eligible = row.screened_candidates.filter((candidate) => candidate.status === "eligible_for_shortlist");
  const blockers = [...new Set([...row.screening_reason_codes, ...row.requirement_gaps])].slice(0, 3);
  const preliminary = row.status === "preliminary_shortlist";
  return `<section class="package-pathway" aria-label="Package option evidence tiers">
    <div class="package-pathway-intro"><span>PACKAGE PATHWAY</span><h3>What can we show for this scenario?</h3><p class="supplier-boundary">A supplier-listed use is a research option, not a material prediction, approved package, or suitability label. Only a reviewed complete structure can enter the separate engineering screen.</p></div>
    <div class="package-tier"><div class="package-tier-heading"><span>01 / SOURCE-LISTED OPTIONS</span><strong>${groups.exactConditions.length} listed-condition ${groups.exactConditions.length === 1 ? "match" : "matches"} · ${groups.relatedFoodName.length} related food ${groups.relatedFoodName.length === 1 ? "name" : "names"}</strong></div>
      ${lookup ? (visible.length ? `<div class="supplier-leads">${visible.join("")}</div>` : `<p class="package-tier-empty">No source-listed use aligns with this food and scenario in the current catalogue.</p>`) : `<p class="package-tier-empty">No supplier catalogue was attached to this report.</p>`}
      ${outside.length ? `<details class="outside-source-options"><summary>${outside.length} additional ${outside.length === 1 ? "use differs" : "uses differ"} from this scenario</summary><div class="supplier-leads">${outside.join("")}</div></details>` : ""}
    </div>
    <div class="package-tier package-tier-engineering${preliminary ? " is-preliminary" : ""}"><div class="package-tier-heading"><span>02 / ENGINEERING SHORTLIST</span><strong>${preliminary ? `${eligible.length} provisionally eligible ${eligible.length === 1 ? "structure" : "structures"}` : "Not ready to shortlist"}</strong></div>
      ${preliminary ? `<p>These complete structures passed the current narrow protection screen, not product validation.${row.preliminary_preferred_structure_id ? ` Protection-only preference: <strong>${escapeHtml(row.preliminary_preferred_structure_id)}</strong>.` : " No unique protection preference is established."}</p>` : `<p>Source-listed uses cannot bypass the evidence gate. ${blockers.length ? `Current blockers: ${blockers.map((code) => escapeHtml(readableCode(code))).join(" · ")}.` : "No reviewed complete structure is eligible in this report."} The detailed gaps are recorded below.</p>`}
    </div>
  </section>`;
}

function renderInspector(row) {
  const root = $("#record-inspector");
  if (!row) {
    root.innerHTML = `<div class="inspector-placeholder"><strong>Select a scenario</strong><p>Choose a row to inspect its evidence, temperature exposure and package screen.</p></div>`;
    return;
  }
  const submittedProfile = state.reportOrigin === "browser"
    && state.submittedFoodProfile?.food_reference_id === row.food_reference_id
    ? state.submittedFoodProfile : null;
  root.innerHTML = `<div class="inspector-header"><div class="section-kicker">SOURCE ROW ${row.source_row_number}</div><h2>${escapeHtml(row.scenario?.commodity_type || row.record_id || `Row ${row.source_row_number}`)}</h2>${row.scenario ? `<div class="inspector-record-id">Record ${escapeHtml(row.record_id)}</div>` : ""}${statusBadge(row.status)}<p>${row.status === "exception" ? "This scenario needs an input correction before screening." : row.status === "not_ready" ? "The scenario is understood, but the evidence is not sufficient for a package result." : "These structures passed a narrow protection screen. This is not a released recommendation."}</p></div>
    <div class="inspector-facts"><div><span>FOOD REFERENCE</span><strong>${displayValue(row.food_reference_id, "Not matched")}</strong></div><div><span>REQUESTED LIFE</span><strong>${row.target_shelf_life_days == null ? "Not available" : formatNumber(row.target_shelf_life_days, " days")}</strong></div></div>
    ${submittedProfile ? `<section class="submitted-profile-callout"><span>FOOD PROPERTIES FROM REFERENCE · CONDITIONS SUBMITTED BY USER</span><p>Moisture, oil/fat, pH and any respiration value came from ${escapeHtml(submittedProfile.food_reference_id)}. pH basis: ${displayValue(submittedProfile.pH_basis)}. These are not measurements of the submitted batch.</p></section>` : ""}
    ${row.status !== "exception" ? renderPackagePathway(row) : ""}
    ${row.scenario ? `<section class="inspector-section"><div class="inspector-section-title"><h3>Submitted scenario values</h3></div><div class="scenario-facts"><div><span>MOISTURE</span><strong>${formatNumber(row.scenario.moisture_content_pct, "%")}</strong></div><div><span>OIL / FAT</span><strong>${formatNumber(row.scenario.oil_fat_content_pct, "%")}</strong></div><div><span>pH</span><strong>${formatNumber(row.scenario.pH)}</strong></div><div><span>NET PACK</span><strong>${formatNumber(row.scenario.net_pack_quantity, ` ${escapeHtml(row.scenario.net_pack_quantity_unit ?? "")}`)}</strong></div><div><span>STORAGE</span><strong>${escapeHtml(readableCode(row.scenario.storage_type))}</strong></div><div><span>TRANSPORT</span><strong>${escapeHtml(readableCode(row.scenario.transport_mode))}</strong></div><div><span>HANDLING</span><strong>${escapeHtml(readableCode(row.scenario.transport_handling_severity))}</strong></div></div>${row.scenario.respiration_rate != null ? `<div class="respiration-note">Respiration: ${formatNumber(row.scenario.respiration_rate)} ${displayValue(row.scenario.respiration_rate_unit, "")} at ${formatNumber(row.scenario.respiration_reference_temperature_c, " °C")}</div>` : ""}</section>` : ""}
    ${renderReasonGroup("Input issues", row.input_issues, "red")}
    ${renderReasonGroup("Evidence gaps", row.requirement_gaps, "amber")}
    ${renderReasonGroup("Screening reasons", row.screening_reason_codes, "amber")}
    ${renderReasonGroup("Warnings", row.warnings, "neutral")}
    ${renderExposures(row.temperature_exposures)}
    ${row.status !== "exception" ? renderCandidates(row) : ""}
    <div class="inspector-boundary"><strong>Decision boundary</strong><p>Package feasibility and predicted material are withheld. A requested shelf life is not a predicted shelf life.</p></div>
    <button type="button" class="text-button inspector-trace-link" data-trace-row="${state.selectedIndex}">Follow this row through the pipeline →</button>`;
}

function renderDecisions() {
  $("#decisions-empty").hidden = Boolean(state.report);
  $("#decisions-loaded").hidden = !state.report;
  $("#report-file-label").textContent = state.fileName || "No report loaded";
  const navCount = $("#nav-record-count");
  navCount.hidden = !state.report;
  if (!state.report) return;
  navCount.textContent = state.report.rows.length.toLocaleString();
  const rows = filteredRows();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
  if (!rows.some(({ index }) => index === state.selectedIndex)) state.selectedIndex = rows[0]?.index ?? null;
  const offset = (state.page - 1) * PAGE_SIZE;
  $("#record-filter-count").textContent = `${rows.length.toLocaleString()} of ${state.report.rows.length.toLocaleString()} rows`;
  const counts = summarizeReport(state.report);
  const filterCounts = { all: counts.total, not_ready: counts.not_ready, preliminary_shortlist: counts.preliminary_shortlist, exception: counts.exception };
  $$('[data-filter]').forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    button.querySelector("span").textContent = filterCounts[button.dataset.filter].toLocaleString();
  });
  $("#record-list").innerHTML = rows.length ? rows.slice(offset, offset + PAGE_SIZE).map(({ row, index }) => `
    <button type="button" class="record-list-row${index === state.selectedIndex ? " is-selected" : ""}" data-select-row="${index}" aria-pressed="${index === state.selectedIndex}"><span class="record-identity"><strong>${escapeHtml(row.scenario?.commodity_type || row.record_id || `Row ${row.source_row_number}`)}</strong><small>#${row.source_row_number} · ${escapeHtml(row.record_id || row.food_reference_id || "Food not matched")}</small></span>${statusBadge(row.status)}</button>`).join("") : `<div class="list-no-match"><strong>No matching records</strong><p>Try another search term or status filter.</p></div>`;
  $("#record-pagination").innerHTML = rows.length > PAGE_SIZE ? `<span>Page ${state.page} of ${pages}</span><div><button type="button" class="page-button" data-page="previous" ${state.page === 1 ? "disabled" : ""} aria-label="Previous page">←</button><button type="button" class="page-button" data-page="next" ${state.page === pages ? "disabled" : ""} aria-label="Next page">→</button></div>` : `<span>${rows.length.toLocaleString()} shown</span>`;
  renderInspector(state.selectedIndex === null ? null : state.report.rows[state.selectedIndex]);
}

function renderEvidence() {
  const root = $("#trace-list");
  if (!state.report) {
    root.innerHTML = `<div class="trace-empty"><div class="trace-empty-mark" aria-hidden="true">#</div><strong>No source trace loaded</strong><p>Import a decision report to inspect the exact input fingerprints.</p><button type="button" class="button button-secondary button-small" data-import>Import report</button></div>`;
    return;
  }
  root.innerHTML = `<div class="trace-list">${Object.entries(TRACE_LABELS).map(([key, label]) => {
    const hash = state.report.trace[key];
    return `<div class="trace-row"><div><strong>${escapeHtml(label)}</strong><small>${hash ? "Source fingerprint available" : "Not supplied to this batch"}</small></div>${hash ? `<button type="button" class="hash-button" data-copy-hash="${escapeHtml(hash)}" title="Copy full SHA-256 hash"><code>${escapeHtml(String(hash).slice(0, 12))}…</code><span aria-hidden="true">↗</span></button>` : `<span class="trace-absent">—</span>`}</div>`;
  }).join("")}</div>`;
}

function renderPipeline() {
  const actualMode = state.pipelineMode === "actual";
  const hasReport = Boolean(state.report);
  $("#pipeline-guide-bar").hidden = actualMode && !hasReport;
  $("#guide-type-label").textContent = actualMode ? "REAL REPORT · RECORDED VALUES" : "HOW IT WORKS · NO LIVE RESULT";
  $("#guide-stage-caption").textContent = `Step ${state.pipelineStep + 1} of ${STAGES.length}`;
  updatePlaybackControls();
  $$('[data-pipeline-mode]').forEach((button) => {
    const active = button.dataset.pipelineMode === state.pipelineMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $$('[data-route]').forEach((button) => {
    const active = button.dataset.route === state.pipelineRoute;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("#route-control").hidden = actualMode;
  $("#actual-record-control").hidden = !actualMode || !hasReport;
  $("#pipeline-mode-note").textContent = actualMode
    ? "Audited report values only · no new inference is performed"
    : "Conceptual walkthrough · no food/package result is generated";
  $("#pipeline-empty").hidden = !actualMode || hasReport;
  $(".studio-rail").hidden = actualMode && !hasReport;
  $("#studio-focus").hidden = actualMode && !hasReport;
  $("#studio-intake-action").hidden = actualMode || state.pipelineStep !== 0;
  $("#studio-finish").hidden = actualMode || state.pipelineStep !== STAGES.length - 1;
  $("#studio-actual-finish").hidden = !actualMode || !hasReport || state.pipelineStep !== STAGES.length - 1;

  if (actualMode && hasReport) {
    state.pipelineRowIndex = Math.min(state.pipelineRowIndex, state.report.rows.length - 1);
    if (state.pipelineOptionsFor !== state.report) {
      $("#pipeline-record-select").innerHTML = state.report.rows.map((row, index) =>
        `<option value="${index}">Row ${row.source_row_number} · ${escapeHtml(row.scenario?.commodity_type || row.record_id || "Input exception")}</option>`
      ).join("");
      state.pipelineOptionsFor = state.report;
    }
    $("#pipeline-record-select").value = String(state.pipelineRowIndex);
  }

  const contextRoot = $("#actual-context");
  contextRoot.hidden = !actualMode || !hasReport;
  if (actualMode && hasReport) {
    contextRoot.innerHTML = actualContext(state.report.rows[state.pipelineRowIndex]).map(({ label, value }) =>
      `<div class="context-fact"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`
    ).join("");
  }

  const actualStages = actualMode && hasReport
    ? actualPipeline(state.report.rows[state.pipelineRowIndex])
    : null;
  const stageList = $("#pipeline-stage-list");
  const stopPosition = (index) => `${((index + 0.5) / STAGES.length) * 100}%`;
  // The page CSP blocks inline style attributes; CSSOM positions the playback marker.
  stageList.style.setProperty("--travel-start", stopPosition(state.pipelineStep));
  stageList.style.setProperty("--travel-end", stopPosition(Math.min(state.pipelineStep + 1, STAGES.length - 1)));
  stageList.innerHTML = STAGES.map((stage, index) => {
    const active = index === state.pipelineStep;
    const status = actualStages ? actualStages[index].state : actualMode ? "awaiting_report" : active ? "in_focus" : index < state.pipelineStep ? "viewed" : "upcoming";
    const statusText = actualMode ? (hasReport ? readableCode(status) : "Awaiting report") : active ? "In focus" : index < state.pipelineStep ? "Explored" : "Up next";
    return `<button type="button" class="studio-stage stage-status-${escapeHtml(status)}${active ? " is-active" : ""}${index < state.pipelineStep ? " is-past" : ""}" data-pipeline-index="${index}" ${active ? 'aria-current="step"' : ""} aria-label="Step ${index + 1}: ${escapeHtml(stage.title)}. ${escapeHtml(statusText)}" title="${escapeHtml(stage.title)}"><span class="stage-index">${stage.number}</span><span class="stage-text"><strong>${escapeHtml(stage.short)}</strong></span></button>`;
  }).join("") + '<span class="stage-traveler" aria-hidden="true"></span>';

  if (actualMode && !hasReport) return;
  const stage = actualStages
    ? { ...STAGES[state.pipelineStep], ...actualStages[state.pipelineStep] }
    : walkthroughStage(state.pipelineStep, state.pipelineRoute);
  $("#studio-state-label").textContent = actualMode ? readableCode(stage.state).toUpperCase() : "CURRENT STEP";
  $("#studio-title").textContent = stage.title;
  $("#studio-statement").textContent = stage.statement;
  $("#studio-input").textContent = stage.input;
  $("#studio-check").textContent = stage.check;
  $("#studio-output").textContent = stage.output;
  $("#studio-boundary-label").textContent = actualMode ? "READING THIS TRACE" : stage.routeNote ? "ROUTE DECISION" : "EVIDENCE BOUNDARY";
  $("#studio-boundary-text").textContent = actualMode
    ? "This stage reflects the imported decision row only. It does not prove package feasibility or run a trained predictor."
    : stage.routeNote || stage.boundary;
  const codes = actualMode ? stage.evidence : [];
  $("#studio-evidence").hidden = !codes?.length;
  $("#studio-evidence").innerHTML = codes?.length
    ? `<span>REPORTED CODES</span><div>${codes.map((code) => `<code>${escapeHtml(code)}</code>`).join("")}</div>`
    : "";
  $("#pipeline-previous").disabled = state.pipelineStep === 0;
  $("#pipeline-next").disabled = state.pipelineStep === STAGES.length - 1;
}

function render() {
  renderOverview();
  renderDecisions();
  renderEvidence();
  renderPipeline();
  renderReviewItems();
}

function setReviewOpen(open) {
  $("#review-panel").hidden = !open;
  $("#review-toggle").setAttribute("aria-expanded", String(open));
}

function renderReviewItems() {
  const items = deriveReviewItems(state);
  $("#review-count").hidden = items.length === 0;
  $("#review-count").textContent = String(items.length);
  $("#review-toggle").setAttribute("aria-label", items.length ? `Review updates: ${items.length} ${items.length === 1 ? "item" : "items"}` : "Review updates: no items");
  $("#review-items").innerHTML = items.length ? items.map((item) => `
    <button type="button" class="review-item review-item-${item.tone}" data-review-action="${item.action}"><span class="review-item-mark" aria-hidden="true"></span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span><span class="review-item-arrow" aria-hidden="true">↗</span></button>`).join("")
    : `<div class="review-empty">${state.backendMode === "checking" ? "Checking the local workspace…" : "No review items in the current workspace."}</div>`;
}

function followReviewAction(action) {
  setReviewOpen(false);
  if (["exception", "not_ready", "preliminary_shortlist"].includes(action) && state.report) {
    state.search = "";
    state.filter = action;
    state.page = 1;
    $("#record-search").value = "";
    renderDecisions();
    goTo("decisions");
  } else if (action === "published" && state.publishedApplications) {
    enterPublishedApplications();
  } else if (action === "evaluate" && state.canEvaluate) {
    enterEvaluation();
  } else if (action === "run") {
    runBackend();
  } else if (action === "setup") {
    goTo("pipeline");
    $("#run-path").open = true;
    $("#run-path").scrollIntoView({ block: "start", behavior: "auto" });
  } else if (action === "import") {
    $("#report-input").click();
  }
}

function renderBackendState() {
  const statuses = {
    checking: ["Checking", "Checking the local backend connection."],
    unavailable: ["Offline", "Local backend unavailable; report import still works."],
    unconfigured: ["Connected", "Local backend connected; no scenario batch is configured."],
    audited_report: ["Connected", "Local backend connected; an audited report is configured."],
    scenario_batch: ["Connected", "Local backend connected; scenario sources are configured."],
    published_catalogue: ["Connected", "Local backend connected; published supplier applications are available."],
    interactive_scenario: ["Connected", "Local backend connected; food and material references are configured for a single scenario."],
    report_error: ["Report error", "The local backend is connected, but its configured report could not be loaded."],
  };
  const [label, detail] = statuses[state.backendMode] || statuses.unavailable;
  $("#backend-indicator-text").textContent = state.backendBusy ? "Running" : label;
  $("#backend-indicator").dataset.state = state.backendBusy ? "running" : state.backendMode;
  $("#backend-indicator").title = state.backendBusy ? "Running the configured scenario batch." : detail;
  $("#backend-indicator").setAttribute("aria-label", state.backendBusy ? "Backend running a scenario batch" : `Backend ${label.toLowerCase()}: ${detail}`);
  const runButton = $("#run-backend");
  runButton.hidden = state.backendMode !== "scenario_batch";
  runButton.disabled = state.backendBusy;
  runButton.textContent = state.backendBusy ? "Running…" : "Run batch";
  const setupRunButton = $("#setup-run-batch");
  setupRunButton.hidden = state.backendMode !== "scenario_batch";
  setupRunButton.disabled = state.backendBusy;
  setupRunButton.textContent = state.backendBusy ? "Running…" : "Run configured batch";
  $("#setup-open-results").hidden = !state.report;
  $("#nav-evaluate").hidden = !state.canEvaluate;
  $("#start-evaluation").hidden = !state.canEvaluate;
  $(".welcome-enter").classList.toggle("button-light", !state.canEvaluate);
  $(".welcome-enter").classList.toggle("button-secondary", state.canEvaluate);
  $("#hero-tour-hint").textContent = state.canEvaluate
    ? "Or explore the method through a short, interactive tour."
    : "Start with a short, interactive tour of the decision path.";
  $("#run-path-form-note").hidden = !state.canEvaluate;
  $("#studio-form-button").hidden = !state.canEvaluate;
  $("#studio-setup-button").hidden = state.canEvaluate;
  $("#studio-finish-copy").textContent = state.canEvaluate
    ? "Select a sourced food and enter your conditions in the form. The walkthrough did not invent a package result."
    : "Prepare one genuine scenario batch, run the backend, then inspect its reported status and sources. The walkthrough did not invent a package result.";
  renderReviewItems();
}

function acceptReport(report, label, destination, origin = "local", submittedFoodProfile = null) {
  state.report = report;
  state.fileName = label;
  state.reportOrigin = origin;
  state.submittedFoodProfile = submittedFoodProfile;
  state.search = "";
  state.filter = "all";
  state.page = 1;
  state.selectedIndex = 0;
  state.pipelineRowIndex = 0;
  state.pipelineStep = 0;
  state.pipelineOptionsFor = null;
  $("#browse-real-applications").hidden = true;
  if (destination === "pipeline") state.pipelineMode = "actual";
  $("#record-search").value = "";
  goTo(destination);
  render();
  renderBackendState();
  notify(`${report.rows.length.toLocaleString()} decision ${report.rows.length === 1 ? "row" : "rows"} ready.`);
}

async function loadFile(file) {
  if (!file) return;
  const returnToTrace = state.view === "pipeline" && state.pipelineMode === "actual";
  if (file.size > MAX_FILE_BYTES) {
    notify("This report is over 100 MB. Export a smaller batch before importing.", true);
    return;
  }
  try {
    const report = parseDecisionReport(await file.text());
    acceptReport(report, file.name, returnToTrace ? "pipeline" : "decisions");
  } catch (error) {
    notify(error instanceof Error ? error.message : "Could not read the report.", true);
  }
}

async function responseError(response) {
  try {
    const payload = await response.json();
    return typeof payload.error === "string" ? payload.error : `Backend returned ${response.status}.`;
  } catch {
    return `Backend returned ${response.status}.`;
  }
}

async function connectBackend() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Local backend is unavailable.");
    const status = await response.json();
    if (!["unconfigured", "audited_report", "scenario_batch", "published_catalogue", "interactive_scenario"].includes(status.mode) || status.model_deployed !== false) {
      throw new Error("Local backend state is unsupported.");
    }
    state.backendMode = status.mode;
    state.canEvaluate = status.can_evaluate === true;
    renderBackendState();
    if (status.has_public_applications === true) {
      try {
        const catalogueResponse = await fetch("/api/published-applications", { cache: "no-store" });
        if (!catalogueResponse.ok) throw new Error(await responseError(catalogueResponse));
        state.publishedApplications = validatePublishedApplications(await catalogueResponse.json());
        $("#browse-real-applications").hidden = state.canEvaluate;
        $("#hero-tour-hint").hidden = !state.canEvaluate;
        renderOverview();
        renderReviewItems();
      } catch (error) {
        notify(error instanceof Error ? error.message : "Could not load published applications.", true);
      }
    }
    if (status.has_report && status.mode === "audited_report") {
      try {
        const reportResponse = await fetch("/api/report", { cache: "no-store" });
        if (!reportResponse.ok) throw new Error(await responseError(reportResponse));
        acceptReport(parseDecisionReport(await reportResponse.text()), "Connected backend report", "overview", "backend");
      } catch (error) {
        state.backendMode = "report_error";
        renderBackendState();
        notify(error instanceof Error ? error.message : "Could not load the configured report.", true);
      }
    }
  } catch (error) {
    state.backendMode = "unavailable";
    state.canEvaluate = false;
    renderBackendState();
    if (error.message !== "Local backend is unavailable.") notify(error.message, true);
  }
}

async function runBackend() {
  if (state.backendMode !== "scenario_batch" || state.backendBusy) return;
  state.backendBusy = true;
  renderBackendState();
  try {
    const response = await fetch("/api/run", { method: "POST", cache: "no-store" });
    if (!response.ok) throw new Error(await responseError(response));
    acceptReport(parseDecisionReport(await response.text()), "Current backend run", "pipeline", "backend");
  } catch (error) {
    notify(error instanceof Error ? error.message : "The backend run failed.", true);
  } finally {
    state.backendBusy = false;
    renderBackendState();
  }
}

async function copyText(value, successMessage) {
  try {
    await navigator.clipboard.writeText(value);
    notify(successMessage);
  } catch {
    notify("Copy is unavailable in this browser. Select and copy the text manually.", true);
  }
}

document.addEventListener("click", (event) => {
  if (!event.target.closest("#review-menu")) setReviewOpen(false);
  const target = event.target.closest("button");
  if (!target) return;
  if (target.matches("#review-toggle")) setReviewOpen($("#review-panel").hidden);
  else if (target.matches("[data-review-action]")) followReviewAction(target.dataset.reviewAction);
  else if (target.matches("[data-enter-app]")) enterWorkspace();
  else if (target.matches("[data-enter-evaluate]")) enterEvaluation();
  else if (target.matches("[data-enter-published]")) enterPublishedApplications();
  else if (target.matches("[data-food-id]")) {
    const food = state.foodSearchResults.find((item) => item.food_reference_id === target.dataset.foodId);
    if (!food) return;
    state.selectedFood = food;
    $("#food-search").value = food.commodity_type;
    $("#food-search-results").innerHTML = "";
    $("#food-search-status").textContent = food.form_ready
      ? "Reference selected. Enter the conditions for your product below."
      : "This reference is incomplete. Choose a food with all basic properties.";
    renderSelectedFood();
  }
  else if (target.matches("[data-clear-food]")) {
    state.selectedFood = null;
    $("#food-search").value = "";
    $("#food-search-status").textContent = "Enter at least two characters to search the configured food reference.";
    renderFoodSearch();
    $("#food-search").focus();
  }
  else if (target.matches("[data-enter-stage]")) enterWorkspace(Number(target.dataset.enterStage), false);
  else if (target.matches("[data-welcome]")) returnToWelcome();
  else if (target.matches("[data-nav]")) goTo(target.dataset.nav);
  else if (target.matches("[data-go]")) goTo(target.dataset.go);
  else if (target.matches("[data-import]")) $("#report-input").click();
  else if (target.matches("[data-run-backend]")) runBackend();
  else if (target.matches("[data-compare-index]")) {
    const index = Number(target.dataset.compareIndex);
    if (!Number.isInteger(index) || index < 0 || index >= (state.publishedApplications?.applications.length ?? 0)) return;
    const selected = state.publishedCompareIndices;
    if (selected.includes(index)) state.publishedCompareIndices = selected.filter((value) => value !== index);
    else if (selected.length < 2) state.publishedCompareIndices = [...selected, index];
    else { notify("Compare two source uses at a time. Remove one to choose another."); return; }
    renderPublishedApplications();
    $(`[data-compare-index="${index}"]`)?.focus();
  }
  else if (target.matches("[data-clear-comparison]")) {
    state.publishedCompareIndices = [];
    renderPublishedApplications();
    $("#published-search").focus();
  }
  else if (target.matches("[data-show-setup]")) {
    stopPlayback();
    $("#run-path").open = true;
    $("#run-path").scrollIntoView({ block: "start", behavior: "auto" });
  }
  else if (target.matches("[data-copy-setup]")) {
    copyText($("#startup-command").textContent.trim(), "Command copied. Replace the example paths before running it.");
  }
  else if (target.matches("[data-filter]")) {
    state.filter = target.dataset.filter;
    state.page = 1;
    renderDecisions();
  }
  else if (target.matches("#theme-toggle")) {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  } else if (target.matches("[data-pipeline-mode]")) {
    stopPlayback();
    state.pipelineMode = target.dataset.pipelineMode;
    state.pipelineStep = 0;
    renderPipeline();
  } else if (target.matches("[data-route]")) {
    stopPlayback();
    state.pipelineRoute = target.dataset.route;
    renderPipeline();
  } else if (target.matches("[data-pipeline-index]")) {
    stopPlayback();
    state.pipelineStep = Number(target.dataset.pipelineIndex);
    renderPipeline();
  } else if (target.matches("[data-pipeline-step]")) {
    stopPlayback();
    state.pipelineStep += target.dataset.pipelineStep === "next" ? 1 : -1;
    state.pipelineStep = Math.max(0, Math.min(STAGES.length - 1, state.pipelineStep));
    renderPipeline();
  } else if (target.matches("#pipeline-play")) {
    if (playbackTimer !== null) stopPlayback();
    else startPlayback();
  } else if (target.matches("[data-trace-row]")) {
    stopPlayback();
    state.pipelineRowIndex = Number(target.dataset.traceRow);
    state.pipelineMode = "actual";
    state.pipelineStep = 0;
    goTo("pipeline");
    renderPipeline();
  } else if (target.matches("[data-select-row]")) {
    state.selectedIndex = Number(target.dataset.selectRow);
    state.pipelineRowIndex = state.selectedIndex;
    state.page = Math.floor(filteredRows().findIndex(({ index }) => index === state.selectedIndex) / PAGE_SIZE) + 1;
    renderDecisions();
    goTo("decisions");
  } else if (target.matches("[data-page]")) {
    state.page += target.dataset.page === "next" ? 1 : -1;
    renderDecisions();
  } else if (target.matches("[data-copy-hash]")) {
    copyText(target.dataset.copyHash, "Source fingerprint copied.");
  }
});

$("#record-search").addEventListener("input", (event) => {
  state.search = event.target.value;
  state.page = 1;
  renderDecisions();
});
$("#published-search").addEventListener("input", (event) => {
  state.publishedSearch = event.target.value;
  if (state.publishedApplications && !state.report) renderPublishedApplications();
});
$("#food-search").addEventListener("input", (event) => {
  clearTimeout(foodSearchTimer);
  if (foodSearchAbort) foodSearchAbort.abort();
  state.selectedFood = null;
  state.foodSearchResults = [];
  state.foodMasterSha256 = null;
  renderFoodSearch();
  const query = event.target.value.trim();
  if (query.length < 2) {
    $("#food-search-status").textContent = "Enter at least two characters to search the configured food reference.";
    return;
  }
  foodSearchTimer = setTimeout(() => searchFoods(query), 250);
});
$("#scenario-form").addEventListener("submit", submitEvaluation);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#review-panel").hidden) {
    setReviewOpen(false);
    $("#review-toggle").focus();
  }
});
$("#report-input").addEventListener("change", (event) => {
  loadFile(event.target.files?.[0]);
  event.target.value = "";
});
$("#pipeline-record-select").addEventListener("change", (event) => {
  stopPlayback();
  state.pipelineRowIndex = Number(event.target.value);
  state.pipelineStep = 0;
  renderPipeline();
});
document.addEventListener("dragover", (event) => {
  if ([...(event.dataTransfer?.types ?? [])].includes("Files")) event.preventDefault();
});
document.addEventListener("drop", (event) => {
  if ([...(event.dataTransfer?.types ?? [])].includes("Files")) {
    event.preventDefault();
    loadFile(event.dataTransfer.files?.[0]);
  }
});

let storedTheme = "dark";
try { storedTheme = localStorage.getItem("packsense-theme") || "dark"; } catch { /* Private mode may block storage. */ }
setTheme(storedTheme);
render();
renderBackendState();
connectBackend();
