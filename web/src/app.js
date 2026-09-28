import { parseDecisionReport, readableCode, summarizeReport } from "./report.js";
import { actualContext, actualPipeline, STAGES, walkthroughStage } from "./pipeline.js";

const VIEWS = new Set(["overview", "decisions", "pipeline", "evidence"]);
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
  $(".pipeline-studio").classList.toggle("is-playing", playing);
  $("#guide-play-label").textContent = playing ? "Pause tour" : state.pipelineStep === STAGES.length - 1 ? "Replay tour" : "Play guided tour";
  $("#guide-play-icon").textContent = playing ? "Ⅱ" : "▶";
  $("#pipeline-play").setAttribute("aria-label", playing ? "Pause guided tour" : state.pipelineStep === STAGES.length - 1 ? "Replay guided tour" : "Play guided tour");
  $("#pipeline-play").setAttribute("aria-pressed", String(playing));
  $("#guide-playback-status").textContent = playing
    ? "Playing automatically · select any stage or pause to inspect it."
    : state.pipelineStep === STAGES.length - 1 ? "Tour complete · replay or explore any stage."
      : "Press Play to watch the stages advance automatically.";
}

function stopPlayback() {
  if (playbackTimer !== null) clearInterval(playbackTimer);
  playbackTimer = null;
  updatePlaybackControls();
}

function startPlayback() {
  if (state.pipelineMode !== "walkthrough" || playbackTimer !== null) return;
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

function centerActiveStage() {
  const stageList = $("#pipeline-stage-list");
  const activeStage = stageList.querySelector(".is-active");
  if (!activeStage || stageList.scrollWidth <= stageList.clientWidth) return;
  const listBounds = stageList.getBoundingClientRect();
  const stageBounds = activeStage.getBoundingClientRect();
  stageList.scrollLeft += stageBounds.left - listBounds.left - (stageList.clientWidth - stageBounds.width) / 2;
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
  if (view === "pipeline") centerActiveStage();
  window.scrollTo(0, 0);
}

function renderOverview() {
  $("#overview-results").hidden = !state.report;
  $("#overview-empty").hidden = Boolean(state.report);
  $("#backend-banner").hidden = !state.report;
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

function renderInspector(row) {
  const root = $("#record-inspector");
  if (!row) {
    root.innerHTML = `<div class="inspector-placeholder"><strong>Select a scenario</strong><p>Choose a row to inspect its evidence, temperature exposure and package screen.</p></div>`;
    return;
  }
  const preferred = row.preliminary_preferred_structure_id;
  root.innerHTML = `<div class="inspector-header"><div class="section-kicker">SOURCE ROW ${row.source_row_number}</div><h2>${escapeHtml(row.scenario?.commodity_type || row.record_id || `Row ${row.source_row_number}`)}</h2>${row.scenario ? `<div class="inspector-record-id">Record ${escapeHtml(row.record_id)}</div>` : ""}${statusBadge(row.status)}<p>${row.status === "exception" ? "This scenario needs an input correction before screening." : row.status === "not_ready" ? "The scenario is understood, but the evidence is not sufficient for a package result." : "These structures passed a narrow protection screen. This is not a released recommendation."}</p></div>
    <div class="inspector-facts"><div><span>FOOD REFERENCE</span><strong>${displayValue(row.food_reference_id, "Not matched")}</strong></div><div><span>REQUESTED LIFE</span><strong>${row.target_shelf_life_days == null ? "Not available" : formatNumber(row.target_shelf_life_days, " days")}</strong></div></div>
    ${row.scenario ? `<section class="inspector-section"><div class="inspector-section-title"><h3>Submitted scenario values</h3></div><div class="scenario-facts"><div><span>MOISTURE</span><strong>${formatNumber(row.scenario.moisture_content_pct, "%")}</strong></div><div><span>OIL / FAT</span><strong>${formatNumber(row.scenario.oil_fat_content_pct, "%")}</strong></div><div><span>pH</span><strong>${formatNumber(row.scenario.pH)}</strong></div><div><span>NET PACK</span><strong>${formatNumber(row.scenario.net_pack_quantity, ` ${escapeHtml(row.scenario.net_pack_quantity_unit ?? "")}`)}</strong></div><div><span>STORAGE</span><strong>${escapeHtml(readableCode(row.scenario.storage_type))}</strong></div><div><span>TRANSPORT</span><strong>${escapeHtml(readableCode(row.scenario.transport_mode))}</strong></div><div><span>HANDLING</span><strong>${escapeHtml(readableCode(row.scenario.transport_handling_severity))}</strong></div></div>${row.scenario.respiration_rate != null ? `<div class="respiration-note">Respiration: ${formatNumber(row.scenario.respiration_rate)} ${displayValue(row.scenario.respiration_rate_unit, "")} at ${formatNumber(row.scenario.respiration_reference_temperature_c, " °C")}</div>` : ""}</section>` : ""}
    ${preferred ? `<div class="preliminary-callout"><span>PRELIMINARY PROTECTION PREFERENCE</span><strong>${escapeHtml(preferred)}</strong><p>Not a validated material prediction or package approval.</p></div>` : ""}
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
  $("#pipeline-heading-step").textContent = STAGES[state.pipelineStep].number;
  $("#pipeline-guide-bar").hidden = actualMode;
  $("#guide-stage-caption").textContent = `Step ${state.pipelineStep + 1} of ${STAGES.length} · ${STAGES[state.pipelineStep].title}`;
  $("#guide-progress").setAttribute("aria-valuenow", String(state.pipelineStep + 1));
  $("#guide-progress-fill").style.width = `${((state.pipelineStep + 1) / STAGES.length) * 100}%`;
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
  $("#studio-focus").hidden = actualMode && !hasReport;

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
  stageList.innerHTML = STAGES.map((stage, index) => {
    const active = index === state.pipelineStep;
    const status = actualStages ? actualStages[index].state : actualMode ? "awaiting_report" : active ? "in_focus" : index < state.pipelineStep ? "viewed" : "upcoming";
    const statusText = actualMode ? (hasReport ? readableCode(status) : "Awaiting report") : active ? "In focus" : index < state.pipelineStep ? "Explored" : "Up next";
    return `<button type="button" class="studio-stage${active ? " is-active" : ""}" data-pipeline-index="${index}" ${actualMode && !hasReport ? "disabled" : ""} ${active ? 'aria-current="step"' : ""}><span class="stage-index">${stage.number}</span><span class="stage-text"><strong>${escapeHtml(stage.title)}</strong><small>${escapeHtml(statusText)}</small></span><span class="stage-light stage-${escapeHtml(status)}" aria-hidden="true"></span></button>`;
  }).join("");
  centerActiveStage();

  if (actualMode && !hasReport) return;
  const stage = actualStages
    ? { ...STAGES[state.pipelineStep], ...actualStages[state.pipelineStep] }
    : walkthroughStage(state.pipelineStep, state.pipelineRoute);
  $("#studio-mode-label").textContent = actualMode ? "ACTUAL REPORT TRACE" : "CONCEPTUAL WALKTHROUGH";
  $("#studio-progress").textContent = `${stage.number} / 08`;
  $("#studio-state-label").textContent = actualMode ? readableCode(stage.state).toUpperCase() : "STEP IN FOCUS";
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
  $("#studio-step-caption").textContent = `Step ${state.pipelineStep + 1} of 8`;
  $("#pipeline-previous").disabled = state.pipelineStep === 0;
  $("#pipeline-next").disabled = state.pipelineStep === STAGES.length - 1;
}

function render() {
  renderOverview();
  renderDecisions();
  renderEvidence();
  renderPipeline();
}

function renderBackendState() {
  const messages = {
    checking: ["Checking backend", "Connecting to the local decision pipeline.", "Checking"],
    unavailable: ["Open a decision report", "The local backend is not running. You can still inspect a PackSense report here.", "Report mode"],
    unconfigured: ["Backend online; add source files", "Configure a scenario batch and reference masters when starting the local backend, or open an existing report.", "Backend online"],
    audited_report: ["Audited report connected", "This report is projected directly from the local Python backend. Explore its records and source trace.", "Report connected"],
    scenario_batch: ["Source files connected", "Run the configured scenario batch through the real ingestion, requirement and package-screening steps.", "Backend ready"],
  };
  const [title, detail, indicator] = messages[state.backendMode] || messages.unavailable;
  const localReport = state.report && state.reportOrigin === "local";
  const shownTitle = state.backendBusy ? "Running evidence checks" : localReport ? "Local decision report open" : title;
  const shownDetail = state.backendBusy
    ? "The Python backend is processing the configured source files. This may take a moment."
    : localReport ? "Explore the report's recorded conditions, screening status and source trace." : detail;
  $("#backend-banner-title").textContent = shownTitle;
  $("#backend-banner-detail").textContent = shownDetail;
  $("#overview-backend-title").textContent = shownTitle;
  $("#overview-backend-detail").textContent = shownDetail;
  $("#overview-empty-status").dataset.state = state.backendBusy ? "running" : state.backendMode;
  $("#backend-indicator-text").textContent = state.backendBusy ? "Backend running" : indicator;
  $("#backend-indicator").dataset.state = state.backendBusy ? "running" : state.backendMode;
  $("#backend-indicator").title = state.backendBusy ? "Backend running" : indicator;
  $$('[data-run-backend]').forEach((button) => {
    button.hidden = state.backendMode !== "scenario_batch";
    button.disabled = state.backendBusy;
    button.textContent = state.backendBusy ? "Running…" : ["banner-run-backend", "overview-run-backend"].includes(button.id) ? "Run configured batch →" : "Run batch";
  });
}

function acceptReport(report, label, destination, origin = "local") {
  state.report = report;
  state.fileName = label;
  state.reportOrigin = origin;
  state.search = "";
  state.filter = "all";
  state.page = 1;
  state.selectedIndex = 0;
  state.pipelineRowIndex = 0;
  state.pipelineOptionsFor = null;
  if (destination === "pipeline") state.pipelineMode = "actual";
  $("#record-search").value = "";
  goTo(destination);
  render();
  renderBackendState();
  notify(`${report.rows.length.toLocaleString()} decision rows ready.`);
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
    if (!["unconfigured", "audited_report", "scenario_batch"].includes(status.mode) || status.model_deployed !== false) {
      throw new Error("Local backend state is unsupported.");
    }
    state.backendMode = status.mode;
    renderBackendState();
    if (status.has_report && status.mode === "audited_report") {
      try {
        const reportResponse = await fetch("/api/report", { cache: "no-store" });
        if (!reportResponse.ok) throw new Error(await responseError(reportResponse));
        acceptReport(parseDecisionReport(await reportResponse.text()), "Connected backend report", "overview", "backend");
      } catch (error) {
        $("#backend-banner-title").textContent = "Report could not be loaded";
        $("#backend-banner-detail").textContent = "The backend is online, but its configured report needs attention.";
        $("#overview-backend-title").textContent = "Report could not be loaded";
        $("#overview-backend-detail").textContent = "The backend is online, but its configured report needs attention.";
        notify(error instanceof Error ? error.message : "Could not load the configured report.", true);
      }
    }
  } catch (error) {
    state.backendMode = "unavailable";
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
  const target = event.target.closest("button");
  if (!target) return;
  if (target.matches("[data-enter-app]")) enterWorkspace();
  else if (target.matches("[data-enter-stage]")) enterWorkspace(Number(target.dataset.enterStage), false);
  else if (target.matches("[data-welcome]")) returnToWelcome();
  else if (target.matches("[data-nav]")) goTo(target.dataset.nav);
  else if (target.matches("[data-go]")) goTo(target.dataset.go);
  else if (target.matches("[data-import]")) $("#report-input").click();
  else if (target.matches("[data-run-backend]")) runBackend();
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
