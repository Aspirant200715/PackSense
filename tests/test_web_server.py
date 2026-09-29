"""TEST_ONLY local HTTP tests; they do not create packaging training data."""

import csv
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packsense.units import (
    SCENARIO_REFERENCE_COLUMNS, SCENARIO_REQUIRED_COLUMNS,
    SCENARIO_RESPIRATION_COLUMNS,
)
from packsense.web_server import (
    AppSources, PackSenseHTTPServer, _arguments, run_configured_batch,
    scenario_template_csv,
)
from tests.test_frontend_contract import _report
from tests.test_interactive import FOOD_HASH, food_audit, submission


@contextmanager
def running(sources, **server_options):
    server = PackSenseHTTPServer(0, sources, **server_options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(url, *, method="GET", headers=None, body=None):
    request = Request(url, method=method, headers=headers or {}, data=body)
    with urlopen(request, timeout=5) as response:
        return response.status, json.load(response)


class WebServerTests(unittest.TestCase):
    def test_render_port_environment_is_used_by_default(self):
        with patch.dict(os.environ, {"PORT": "4179"}), patch("sys.argv", ["packsense.web_server"]):
            port, _ = _arguments()
        self.assertEqual(4179, port)

    def test_public_catalogue_host_and_health_check(self):
        catalogue = Path(__file__).resolve().parents[1] / "data" / "public_catalogue_candidates.v1.json"
        sources = AppSources(public_candidates=catalogue)
        with running(sources, public_hostnames=("packsense.example",)) as base:
            _, health = request_json(f"{base}/healthz", headers={"Host": "other.example"})
            self.assertEqual({"status": "ok"}, health)
            _, status = request_json(f"{base}/api/status", headers={"Host": "packsense.example"})
            self.assertEqual("published_catalogue", status["mode"])
            self.assertFalse(status["can_evaluate"])
            _, catalogue_payload = request_json(
                f"{base}/api/published-applications", headers={"Host": "packsense.example"},
            )
            self.assertGreater(len(catalogue_payload["applications"]), 0)
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/status", headers={"Host": "other.example"})
            self.assertEqual(403, error.exception.code)
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/evaluate", method="POST",
                             headers={"Host": "packsense.example", "Origin": "https://packsense.example",
                                      "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(409, error.exception.code)

    def test_public_binding_requires_catalogue_and_host(self):
        catalogue = Path(__file__).resolve().parents[1] / "data" / "public_catalogue_candidates.v1.json"
        with self.assertRaisesRegex(ValueError, "catalogue-only"):
            PackSenseHTTPServer(0, AppSources(), bind_host="0.0.0.0",
                                public_hostnames=("packsense.example",))
        with self.assertRaisesRegex(ValueError, "public hostname"):
            PackSenseHTTPServer(0, AppSources(public_candidates=catalogue), bind_host="0.0.0.0")

    def test_template_download_uses_contract_headers_and_no_fake_rows(self):
        expected = (*SCENARIO_REQUIRED_COLUMNS, *SCENARIO_RESPIRATION_COLUMNS,
                    *SCENARIO_REFERENCE_COLUMNS)
        self.assertEqual([list(expected)], list(csv.reader(
            io.StringIO(scenario_template_csv().decode("utf-8"))
        )))
        with running(AppSources()) as base:
            with urlopen(f"{base}/api/scenario-template", timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertEqual("text/csv; charset=utf-8",
                                 response.headers["Content-Type"])
                self.assertIn("attachment;", response.headers["Content-Disposition"])
                self.assertEqual([list(expected)], list(csv.reader(
                    io.StringIO(response.read().decode("utf-8"))
                )))

    def test_relative_source_paths_are_frozen_before_subprocess_cwd_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {name: root / f"TEST_ONLY_{name}.csv" for name in ("scenarios", "food", "material", "routes")}
            for path in files.values():
                path.touch()
            relative = {name: os.path.relpath(path) for name, path in files.items()}
            argv = [
                "packsense.web_server", "--scenarios", relative["scenarios"],
                "--food-master", relative["food"], "--material-master", relative["material"],
                "--route-register", relative["routes"],
            ]
            with patch("sys.argv", argv):
                _, sources = _arguments()
            self.assertEqual(files["scenarios"].resolve(), sources.scenarios)
            self.assertEqual(files["food"].resolve(), sources.food_master)
            self.assertEqual(files["material"].resolve(), sources.material_master)
            self.assertEqual(str(files["routes"].resolve()), sources.backend_options[1])

    def test_unconfigured_service_is_explicit_and_does_not_run(self):
        with running(AppSources()) as base:
            _, status = request_json(f"{base}/api/status")
            self.assertEqual("unconfigured", status["mode"])
            self.assertFalse(status["can_run"])
            self.assertFalse(status["has_public_applications"])
            self.assertFalse(status["model_deployed"])
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/run", method="POST")
            self.assertEqual(409, error.exception.code)
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/published-applications")
            self.assertEqual(404, error.exception.code)
            with urlopen(base, timeout=5) as response:
                self.assertIn(b"PackSense", response.read())

    def test_real_published_applications_are_visible_without_a_scenario(self):
        catalogue = Path(__file__).resolve().parents[1] / "data" / "public_catalogue_candidates.v1.json"
        argv = ["packsense.web_server", "--public-candidates", str(catalogue)]
        with patch("sys.argv", argv):
            _, sources = _arguments()
        self.assertEqual("published_catalogue", sources.mode)
        self.assertEqual(catalogue.resolve(), sources.public_candidates)
        with running(sources) as base:
            _, status = request_json(f"{base}/api/status")
            self.assertTrue(status["has_public_applications"])
            self.assertFalse(status["can_run"])
            self.assertFalse(status["model_deployed"])
            _, payload = request_json(f"{base}/api/published-applications")
            self.assertEqual("published-applications-v1", payload["contract_version"])
            self.assertFalse(payload["model_prediction_available"])
            self.assertFalse(payload["package_approval_available"])
            broccoli = [item for item in payload["applications"] if item["food"] == "broccoli"]
            self.assertEqual(2, len(broccoli))
            self.assertEqual({("VY7K9", 400), ("VY7K4", 500)},
                             {(item["product_code"], item["quantity"]) for item in broccoli})
            self.assertTrue(broccoli[0]["source_url"].startswith("https://"))
            self.assertTrue(all(item["pack_format"] != "box inner liner"
                                for item in payload["applications"]))

    def test_existing_backend_batch_is_projected_on_request(self):
        with tempfile.TemporaryDirectory() as directory:
            batch_path = Path(directory) / "TEST_ONLY_batch.json"
            batch_path.write_text(json.dumps(_report()), encoding="utf-8")
            with running(AppSources(batch_report=batch_path)) as base:
                _, status = request_json(f"{base}/api/status")
                self.assertEqual("audited_report", status["mode"])
                self.assertTrue(status["has_report"])
                code, report = request_json(f"{base}/api/report")
                self.assertEqual(200, code)
                self.assertEqual("frontend-decision-v1", report["contract_version"])
                self.assertEqual(3, report["total_rows"])
                self.assertIsNone(report["rows"][2]["material_prediction"])

    def test_run_reuses_backend_cli_and_keeps_exception_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = AppSources(
                scenarios=root / "TEST_ONLY_scenarios.csv",
                food_master=root / "TEST_ONLY_food.xlsx",
                material_master=root / "TEST_ONLY_material.xlsx",
                public_candidates=root / "TEST_ONLY_public.json",
                backend_options=("--route-register", str(root / "TEST_ONLY_routes.json")),
            )

            def backend(command, **kwargs):
                self.assertEqual("packsense.recommendation_batch", command[2])
                self.assertEqual(str(sources.scenarios), command[3])
                self.assertIn("--route-register", command)
                self.assertEqual(str(sources.public_candidates),
                                 command[command.index("--public-candidates") + 1])
                Path(command[command.index("--report") + 1]).write_text(
                    json.dumps(_report()), encoding="utf-8",
                )
                return SimpleNamespace(returncode=1, stderr="")

            with patch("packsense.web_server.subprocess.run", side_effect=backend):
                report = run_configured_batch(sources)
            self.assertEqual(3, report["total_rows"])
            self.assertEqual("exception", report["rows"][0]["status"])

    def test_reference_pair_enables_one_scenario_form_without_scenario_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            food_path = root / "TEST_ONLY_food.xlsx"
            material_path = root / "TEST_ONLY_material.xlsx"
            food_path.touch()
            material_path.touch()
            with patch("sys.argv", ["packsense.web_server", "--food-master", str(food_path),
                                    "--material-master", str(material_path)]):
                _, sources = _arguments()
            self.assertEqual("interactive_scenario", sources.mode)
            with patch.object(PackSenseHTTPServer, "food_audit", return_value=food_audit()):
                with running(sources) as base:
                    _, status = request_json(f"{base}/api/status")
                    self.assertTrue(status["can_evaluate"])
                    self.assertFalse(status["can_run"])
                    _, search = request_json(f"{base}/api/foods?q=asparagus")
                    self.assertEqual(1, search["form_ready_matches"])
                    self.assertEqual("TEST_ONLY_READY", search["foods"][0]["food_reference_id"])

                    report = {"trace": {"food_master_sha256": FOOD_HASH},
                              "rows": [{"status": "not_ready"}]}
                    with patch("packsense.web_server.run_configured_batch", return_value=report):
                        code, result = request_json(
                            f"{base}/api/evaluate", method="POST",
                            headers={"Content-Type": "application/json"},
                            body=json.dumps(submission()).encode("utf-8"),
                        )
                    self.assertEqual(200, code)
                    self.assertEqual("interactive-evaluation-v1", result["contract_version"])
                    self.assertEqual("browser_submitted", result["input_origin"])
                    self.assertEqual("not_ready", result["report"]["rows"][0]["status"])

    def test_form_rejects_cross_origin_unconfigured_and_unsupported_body(self):
        with running(AppSources()) as base:
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/evaluate", method="POST",
                             headers={"Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(409, error.exception.code)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = AppSources(food_master=root / "TEST_ONLY_food.xlsx",
                                 material_master=root / "TEST_ONLY_material.xlsx")
            with running(sources) as base:
                with self.assertRaises(HTTPError) as error:
                    request_json(f"{base}/api/evaluate", method="POST",
                                 headers={"Origin": "https://unrelated.example",
                                          "Content-Type": "application/json"},
                                 body=json.dumps(submission()).encode("utf-8"))
                self.assertEqual(403, error.exception.code)
                with self.assertRaises(HTTPError) as error:
                    request_json(f"{base}/api/evaluate", method="POST",
                                 headers={"Content-Type": "text/plain"}, body=b"{}")
                self.assertEqual(400, error.exception.code)
                with self.assertRaises(HTTPError) as error:
                    request_json(f"{base}/api/evaluate", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 body=b'{"food_reference_id":"one","food_reference_id":"two"}')
                self.assertEqual(400, error.exception.code)
                with self.assertRaises(HTTPError) as error:
                    request_json(f"{base}/api/evaluate", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 body=b" " * 8193)
                self.assertEqual(400, error.exception.code)

    def test_cross_origin_and_browser_body_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = AppSources(
                scenarios=root / "TEST_ONLY_scenarios.csv",
                food_master=root / "TEST_ONLY_food.xlsx",
                material_master=root / "TEST_ONLY_material.xlsx",
            )
            with running(sources) as base:
                with self.assertRaises(HTTPError) as error:
                    request_json(f"{base}/api/run", method="POST",
                                 headers={"Origin": "https://unrelated.example"})
                self.assertEqual(403, error.exception.code)
                with self.assertRaises(HTTPError) as error:
                    with urlopen(Request(f"{base}/api/run", data=b"scenario=TEST_ONLY"), timeout=5):
                        pass
                self.assertEqual(400, error.exception.code)

    def test_host_header_cannot_be_rebound(self):
        with running(AppSources()) as base:
            with self.assertRaises(HTTPError) as error:
                request_json(f"{base}/api/status", headers={"Host": "unrelated.example"})
            self.assertEqual(403, error.exception.code)


if __name__ == "__main__":
    unittest.main()
