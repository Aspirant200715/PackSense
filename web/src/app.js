import { parseDecisionReport, readableCode, summarizeReport } from "./report.js";
import { actualPipeline, STAGES, walkthroughStage } from "./pipeline.js";

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

function closeMobileMenu() {
  $("#sidebar").classList.remove("is-open");
  $("#sidebar-scrim").hidden = true;
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  $("#menu-toggle").setAttribute("aria-label", "Open navigation");
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

function stopPlayback() {
  if (playbackTimer !== null) clearInterval(playbackTimer);
  playbackTimer = null;
  $("#pipeline-play").textContent = "Play walkthrough";
  $("#pipeline-play").setAttribute("aria-label", "Play walkthrough");
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
  $("#breadcrumb-current").textContent = {
    overview: "Overview", decisions: "Decision records", pipeline: "Pipeline", evidence: "Evidence & sources",
  }[view];
  closeMobileMenu();
  window.scrollTo(0, 0);
}

function emptyRecords() {
  return `<div class="records-empty" data-drop-zone><div class="records-empty-icon" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none"><rect x="10" y="7" width="28" height="34" rx="2"/><path d="M17 17h14M17 24h14M17 31h8"/></svg></div><strong>No report loaded</strong><p>Bring in a generated decision report to see your scenarios here.</p><button type="button" class="button button-secondary button-small" data-import>Choose JSON file</button></div>`;
}

function renderOverview() {
  const counts = state.report ? summarizeReport(state.report) : null;
  $("#metric-total").textContent = counts ? counts.total.toLocaleString() : "—";
  $("#metric-not-ready").textContent = counts ? counts.not_ready.toLocaleString() : "—";
  $("#metric-shortlist").textContent = counts ? counts.preliminary_shortlist.toLocaleString() : "—";
  $("#metric-exception").textContent = counts ? counts.exception.toLocaleString() : "—";
  const root = $("#overview-records");
  if (!state.report) {
    root.innerHTML = emptyRecords();
    return;
  }
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
  return `<section class="inspector-section"><div class="inspector-section-title"><h3>${escapeHtml(title)}</h3><span>${items.length}</span></div><div class="reason-stack">${items.map((item) => {
    const isIssue = typeof item === "object" && item !== null;
    const code = isIssue ? item.code : item;
    const field = isIssue ? item.field : null;
    const message = isIssue ? item.message : null;
    return `<div class="reason-card reason-${kind}"><span class="reason-mark" aria-hidden="true"></span><div><strong>${escapeHtml(field ? `${field}: ${readableCode(code)}` : readableCode(code))}</strong>${message ? `<p>${escapeHtml(message)}</p>` : ""}<code>${escapeHtml(code ?? "unknown")}</code></div></div>`;
  }).join("")}</div></section>`;
}

function renderExposures(exposures) {
  if (!exposures.length) return "";
  return `<section class="inspector-section"><div class="inspector-section-title"><h3>Temperature exposure</h3><span>${exposures.length} phases</span></div><div class="exposure-list">${exposures.map((item) => `
    <div class="exposure-row"><div><strong>${escapeHtml(readableCode(item.phase))}</strong>${item.safety_check_only ? `<small>Safety excursion check</small>` : item.duration_hours != null ? `<small>${formatNumber(item.duration_hours, " h")} duration</small>` : `<small>Duration not specified</small>`}</div><div class="exposure-values"><strong>${formatNumber(item.temperature_c, " °C")}</strong><small>RH ${formatNumber(item.relative_humidity_pct, "%")}</small></div></div>`).join("")}</div></section>`;
}

function renderCandidates(row) {
  if (!row.screened_candidates.length) return `<section class="inspector-section"><div class="inspector-section-title"><h3>Package structures</h3></div><div class="quiet-empty">No complete structure is available for this row in the current report.</div></section>`;
  return `<section class="inspector-section"><div class="inspector-section-title"><h3>Screened structures</h3><span>${row.screened_candidates.length}</span></div><div class="candidate-list">${row.screened_candidates.map((candidate) => `
    <details class="candidate-card"><summary><span class="candidate-main"><strong>${escapeHtml(candidate.structure_id)}</strong><small>${displayValue(candidate.pack_format, "Format not reported")}</small></span>${statusBadge(candidate.status)}<span class="candidate-expand" aria-hidden="true">+</span></summary><div class="candidate-body"><div class="candidate-facts"><div><span>PROTECTION RANK</span><strong>${candidate.protection_rank == null ? "Not ranked" : escapeHtml(candidate.protection_rank)}</strong></div><div><span>SERVICE RANGE</span><strong>${formatNumber(candidate.service_temperature_min_c, " °C")} to ${formatNumber(candidate.service_temperature_max_c, " °C")}</strong></div></div><div class="candidate-subhead">Layer structure</div>${candidate.layers.length ? `<div class="layer-list">${candidate.layers.map((layer, index) => `<div class="layer-row"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(layer.grade_id ?? "Unspecified grade")}</strong><small>${formatNumber(layer.thickness_um, " µm")}${layer.role ? ` · ${escapeHtml(layer.role)}` : ""}${layer.is_food_contact ? " · food contact" : ""}</small></div>`).join("")}</div>` : `<p class="candidate-empty">Layer details not supplied.</p>`}${candidate.reason_codes.length ? `<div class="candidate-subhead">Screening reasons</div><div class="candidate-reasons">${candidate.reason_codes.map((reason) => `<span>${escapeHtml(readableCode(reason))}</span>`).join("")}</div>` : ""}</div></details>`).join("")}</div></section>`;
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

  const actualStages = actualMode && hasReport
    ? actualPipeline(state.report.rows[state.pipelineRowIndex])
    : null;
  $("#pipeline-stage-list").innerHTML = STAGES.map((stage, index) => {
    const active = index === state.pipelineStep;
    const status = actualStages ? actualStages[index].state : actualMode ? "awaiting_report" : active ? "in_focus" : index < state.pipelineStep ? "viewed" : "upcoming";
    const statusText = actualMode ? (hasReport ? readableCode(status) : "Awaiting report") : active ? "In focus" : index < state.pipelineStep ? "Explored" : "Up next";
    return `<button type="button" class="studio-stage${active ? " is-active" : ""}" data-pipeline-index="${index}" ${actualMode && !hasReport ? "disabled" : ""} ${active ? 'aria-current="step"' : ""}><span class="stage-index">${stage.number}</span><span class="stage-text"><strong>${escapeHtml(stage.title)}</strong><small>${escapeHtml(statusText)}</small></span><span class="stage-light stage-${escapeHtml(status)}" aria-hidden="true"></span></button>`;
  }).join("");

  if (actualMode && !hasReport) return;
  const stage = actualStages
    ? { ...STAGES[state.pipelineStep], ...actualStages[state.pipelineStep] }
    : walkthroughStage(state.pipelineStep, state.pipelineRoute);
  $("#studio-mode-label").textContent = actualMode ? "ACTUAL REPORT TRACE" : "CONCEPTUAL WALKTHROUGH";
  $("#studio-progress").textContent = `${stage.number} / 08`;
  $("#studio-step-number").textContent = stage.number;
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
  $("#pipeline-play").hidden = actualMode;
}

function render() {
  renderOverview();
  renderDecisions();
  renderEvidence();
  renderPipeline();
}

async function loadFile(file) {
  if (!file) return;
  if (file.size > MAX_FILE_BYTES) {
    notify("This report is over 100 MB. Export a smaller batch before importing.", true);
    return;
  }
  try {
    const report = parseDecisionReport(await file.text());
    state.report = report;
    state.fileName = file.name;
    state.search = "";
    state.filter = "all";
    state.page = 1;
    state.selectedIndex = 0;
    state.pipelineRowIndex = 0;
    state.pipelineOptionsFor = null;
    $("#record-search").value = "";
    $("#record-filter").value = "all";
    render();
    goTo("decisions");
    notify(`${report.rows.length.toLocaleString()} decision rows loaded locally.`);
  } catch (error) {
    notify(error instanceof Error ? error.message : "Could not read the report.", true);
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
  if (target.matches("[data-nav]")) goTo(target.dataset.nav);
  else if (target.matches("[data-go]")) goTo(target.dataset.go);
  else if (target.matches("[data-import]")) $("#report-input").click();
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
    if (playbackTimer !== null) {
      stopPlayback();
    } else {
      if (state.pipelineStep === STAGES.length - 1) state.pipelineStep = 0;
      target.textContent = "Pause walkthrough";
      target.setAttribute("aria-label", "Pause walkthrough");
      renderPipeline();
      playbackTimer = setInterval(() => {
        if (state.pipelineStep >= STAGES.length - 1) {
          stopPlayback();
          return;
        }
        state.pipelineStep += 1;
        renderPipeline();
      }, 2400);
    }
  } else if (target.matches("[data-trace-row]")) {
    stopPlayback();
    state.pipelineRowIndex = Number(target.dataset.traceRow);
    state.pipelineMode = "actual";
    state.pipelineStep = 0;
    renderPipeline();
    goTo("pipeline");
  } else if (target.matches("[data-select-row]")) {
    state.selectedIndex = Number(target.dataset.selectRow);
    state.pipelineRowIndex = state.selectedIndex;
    state.page = Math.floor(filteredRows().findIndex(({ index }) => index === state.selectedIndex) / PAGE_SIZE) + 1;
    renderDecisions();
    goTo("decisions");
  } else if (target.matches("[data-page]")) {
    state.page += target.dataset.page === "next" ? 1 : -1;
    renderDecisions();
  } else if (target.matches("[data-copy-command]")) {
    copyText($("#projection-command").textContent, "Command copied.");
  } else if (target.matches("[data-copy-hash]")) {
    copyText(target.dataset.copyHash, "Source fingerprint copied.");
  }
});

$("#record-search").addEventListener("input", (event) => {
  state.search = event.target.value;
  state.page = 1;
  renderDecisions();
});
$("#record-filter").addEventListener("change", (event) => {
  state.filter = event.target.value;
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
$("#menu-toggle").addEventListener("click", () => {
  const opened = $("#sidebar").classList.toggle("is-open");
  $("#sidebar-scrim").hidden = !opened;
  $("#menu-toggle").setAttribute("aria-expanded", String(opened));
  $("#menu-toggle").setAttribute("aria-label", opened ? "Close navigation" : "Open navigation");
});
$("#sidebar-scrim").addEventListener("click", closeMobileMenu);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMobileMenu(); });
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
