import { summarizeReport } from "./report.js";

/** Review items describe current, observed workspace state; they are not an activity feed. */
export function deriveReviewItems({ backendMode, backendBusy, report, publishedApplications }) {
  if (report) {
    const counts = summarizeReport(report);
    const items = [];
    if (counts.exception) items.push({
      id: "exceptions", tone: "red", action: "exception",
      title: `${counts.exception.toLocaleString()} input ${counts.exception === 1 ? "exception" : "exceptions"}`,
      detail: "Correct or match these scenarios before screening.",
    });
    if (counts.not_ready) items.push({
      id: "evidence", tone: "amber", action: "not_ready",
      title: `${counts.not_ready.toLocaleString()} ${counts.not_ready === 1 ? "row needs" : "rows need"} evidence`,
      detail: "The food scenario is understood, but package checks cannot finish.",
    });
    if (counts.preliminary_shortlist) items.push({
      id: "preliminary", tone: "blue", action: "preliminary_shortlist",
      title: `${counts.preliminary_shortlist.toLocaleString()} preliminary ${counts.preliminary_shortlist === 1 ? "shortlist" : "shortlists"}`,
      detail: "Review screened structures and their unresolved approval boundary.",
    });
    return items;
  }
  if (backendMode === "interactive_scenario") return [{
    id: "evaluate", tone: "blue", action: "evaluate",
    title: "Food scenario form ready",
    detail: "Choose a sourced food and enter this product's actual storage and transport conditions.",
  }];
  if (publishedApplications?.applications.length) return [{
    id: "published", tone: "blue", action: "published",
    title: `${publishedApplications.applications.length.toLocaleString()} published package ${publishedApplications.applications.length === 1 ? "use" : "uses"}`,
    detail: "Supplier-listed conditions are available to inspect; rights review is pending.",
  }];
  if (backendMode === "scenario_batch") return [{
    id: "batch", tone: "blue", action: "run",
    title: backendBusy ? "Scenario batch running" : "Scenario batch configured",
    detail: backendBusy ? "The backend is processing the configured source files." : "Run the configured sources to generate decision records.",
  }];
  if (backendMode === "unconfigured") return [{
    id: "setup", tone: "neutral", action: "setup",
    title: "Add a real scenario batch",
    detail: "Connect the scenario and reference files when starting the local backend.",
  }];
  if (backendMode === "unavailable") return [{
    id: "offline", tone: "red", action: "import",
    title: "Local backend unavailable",
    detail: "You can still open an existing decision report in this browser.",
  }];
  if (backendMode === "report_error") return [{
    id: "report_error", tone: "red", action: "import",
    title: "Configured report could not load",
    detail: "Open a valid decision report or check the backend source file.",
  }];
  return [];
}
