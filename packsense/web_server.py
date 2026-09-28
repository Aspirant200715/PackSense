"""Local-only web app for the existing, evidence-gated PackSense batch flow.

The browser cannot supply source paths or scenario rows to this server. An
operator configures immutable local files at startup; the server either views
an audited batch or runs the existing batch CLI and projects its result. No
trained material or shelf-life prediction is created here.
"""

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from packsense.frontend_contract import project_frontend_decisions
from packsense.units import (
    SCENARIO_REFERENCE_COLUMNS, SCENARIO_REQUIRED_COLUMNS,
    SCENARIO_RESPIRATION_COLUMNS,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
MAX_REPORT_BYTES = 100 * 1024 * 1024
BACKEND_PATH_OPTIONS = (
    "route_register", "assessments", "structures", "structure_reviews",
    "transfers", "kinetics_register", "gas_observations",
    "water_observations", "public_candidates",
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
    backend_options: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        if self.batch_report is not None:
            return "audited_report"
        if self.scenarios is not None:
            return "scenario_batch"
        return "unconfigured"


def _read_projected_report(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("batch report exceeds the 100 MB limit")
    with path.open("r", encoding="utf-8") as stream:
        batch = json.load(stream, parse_constant=_reject_nonfinite)
    return project_frontend_decisions(batch)


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


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
            *sources.backend_options, "--report", str(report_path),
        ]
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


class PackSenseHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, sources: AppSources):
        super().__init__(("127.0.0.1", port), PackSenseHandler)
        self.sources = sources
        self.run_lock = threading.Lock()


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
                "has_report": mode == "audited_report",
                "model_deployed": False,
            })
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
            self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin requests are not allowed"})
            return
        if urlsplit(self.path).path != "/api/run":
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        if self.server.sources.mode != "scenario_batch":
            self._json(HTTPStatus.CONFLICT, {"error": "scenario sources are not configured"})
            return
        if self.headers.get("Content-Length", "0") != "0":
            self._json(HTTPStatus.BAD_REQUEST, {"error": "this endpoint accepts no browser-supplied data"})
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


def _arguments() -> tuple[int, AppSources]:
    parser = argparse.ArgumentParser(description="Serve the PackSense MVP on localhost")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--batch-report", type=Path)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--food-master", type=Path)
    parser.add_argument("--material-master", type=Path)
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
    scenario_paths = (args.scenarios, args.food_master, args.material_master)
    if any(scenario_paths) and not all(scenario_paths):
        parser.error("--scenarios, --food-master and --material-master are required together")
    if args.batch_report is not None and any(scenario_paths):
        parser.error("--batch-report cannot be combined with scenario sources")
    for name in ("batch_report", "scenarios", "food_master", "material_master", *BACKEND_PATH_OPTIONS):
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
    if options and args.scenarios is None:
        parser.error("backend options require scenario sources")
    return args.port, AppSources(
        batch_report=args.batch_report, scenarios=args.scenarios,
        food_master=args.food_master, material_master=args.material_master,
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
