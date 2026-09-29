"""Rebuild the archived, evidence-gated website demo from approved inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from packsense.catalogue_candidates import load_candidate_catalogue
from packsense.interactive import scenario_row_from_submission
from packsense.masters import load_food_references
from packsense.units import (
    SCENARIO_REFERENCE_COLUMNS, SCENARIO_REQUIRED_COLUMNS,
    SCENARIO_RESPIRATION_COLUMNS,
)
from packsense.web_server import AppSources, run_configured_batch


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "demo_scenarios.v1.json"
CATALOGUE = ROOT / "data" / "public_catalogue_candidates.v1.json"
OUTPUT = ROOT / "web" / "demo"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_links(citations: str) -> list[dict[str, str]]:
    links = []
    for citation in citations.split(" | "):
        label, separator, url = citation.partition(": ")
        parsed = urlsplit(url)
        if not separator or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"demo food citation is not a safe HTTPS link: {citation}")
        links.append({"label": label, "url": url})
    return links


def build_demo_report(food_master: Path, material_master: Path, output: Path = OUTPUT) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["contract_version"] != "packsense-demo-scenarios-v1":
        raise ValueError("unsupported demo manifest")
    food_master = food_master.resolve()
    material_master = material_master.resolve()
    for path, field in ((food_master, "food_master_sha256"), (material_master, "material_master_sha256")):
        if _sha256(path) != manifest[field]:
            raise ValueError(f"{field} differs from the reviewed demo source")
    catalogue, catalogue_hash = load_candidate_catalogue(CATALOGUE)
    if catalogue_hash != manifest["public_candidate_catalogue_sha256"]:
        raise ValueError("public candidate catalogue differs from the reviewed demo source")
    foods = load_food_references(food_master)
    if foods.issues or foods.source_sha256 != manifest["food_master_sha256"]:
        raise ValueError("demo food reference has rejected rows or a different hash")

    candidates = {item["candidate_id"]: item for item in catalogue["candidates"]}
    sources = {item["source_id"]: item for item in catalogue["sources"]}
    rows = []
    evidence = []
    seen = set()
    for scenario in manifest["scenarios"]:
        record_id = scenario["record_id"]
        if record_id in seen or not record_id.startswith("DEMO-"):
            raise ValueError("demo record IDs must be distinct and visibly marked")
        seen.add(record_id)
        candidate = candidates[scenario["supplier_candidate_id"]]
        conditions = scenario["conditions"]
        applications = [application for application in candidate["applications"]
                        if application["quantity"] == conditions["net_pack_quantity"]
                        and application["quantity_unit"] == conditions["net_pack_quantity_unit"]
                        and application["storage_temperature_min_c"] <= conditions["storage_temperature_c"]
                        <= application["storage_temperature_max_c"]]
        if not applications:
            raise ValueError(f"{record_id} has no matching manufacturer-listed pack quantity and storage range")
        payload = {
            "food_reference_id": scenario["food_reference_id"],
            "food_master_sha256": foods.source_sha256,
            **conditions,
        }
        row, profile = scenario_row_from_submission(payload, foods)
        row["record_id"] = record_id
        rows.append(row)
        source = sources[candidate["source_id"]]
        evidence.append({
            "record_id": record_id,
            "food_reference_id": profile["food_reference_id"],
            "pH_basis": profile["pH_basis"],
            "pH_evidence": profile["pH_evidence"],
            "food_source_links": _source_links(profile["source_citations"]),
            "supplier_product_code": candidate["product_code"],
            "supplier_source_url": source["url"],
            "supplier_source_locator": candidate["source_locator"],
        })

    with tempfile.TemporaryDirectory(prefix="packsense-demo-") as temporary:
        scenarios = Path(temporary) / "scenarios.csv"
        with scenarios.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=(
                *SCENARIO_REQUIRED_COLUMNS, *SCENARIO_RESPIRATION_COLUMNS,
                *SCENARIO_REFERENCE_COLUMNS,
            ), lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(rows)
        report = run_configured_batch(AppSources(
            scenarios=scenarios, food_master=food_master,
            material_master=material_master, public_candidates=CATALOGUE,
        ))
    if report["trace"]["food_master_sha256"] != manifest["food_master_sha256"] \
            or report["trace"]["material_master_sha256"] != manifest["material_master_sha256"] \
            or report["trace"]["public_candidate_catalogue_sha256"] != catalogue_hash:
        raise ValueError("demo report trace differs from its reviewed sources")
    if report["total_rows"] != len(rows) or any(row["status"] != "not_ready" for row in report["rows"]):
        raise ValueError("demo report no longer matches its evidence-gated release boundary")
    for row, source in zip(report["rows"], evidence, strict=True):
        leads = row["supplier_application_lookup"]["leads"]
        if row["record_id"] != source["record_id"] or not any(
            lead["product_code"] == source["supplier_product_code"]
            and lead["source_url"] == source["supplier_source_url"]
            for lead in leads
        ):
            raise ValueError("demo supplier source is absent from the generated report")

    context = {
        "contract_version": "packsense-demo-evidence-v1",
        "input_note": manifest["input_note"],
        "trace": report["trace"],
        "scenarios": evidence,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "evidence.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("food_master", type=Path)
    parser.add_argument("material_master", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    build_demo_report(args.food_master, args.material_master, args.output)


if __name__ == "__main__":
    main()
