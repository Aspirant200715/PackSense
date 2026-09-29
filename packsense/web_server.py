"""Local-only web app for the existing, evidence-gated PackSense batch flow.

An operator configures reference files at startup. The browser may submit one
bounded scenario's operating conditions, but never source paths or reference
workbooks. No trained material or shelf-life prediction is created here.
"""

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.frontend_contract import project_frontend_decisions
from packsense.ingestion import audit_scenarios
from packsense.interactive import IntakeError, scenario_row_from_submission, search_foods
from packsense.masters import load_food_references
from packsense.units import (
    SCENARIO_REFERENCE_COLUMNS, SCENARIO_REQUIRED_COLUMNS,
    SCENARIO_RESPIRATION_COLUMNS,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
MAX_REPORT_BYTES = 100 * 1024 * 1024
MAX_SCENARIO_BYTES = 8192
BACKEND_PATH_OPTIONS = (
    "route_register", "assessments", "structures", "structure_reviews",
    "transfers", "kinetics_register", "gas_observations", "water_observations",
)
BACKEND_FLAG_OPTIONS = ("produce_diagnostics", "compare_grade_references")


def scenario_template_csv() -> bytes:
    """Return the canonical header only; never invent scenario values."""
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(
        (*SCENARIO_REQUIRED_COLUMNS, *SCENARIO_RESPIRATION_COLUMNS,
         *SCENARIO_REFERENCE_COLUMNS)
    )
    return output.getvalue().encode("utf-8")


@dataclass(frozen=True)
class AppSources:
    batch_report: Path | None = None
    scenarios: Path | None = None
    food_master: Path | None = None
    material_master: Path | None = None
    food_sheet: str | None = None
    public_candidates: Path | None = None
    backend_options: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        if self.batch_report is not None:
            return "audited_report"
        if self.scenarios is not None:
            return "scenario_batch"
        if self.food_master is not None and self.material_master is not None:
            return "interactive_scenario"
        if self.public_candidates is not None:
            return "published_catalogue"
        return "unconfigured"


def _read_projected_report(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("batch report exceeds the 100 MB limit")
    with path.open("r", encoding="utf-8") as stream:
        batch = json.load(stream, parse_constant=_reject_nonfinite)
    return project_frontend_decisions(batch)


def published_applications_payload(path: Path) -> dict[str, Any]:
    """Expose exact manufacturer-listed uses, not a scenario recommendation."""
    catalogue, source_hash = load_candidate_catalogue(path)
    sources = {item["source_id"]: item for item in catalogue["sources"]}
    applications = []
    for candidate in catalogue["candidates"]:
        # An inner liner is not a complete consumer package.
        if candidate["pack_format"] == "box inner liner":
            continue
        source = sources[candidate["source_id"]]
        source_url = urlsplit(source["url"])
        if (source_url.scheme != "https" or not source_url.hostname
                or source_url.username or source_url.password):
            raise ValueError("public catalogue contains an unsafe source URL")
        for application in candidate["applications"]:
            applications.append({
                "candidate_id": candidate["candidate_id"],
                "product_code": candidate["product_code"],
                "pack_format": candidate["pack_format"],
                "food": application["commodity"],
                "quantity": application["quantity"],
                "quantity_unit": application["quantity_unit"],
                "storage_temperature_min_c": application["storage_temperature_min_c"],
                "storage_temperature_max_c": application["storage_temperature_max_c"],
                "excursion_max_c": application["excursion_max_c"],
                "excursion_max_hours": application["excursion_max_hours"],
                "source_publisher": source["publisher"],
                "source_url": source["url"],
                "source_locator": candidate["source_locator"],
                "source_rights_review_status": source["rights_review_status"],
            })
    applications.sort(key=lambda item: (item["food"].casefold(), item["product_code"]))
    return {
        "contract_version": "published-applications-v1",
        "catalogue_id": catalogue["catalogue_id"],
        "catalogue_sha256": source_hash,
        "model_prediction_available": False,
        "package_approval_available": False,
        "applications": applications,
    }


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def run_configured_batch(sources: AppSources) -> dict[str, Any]:
    """Run the established backend CLI; code and data stay out of the browser."""
    if sources.mode != "scenario_batch" or sources.food_master is None or sources.material_master is None:
        raise ValueError("scenario, food and material sources are required")
    with tempfile.TemporaryDirectory(prefix="packsense-web-") as temporary:
        report_path = Path(temporary) / "batch.json"
        command = [
            sys.executable, "-m", "packsense.recommendation_batch",
            str(sources.scenarios), "--food-master", str(sources.food_master),
            "--material-master", str(sources.material_master),
        ]
        if sources.public_candidates is not None:
            command.extend(("--public-candidates", str(sources.public_candidates)))
        command.extend((*sources.backend_options, "--report", str(report_path)))
        try:
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("backend run exceeded ten minutes") from exc
        # Exit 1 means valid output with one or more input exception rows.
        if completed.returncode not in (0, 1) or not report_path.is_file():
            detail = (completed.stderr or "backend did not produce a report").strip()
            raise ValueError(detail[:800])
        return _read_projected_report(report_path)


def run_interactive_scenario(sources: AppSources, food_audit: Any, payload: Any) -> dict[str, Any]:
    """Write one validated user scenario to a temporary CSV and reuse the batch CLI."""
    row, profile = scenario_row_from_submission(payload, food_audit)
    with tempfile.TemporaryDirectory(prefix="packsense-intake-") as temporary:
        scenario_path = Path(temporary) / "submitted-scenario.csv"
        with scenario_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=(
                *SCENARIO_REQUIRED_COLUMNS, *SCENARIO_RESPIRATION_COLUMNS,
                *SCENARIO_REFERENCE_COLUMNS,
            ))
            writer.writeheader()
            writer.writerow(row)
        audit = audit_scenarios(scenario_path)
        if len(audit.rows) != 1 or audit.rows[0].scenario is None:
            issue = audit.rows[0].issues[0] if audit.rows and audit.rows[0].issues else None
            raise IntakeError(
                issue.message if issue else "Submitted scenario did not pass input validation.",
                issue.field if issue else None,
            )
        report = run_configured_batch(replace(sources, scenarios=scenario_path))
    if report["trace"]["food_master_sha256"] != food_audit.source_sha256:
        raise IntakeError("The food reference changed during evaluation. Please retry.", "food_reference_id")
    return {
        "contract_version": "interactive-evaluation-v1",
        "input_origin": "browser_submitted",
        "food_profile": profile,
        "report": report,
    }


class PackSenseHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, sources: AppSources):
        super().__init__(("127.0.0.1", port), PackSenseHandler)
        self.sources = sources
        self.run_lock = threading.Lock()
        self.food_lock = threading.Lock()
        self.food_cache: tuple[tuple[int, int], Any] | None = None

    def food_audit(self) -> Any:
        if self.sources.food_master is None:
            raise IntakeError("A food reference master is not configured.")
        stat = self.sources.food_master.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with self.food_lock:
            if self.food_cache is None or self.food_cache[0] != signature:
                audit = load_food_references(self.sources.food_master, sheet_name=self.sources.food_sheet)
                if audit.issues:
                    raise IntakeError("The configured food reference has rejected rows; an operator must review it.")
                self.food_cache = (signature, audit)
            return self.food_cache[1]


class PackSenseHandler(SimpleHTTPRequestHandler):
    server: PackSenseHTTPServer

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _same_host(self) -> bool:
        return self.headers.get("Host") in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return origin is None or origin in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _reject_unread_post(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        """Drain a small rejected POST so closing HTTP/1.0 does not reset it."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if 0 < length <= MAX_SCENARIO_BYTES + 1:
            previous_timeout = self.connection.gettimeout()
            self.connection.settimeout(0.25)
            try:
                self.rfile.read(length)
            except (OSError, TimeoutError):
                pass
            finally:
                self.connection.settimeout(previous_timeout)
        self._json(status, payload)

    def _scenario_template(self) -> None:
        body = scenario_template_csv()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="packsense-scenarios-template.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._same_host():
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid host"})
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            mode = self.server.sources.mode
            self._json(HTTPStatus.OK, {
                "mode": mode,
                "can_run": mode == "scenario_batch",
                "can_evaluate": self.server.sources.food_master is not None and self.server.sources.material_master is not None,
                "has_report": mode == "audited_report",
                "has_public_applications": self.server.sources.public_candidates is not None,
                "model_deployed": False,
            })
        elif path == "/api/published-applications":
            catalogue = self.server.sources.public_candidates
            if catalogue is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "no public catalogue is configured"})
                return
            try:
                self._json(HTTPStatus.OK, published_applications_payload(catalogue))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800]})
        elif path == "/api/foods":
            if self.server.sources.food_master is None:
                self._json(HTTPStatus.CONFLICT, {"error": "food reference master is not configured"})
                return
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("q", [""])[0]
            try:
                self._json(HTTPStatus.OK, search_foods(self.server.food_audit(), query))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800]})
        elif path == "/api/scenario-template":
            self._scenario_template()
        elif path == "/api/report":
            if self.server.sources.mode != "audited_report":
                self._json(HTTPStatus.NOT_FOUND, {"error": "no audited report is configured"})
                return
            try:
                self._json(HTTPStatus.OK, _read_projected_report(self.server.sources.batch_report))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800]})
        elif path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if not self._same_host() or not self._same_origin():
            self._reject_unread_post(HTTPStatus.FORBIDDEN, {"error": "cross-origin requests are not allowed"})
            return
        path = urlsplit(self.path).path
        if path not in ("/api/run", "/api/evaluate"):
            self._reject_unread_post(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        if path == "/api/evaluate":
            self._evaluate_scenario()
            return
        if self.server.sources.mode != "scenario_batch":
            self._reject_unread_post(HTTPStatus.CONFLICT, {"error": "scenario sources are not configured"})
            return
        if self.headers.get("Content-Length", "0") != "0":
            self._reject_unread_post(HTTPStatus.BAD_REQUEST, {"error": "this endpoint accepts no browser-supplied data"})
            return
        if not self.server.run_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "a backend run is already in progress"})
            return
        try:
            self._json(HTTPStatus.OK, run_configured_batch(self.server.sources))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800]})
        finally:
            self.server.run_lock.release()

    def _evaluate_scenario(self) -> None:
        if self.server.sources.food_master is None or self.server.sources.material_master is None:
            self._reject_unread_post(HTTPStatus.CONFLICT, {"error": "food and material references are not configured"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if (self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json"
                or length <= 0 or length > MAX_SCENARIO_BYTES):
            self._reject_unread_post(HTTPStatus.BAD_REQUEST, {"error": "submit one JSON scenario of at most 8 KB"})
            return
        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8"),
                parse_constant=_reject_nonfinite, object_pairs_hook=_unique_json_object,
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "scenario body is not valid JSON"})
            return
        if not self.server.run_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "a backend run is already in progress"})
            return
        try:
            self._json(HTTPStatus.OK, run_interactive_scenario(
                self.server.sources, self.server.food_audit(), payload,
            ))
        except IntakeError as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800], "field": exc.field})
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)[:800]})
        finally:
            self.server.run_lock.release()


def _arguments() -> tuple[int, AppSources]:
    parser = argparse.ArgumentParser(description="Serve the PackSense MVP on localhost")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--batch-report", type=Path)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--food-master", type=Path)
    parser.add_argument("--material-master", type=Path)
    parser.add_argument("--public-candidates", type=Path)
    parser.add_argument("--scenario-sheet")
    parser.add_argument("--food-sheet")
    parser.add_argument("--material-sheet")
    parser.add_argument("--pilot-candidate-id")
    for name in BACKEND_PATH_OPTIONS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path)
    for name in BACKEND_FLAG_OPTIONS:
        parser.add_argument(f"--{name.replace('_', '-')}", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if (args.food_master is None) != (args.material_master is None):
        parser.error("--food-master and --material-master are required together")
    if args.scenarios is not None and args.food_master is None:
        parser.error("--scenarios requires --food-master and --material-master")
    if args.batch_report is not None and any((args.scenarios, args.food_master, args.material_master)):
        parser.error("--batch-report cannot be combined with scenario sources")
    if args.scenario_sheet is not None and args.scenarios is None:
        parser.error("--scenario-sheet requires --scenarios")
    for name in ("batch_report", "scenarios", "food_master", "material_master",
                 "public_candidates", *BACKEND_PATH_OPTIONS):
        path = getattr(args, name)
        if path is not None:
            if not path.is_file():
                parser.error(f"source file does not exist: {path}")
            # The subprocess runs from the repository root, not the launch
            # directory. Freeze every operator path before changing cwd.
            setattr(args, name, path.resolve())
    options: list[str] = []
    for name in (*BACKEND_PATH_OPTIONS, "scenario_sheet", "food_sheet", "material_sheet", "pilot_candidate_id"):
        value = getattr(args, name)
        if value is not None:
            options.extend((f"--{name.replace('_', '-')}", str(value)))
    for name in BACKEND_FLAG_OPTIONS:
        if getattr(args, name):
            options.append(f"--{name.replace('_', '-')}")
    if options and args.food_master is None:
        parser.error("backend options require food and material references")
    return args.port, AppSources(
        batch_report=args.batch_report, scenarios=args.scenarios,
        food_master=args.food_master, material_master=args.material_master,
        food_sheet=args.food_sheet,
        public_candidates=args.public_candidates,
        backend_options=tuple(options),
    )


def main() -> None:
    port, sources = _arguments()
    server = PackSenseHTTPServer(port, sources)
    print(f"PackSense at http://127.0.0.1:{server.server_port}/ ({sources.mode})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
