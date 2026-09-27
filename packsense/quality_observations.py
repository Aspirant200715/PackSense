"""Audit the cited measured-quality dataset without treating it as shelf life.

The source contains package-level quality measurements at assessment times.
It does not contain declared failure events, right-censoring, or full package
specifications, so its records are deliberately separate from TrialOutcome.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

SOURCE_DOI = "10.17632/tvsw53j89z.1"
SOURCE_LOCATOR = "https://data.mendeley.com/datasets/tvsw53j89z/1"
SOURCE_LICENSE = "CC BY 4.0"
SOURCE_DATA_ROLE = "measured_quality_timepoint_not_shelf_life_label"

LONG_COLUMNS = (
    "package", "meat", "storage", "time", "outcome", "value",
    "row_type", "row_in_group", "domain",
)
PACKAGE_COLUMNS = (
    "source_doi", "source_locator", "source_file_sha256", "data_role",
    "food_as_reported", "package_as_reported", "storage_as_reported",
    "assessment_day", "source_row_in_group", "source_csv_line_numbers",
    "water_activity", "peroxide_value_meq_kg", "ph",
    "mesophilic_bacteria_cfu_g", "coliform_cfu_g", "yeast_cfu_g",
    "mould_cfu_g",
)
MODEL_FEATURE_COLUMNS = ("food", "package", "storage", "assessment_day")
MODEL_TARGET_COLUMNS = tuple(column for column, _domain in (
    ("water_activity", "Physicochemical"),
    ("peroxide_value_meq_kg", "Physicochemical"),
    ("ph", "Physicochemical"),
    ("mesophilic_bacteria_cfu_g", "Microbial"),
    ("coliform_cfu_g", "Microbial"),
    ("yeast_cfu_g", "Microbial"),
    ("mould_cfu_g", "Microbial"),
))
MODEL_GROUP_COLUMN = "treatment_day_group"
MODEL_SOURCE_LINES_COLUMN = "source_csv_line_numbers"

OUTCOME_COLUMNS = {
    "Water activity": ("water_activity", "Physicochemical"),
    "Peroxide value": ("peroxide_value_meq_kg", "Physicochemical"),
    "pH": ("ph", "Physicochemical"),
    "Mesophilic bacteria": ("mesophilic_bacteria_cfu_g", "Microbial"),
    "Coliform count": ("coliform_cfu_g", "Microbial"),
    "Yeast": ("yeast_cfu_g", "Microbial"),
    "Mould": ("mould_cfu_g", "Microbial"),
}
FOODS = frozenset({"Catfish", "Rabbit"})
PACKAGES = frozenset({"Vacuum", "LDPE", "Paper"})
STORAGE_TYPES = frozenset({"Ambient", "Refrigerated"})
ASSESSMENT_DAYS = frozenset({30, 60, 90})
REPLICATES = frozenset({1, 2})


@dataclass(frozen=True, slots=True)
class QualityIssue:
    source_file: str
    row_number: int
    field: str
    code: str
    message: str


class QualityInputError(ValueError):
    """The supplied files cannot be interpreted as this source dataset."""


@dataclass(frozen=True, slots=True)
class _QualityRow:
    number: int
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityObservation:
    source_row_number: int
    food: str
    package: str
    storage: str
    assessment_day: int
    replicate: int
    source_csv_line_numbers: tuple[int, ...]
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class QualityDataAudit:
    long_path: str
    package_path: str
    long_sha256: str
    package_sha256: str
    observations: tuple[QualityObservation, ...]
    issues: tuple[QualityIssue, ...]
    long_row_count: int
    baseline_value_count: int
    matched_measurement_count: int

    def report(self) -> dict[str, Any]:
        treatment_groups = Counter(
            (row.food, row.package, row.storage) for row in self.observations
        )
        zero_counts = {
            column: sum(row.values[column] == 0 for row in self.observations)
            for column, _domain in OUTCOME_COLUMNS.values()
        }
        issue_counts = Counter((issue.source_file, issue.field, issue.code)
                               for issue in self.issues)
        passed = not self.issues and (
            self.long_row_count == 672
            and len(self.observations) == 72
            and self.baseline_value_count == 168
            and self.matched_measurement_count == 504
            and len(treatment_groups) == 12
            and all(size == 6 for size in treatment_groups.values())
        )
        return {
            "audit_version": "public-measured-quality-v1",
            "audit_status": "passed" if passed else "failed",
            "source": {
                "title": (
                    "Effects of packaging system and storage temperature on the "
                    "physicochemical and microbiological stability of smoked catfish and rabbit"
                ),
                "doi": SOURCE_DOI,
                "locator": SOURCE_LOCATOR,
                "license": SOURCE_LICENSE,
                "long_file_sha256": self.long_sha256,
                "package_file_sha256": self.package_sha256,
            },
            "counts": {
                "long_format_rows_including_day0": self.long_row_count,
                "shared_day0_baseline_measurements_excluded_from_package_rows": (
                    self.baseline_value_count
                ),
                "package_level_rows_days_30_60_90": len(self.observations),
                "measured_quality_values_reconciled": self.matched_measurement_count,
                "outcomes_per_package_row": len(OUTCOME_COLUMNS),
                "treatment_groups_food_package_storage": len(treatment_groups),
                "package_observations_per_treatment_group": sorted(
                    set(treatment_groups.values())
                ),
                "sources": 1 if self.observations else 0,
                "zero_values_by_measurement": zero_counts,
            },
            "readiness": {
                "measured_quality_response_experiment": (
                    "exploratory_only_single_source" if passed else "not_ready_audit_failed"
                ),
                "shelf_life_prediction": "not_ready_no_failure_or_censoring_labels",
                "package_recommendation": "not_ready_incomplete_structure_and_exposure_data",
                "reason": (
                    "The source contains observed quality measurements at sampled days, "
                    "not observed shelf-life failure times or right-censored endpoints."
                ),
            },
            "temperature_and_package_coverage": {
                "storage_field": "categorical only in the supplied package-level records",
                "source_temperature_context": {
                    "Ambient": "approximately 25-30 C",
                    "Refrigerated": "4-5 C",
                },
                "exact_row_temperature": False,
                "transport_exposure": False,
                "relative_humidity": False,
                "complete_structure_or_gauge": False,
            },
            "limitations": [
                "Only one public study/source is represented; no independent-source test is possible.",
                "The source reports no processing-run identifiers, so run-level variation cannot be estimated.",
                "Day-0 values are shared starting baselines and are not additional package trials.",
                "The three reported packaging systems are not complete, gauge-specific catalogue structures.",
                "The source explicitly says these data are not commercial shelf-life or food-safety validation.",
                "Microbial zeros are retained as source values; source analysis treats non-detects at stated limits.",
            ],
            "issue_counts": [
                {
                    "source_file": file_name,
                    "field": field,
                    "code": code,
                    "count": count,
                }
                for (file_name, field, code), count in sorted(issue_counts.items())
            ],
            "issues": [
                {
                    "source_file": issue.source_file,
                    "row_number": issue.row_number,
                    "field": issue.field,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[tuple[str, ...], list[_QualityRow]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise QualityInputError("CSV is empty") from exc
        rows = [
            _QualityRow(number, tuple(values))
            for number, values in enumerate(reader, start=2)
        ]
    return header, rows


def _columns(raw: tuple[Any, ...], expected: tuple[str, ...], name: str) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value.strip() for value in raw):
        raise QualityInputError(f"{name} header names must be non-empty text")
    names = tuple(value.strip() for value in raw)
    duplicates = sorted(column for column, count in Counter(names).items() if count > 1)
    if duplicates:
        raise QualityInputError(f"duplicate {name} columns: {', '.join(duplicates)}")
    missing = sorted(set(expected) - set(names))
    extra = sorted(set(names) - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected: {', '.join(extra)}")
        raise QualityInputError(f"invalid {name} columns ({'; '.join(details)})")
    return names


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError("must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("must be a finite number") from exc
    if not isfinite(number):
        raise ValueError("must be a finite number")
    if number < 0:
        raise ValueError("must not be negative")
    if field == "water_activity" and not 0 <= number <= 1:
        raise ValueError("must be between 0 and 1")
    if field == "ph" and not 0 <= number <= 14:
        raise ValueError("must be between 0 and 14")
    return number


def _row_map(header: tuple[str, ...], row: _QualityRow) -> dict[str, Any]:
    if len(row.values) != len(header):
        raise ValueError("row length differs from header")
    return dict(zip(header, row.values))


def audit_public_quality_data(
    long_path: str | Path,
    package_path: str | Path,
) -> QualityDataAudit:
    """Validate the two source layouts and reconcile every post-baseline value.

    Rows and zero values are preserved, not imputed. This audit does not
    promote the observations to shelf-life trials or package recommendations.
    """
    long_file = Path(long_path).resolve(strict=True)
    package_file = Path(package_path).resolve(strict=True)
    if long_file.suffix.lower() != ".csv" or package_file.suffix.lower() != ".csv":
        raise QualityInputError("both measured-quality inputs must be CSV files")

    long_header_raw, long_rows = _read_csv(long_file)
    package_header_raw, package_rows = _read_csv(package_file)
    long_header = _columns(long_header_raw, LONG_COLUMNS, "long-format")
    package_header = _columns(package_header_raw, PACKAGE_COLUMNS, "package-level")
    long_sha256 = _sha256(long_file)
    package_sha256 = _sha256(package_file)
    issues: list[QualityIssue] = []

    def issue(file_name: str, row_number: int, field: str, code: str, message: str) -> None:
        issues.append(QualityIssue(file_name, row_number, field, code, message))

    long_file_name = long_file.name
    package_file_name = package_file.name
    long_by_line: dict[int, dict[str, Any]] = {}
    long_keys: set[tuple[str, str, str, int, str, int]] = set()
    long_groups: Counter[tuple[str, str, str, str]] = Counter()
    baseline_count = 0

    for row in long_rows:
        try:
            item = _row_map(long_header, row)
            package = item["package"]
            food = item["meat"]
            storage = item["storage"]
            outcome = item["outcome"]
            if package not in PACKAGES or food not in FOODS or storage not in STORAGE_TYPES:
                raise ValueError("unknown source food, package, or storage category")
            if outcome not in OUTCOME_COLUMNS:
                raise ValueError("unknown measured outcome")
            time_value = _number(item["time"], "time")
            replicate_value = _number(item["row_in_group"], "row_in_group")
            value = _number(item["value"], "value")
            if not time_value.is_integer() or int(time_value) not in {0, *ASSESSMENT_DAYS}:
                raise ValueError("time must be 0, 30, 60, or 90 days")
            if not replicate_value.is_integer() or int(replicate_value) not in REPLICATES:
                raise ValueError("row_in_group must be replicate 1 or 2")
            if item["row_type"] != "measured":
                raise ValueError("only source rows marked measured are accepted")
            expected_domain = OUTCOME_COLUMNS[outcome][1]
            if item["domain"] != expected_domain:
                raise ValueError("domain does not match the source outcome")
            time_day = int(time_value)
            replicate = int(replicate_value)
            key = (food, package, storage, time_day, outcome, replicate)
            if key in long_keys:
                issue(long_file_name, row.number, "row", "duplicate_observation",
                      "the food/package/storage/day/outcome/replicate key is repeated")
            long_keys.add(key)
            long_groups[(food, package, storage, outcome)] += 1
            if time_day == 0:
                baseline_count += 1
            long_by_line[row.number] = {
                "package": package,
                "food": food,
                "storage": storage,
                "day": time_day,
                "outcome": outcome,
                "replicate": replicate,
                "value": value,
            }
        except (KeyError, TypeError, ValueError) as exc:
            issue(long_file_name, row.number, "row", "invalid_value", str(exc))

    if len(long_rows) != 672:
        issue(long_file_name, 1, "rows", "unexpected_row_count",
              f"expected 672 source rows, found {len(long_rows)}")
    if baseline_count != 168:
        issue(long_file_name, 1, "time", "unexpected_baseline_count",
              f"expected 168 shared day-0 values, found {baseline_count}")
    if len(long_groups) != 84 or any(count != 8 for count in long_groups.values()):
        issue(long_file_name, 1, "groups", "incomplete_source_design",
              "expected 84 food/package/storage/outcome groups with 8 measurements each")

    observations: list[QualityObservation] = []
    package_keys: set[tuple[str, str, str, int, int]] = set()
    used_source_lines: list[int] = []
    matched_count = 0
    referenced_hashes: set[str] = set()

    for row in package_rows:
        try:
            item = _row_map(package_header, row)
            if item["source_doi"] != SOURCE_DOI or item["source_locator"] != SOURCE_LOCATOR:
                raise ValueError("source DOI or locator differs from the cited dataset")
            if item["data_role"] != SOURCE_DATA_ROLE:
                raise ValueError("data_role must identify quality timepoints, not shelf-life labels")
            if item["food_as_reported"] not in FOODS:
                raise ValueError("unknown source food category")
            if item["package_as_reported"] not in PACKAGES:
                raise ValueError("unknown source package category")
            if item["storage_as_reported"] not in STORAGE_TYPES:
                raise ValueError("unknown source storage category")
            day_value = _number(item["assessment_day"], "assessment_day")
            replicate_value = _number(item["source_row_in_group"], "source_row_in_group")
            if not day_value.is_integer() or int(day_value) not in ASSESSMENT_DAYS:
                raise ValueError("assessment_day must be 30, 60, or 90")
            if not replicate_value.is_integer() or int(replicate_value) not in REPLICATES:
                raise ValueError("source_row_in_group must be replicate 1 or 2")
            row_hash = item["source_file_sha256"]
            if len(row_hash) != 64 or any(c not in "0123456789abcdef" for c in row_hash):
                raise ValueError("source_file_sha256 must be lowercase SHA-256")
            referenced_hashes.add(row_hash)
            values = {
                column: _number(item[column], column)
                for column, _domain in OUTCOME_COLUMNS.values()
            }
            food = item["food_as_reported"]
            package = item["package_as_reported"]
            storage = item["storage_as_reported"]
            day = int(day_value)
            replicate = int(replicate_value)
            key = (food, package, storage, day, replicate)
            if key in package_keys:
                issue(package_file_name, row.number, "row", "duplicate_package_observation",
                      "the food/package/storage/day/replicate key is repeated")
            package_keys.add(key)

            line_tokens = item["source_csv_line_numbers"].split(";")
            if len(line_tokens) != len(OUTCOME_COLUMNS):
                raise ValueError("source_csv_line_numbers must contain one line for each outcome")
            line_numbers = tuple(int(token) for token in line_tokens)
            if len(set(line_numbers)) != len(line_numbers) or any(line < 2 for line in line_numbers):
                raise ValueError("source CSV line numbers must be unique positive data lines")
            used_source_lines.extend(line_numbers)

            observation = QualityObservation(
                row.number, food, package, storage, day, replicate,
                line_numbers, values,
            )
            observations.append(observation)

            if row_hash != long_sha256:
                issue(package_file_name, row.number, "source_file_sha256", "source_hash_mismatch",
                      "recorded source hash does not match the supplied long-format CSV")
            for line_number in line_numbers:
                source_row = long_by_line.get(line_number)
                if source_row is None:
                    issue(package_file_name, row.number, "source_csv_line_numbers",
                          "source_line_not_found",
                          f"line {line_number} is absent or invalid in the source CSV")
                    continue
                if (
                    source_row["food"] != food
                    or source_row["package"] != package
                    or source_row["storage"] != storage
                    or source_row["day"] != day
                    or source_row["replicate"] != replicate
                ):
                    issue(package_file_name, row.number, "source_csv_line_numbers",
                          "source_context_mismatch",
                          f"line {line_number} does not match this package observation")
                    continue
                # Match by the source outcome and target column, not by value alone.
                source_outcome = source_row["outcome"]
                column = OUTCOME_COLUMNS[source_outcome][0]
                if values[column] != source_row["value"]:
                    issue(package_file_name, row.number, column, "measurement_mismatch",
                          f"value differs from source line {line_number}")
                    continue
                matched_count += 1
        except (KeyError, TypeError, ValueError) as exc:
            issue(package_file_name, row.number, "row", "invalid_value", str(exc))

    if len(package_rows) != 72:
        issue(package_file_name, 1, "rows", "unexpected_row_count",
              f"expected 72 package-level rows, found {len(package_rows)}")
    if referenced_hashes != {long_sha256}:
        issue(package_file_name, 1, "source_file_sha256", "source_hash_coverage",
              "every package row must cite the supplied long-format CSV hash")
    if len(used_source_lines) != 504 or len(set(used_source_lines)) != 504:
        issue(package_file_name, 1, "source_csv_line_numbers", "source_line_coverage",
              "expected 504 unique non-baseline source lines for 72 rows and 7 outcomes")
    treatment_groups = Counter(
        (item.food, item.package, item.storage) for item in observations
    )
    if len(treatment_groups) != 12 or any(count != 6 for count in treatment_groups.values()):
        issue(package_file_name, 1, "groups", "incomplete_package_design",
              "expected 12 treatment groups with 6 package observations each")

    return QualityDataAudit(
        str(long_file), str(package_file), long_sha256, package_sha256,
        tuple(observations), tuple(issues), len(long_rows), baseline_count, matched_count,
    )


def _locate_kaggle_input(filename: str) -> Path:
    input_root = Path("/kaggle/input")
    candidates = list(input_root.rglob(filename))
    if len(candidates) != 1:
        available = sorted(
            str(path.relative_to(input_root))
            for path in input_root.rglob("*")
            if path.is_file()
        )
        raise QualityInputError(
            f"expected one {filename!r} under {input_root}, found {len(candidates)}; "
            f"available files: {available}"
        )
    return candidates[0]


def _write_kaggle_model_input(audit: QualityDataAudit, output_path: Path) -> None:
    columns = (*MODEL_FEATURE_COLUMNS, *MODEL_TARGET_COLUMNS,
               MODEL_GROUP_COLUMN, MODEL_SOURCE_LINES_COLUMN)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for observation in audit.observations:
            writer.writerow({
                "food": observation.food,
                "package": observation.package,
                "storage": observation.storage,
                "assessment_day": observation.assessment_day,
                **observation.values,
                MODEL_GROUP_COLUMN: "|".join((
                    observation.food, observation.package, observation.storage,
                    str(observation.assessment_day),
                )),
                MODEL_SOURCE_LINES_COLUMN: ";".join(
                    str(line) for line in observation.source_csv_line_numbers
                ),
            })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit source-backed measured quality observations; not shelf-life trials"
    )
    parser.add_argument("long_csv", type=Path, nargs="?")
    parser.add_argument("package_csv", type=Path, nargs="?")
    parser.add_argument("--report", type=Path, help="write a new JSON audit report")
    args = parser.parse_args()

    kaggle_mode = Path("/kaggle/input").is_dir() and Path("/kaggle/working").is_dir()
    try:
        if kaggle_mode and args.long_csv is None and args.package_csv is None:
            args.long_csv = _locate_kaggle_input("packsense_public_measured_quality_raw_672.csv")
            args.package_csv = _locate_kaggle_input("packsense_public_measured_quality_packages_72.csv")
        elif args.long_csv is None or args.package_csv is None:
            parser.error("provide both CSV paths, or run without paths inside the Kaggle kernel")
        audit = audit_public_quality_data(args.long_csv, args.package_csv)
    except (QualityInputError, OSError, csv.Error) as exc:
        parser.exit(2, f"input error: {exc}\n")
    report = audit.report()

    if kaggle_mode:
        if report["audit_status"] != "passed":
            parser.exit(1, "audit failed; refusing to prepare Kaggle model input\n")
        output_dir = Path("/kaggle/working")
        model_input_path = output_dir / "packsense_measured_quality_model_input.csv"
        _write_kaggle_model_input(audit, model_input_path)
        report_path = args.report or output_dir / "packsense_measured_quality_prep_report.json"
        preparation = {
            "status": "prepared_no_model_fit",
            "source_doi": SOURCE_DOI,
            "license": SOURCE_LICENSE,
            "prepared_file": model_input_path.name,
            "prepared_rows": len(audit.observations),
            "feature_columns": list(MODEL_FEATURE_COLUMNS),
            "target_columns": list(MODEL_TARGET_COLUMNS),
            "group_split_column": MODEL_GROUP_COLUMN,
            "provenance_column": MODEL_SOURCE_LINES_COLUMN,
            "processing": {
                "shared_day0_baselines": "excluded; not independent package trials",
                "measurement_values": "preserved as reported; no imputation or synthesis",
                "microbial_zero_values": (
                    "preserved; source non-detect transforms are not applied in this file"
                ),
                "temperature": "categorical source storage only; no midpoint imputation",
                "intended_scope": "exploratory within-study quality-indicator prediction only",
                "shelf_life_training": "not performed; no failure/censoring endpoint",
                "package_recommendations": "not performed; insufficient package specifications",
            },
            "audit": report,
        }
        report_to_write = preparation
    else:
        report_path = args.report
        report_to_write = report

    if report_path:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report_to_write, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            parser.exit(2, f"report error: {exc}\n")
    printable = {key: value for key, value in report_to_write.items() if key != "issues"}
    print(json.dumps(printable, indent=2))
    return 0 if report["audit_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
