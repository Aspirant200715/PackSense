"""Intake for observed food-package trials, not a shelf-life model.

Only a declared measured experiment can become a schema-valid TrialOutcome.
Source verification, package-structure joins, split design, and model fitting
are deliberately separate gates. A requested shelf life is never an outcome.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from packsense.contracts import TrialOutcome
from packsense.ingestion import InputSchemaError, _read_csv, _read_xlsx, _sha256


TRIAL_REQUIRED_COLUMNS = (
    "trial_id", "trial_group_id", "batch_id", "source_id", "source_locator",
    "evidence_basis", "food_id", "structure_id", "structure_catalogue_version",
    "fill_mass_g", "package_area_m2", "headspace_ml", "storage_temperature_c",
    "storage_relative_humidity_pct", "observed_days", "failure_observed",
    "failure_criterion", "failure_threshold",
)
TRIAL_OPTIONAL_COLUMNS = (
    "failure_mechanism", "exposure_profile_id", "transport_temperature_c",
    "transport_max_temperature_c", "transport_duration_hours",
)
TRIAL_COLUMNS = frozenset(TRIAL_REQUIRED_COLUMNS + TRIAL_OPTIONAL_COLUMNS)
NUMERIC_COLUMNS = frozenset({
    "fill_mass_g", "package_area_m2", "headspace_ml", "storage_temperature_c",
    "storage_relative_humidity_pct", "observed_days", "transport_temperature_c",
    "transport_max_temperature_c", "transport_duration_hours",
})
TRANSPORT_COLUMNS = (
    "transport_temperature_c", "transport_max_temperature_c", "transport_duration_hours",
)
MISSING_TEXT = frozenset({"", "unknown", "not_reported", "not_measured", "n/a", "na"})


@dataclass(frozen=True, slots=True)
class TrialIssue:
    row_number: int
    trial_id: str | None
    field: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TrialEntry:
    source_row_number: int
    outcome: TrialOutcome
    source_locator: str


@dataclass(frozen=True, slots=True)
class TrialAudit:
    source_path: str
    source_sha256: str
    sheet_name: str | None
    total_rows: int
    entries: tuple[TrialEntry, ...]
    issues: tuple[TrialIssue, ...]

    def report(self) -> dict[str, Any]:
        """Schema quality only; accepted rows are not automatically training-ready."""
        outcomes = [entry.outcome for entry in self.entries]
        counts = Counter((issue.field, issue.code) for issue in self.issues)
        group_sizes = Counter(outcome.trial_group_id for outcome in outcomes)
        readiness = (
            "no_valid_trials" if not outcomes else
            "no_observed_failures" if not any(outcome.failure_observed for outcome in outcomes)
            else "not_assessed"
        )
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "sheet_name": self.sheet_name,
            "total_rows": self.total_rows,
            "schema_valid_rows": len(outcomes),
            "rejected_rows": self.total_rows - len(outcomes),
            "observed_failure_rows": sum(outcome.failure_observed for outcome in outcomes),
            "right_censored_rows": sum(not outcome.failure_observed for outcome in outcomes),
            "trial_group_count": len(group_sizes),
            "single_row_group_count": sum(size == 1 for size in group_sizes.values()),
            "batch_count": len({(outcome.source_id, outcome.batch_id) for outcome in outcomes}),
            "source_count": len({outcome.source_id for outcome in outcomes}),
            "training_readiness": readiness,
            "training_readiness_reason": (
                "Schema intake cannot verify source evidence, finished-package links, "
                "independent groups, coverage, or a frozen evaluation split."
            ),
            "issue_counts": [
                {"field": field, "code": code, "count": count}
                for (field, code), count in sorted(counts.items())
            ],
            "issues": [
                {"row_number": x.row_number, "trial_id": x.trial_id,
                 "field": x.field, "code": x.code, "message": x.message}
                for x in self.issues
            ],
        }


def _header(values: tuple[Any, ...]) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise InputSchemaError("trial header names must be non-empty text")
    names = tuple(value.strip() for value in values)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise InputSchemaError(f"duplicate trial columns: {', '.join(duplicates)}")
    missing = sorted(set(TRIAL_REQUIRED_COLUMNS) - set(names))
    if missing:
        raise InputSchemaError(f"missing trial columns: {', '.join(missing)}")
    unexpected = sorted(set(names) - TRIAL_COLUMNS)
    if unexpected:
        raise InputSchemaError(f"unexpected trial columns: {', '.join(unexpected)}")
    transport = set(TRANSPORT_COLUMNS) & set(names)
    if transport and transport != set(TRANSPORT_COLUMNS):
        raise InputSchemaError("all three transport columns must appear together")
    return names


def _text(value: Any, field: str, *, required: bool) -> str | None:
    if value is None or isinstance(value, str) and value.strip().lower() in MISSING_TEXT:
        if required:
            raise ValueError("required trial evidence is blank or marked missing")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _number(value: Any, field: str, *, required: bool) -> float | None:
    if value is None or isinstance(value, str) and not value.strip():
        if required:
            raise ValueError("required numeric trial value is blank")
        return None
    if isinstance(value, bool):
        raise ValueError("must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("must be a finite number") from exc
    if not isfinite(number):
        raise ValueError("must be a finite number")
    if field in {"fill_mass_g", "package_area_m2", "observed_days"} and number <= 0:
        raise ValueError("must be positive")
    if field in {"headspace_ml", "transport_duration_hours"} and number < 0:
        raise ValueError("must not be negative")
    if field == "storage_relative_humidity_pct" and not 0 <= number <= 100:
        raise ValueError("must be between 0 and 100 percent")
    if field.endswith("temperature_c") and number < -273.15:
        raise ValueError("cannot be below absolute zero")
    return number


def _failure_observed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0"}:
        return value.strip().lower() in {"true", "1"}
    raise ValueError("use true/false or 1/0; a censored observation is false")


def _parse_row(raw: dict[str, Any], number: int, *, duplicate: bool,
               conflicting_batch: bool, formula_fields: set[str],
               column_mismatch: bool) -> tuple[TrialEntry | None, tuple[TrialIssue, ...]]:
    identifier = raw.get("trial_id")
    label = identifier.strip() if isinstance(identifier, str) and identifier.strip() else None
    issues: list[TrialIssue] = []

    def issue(field: str, code: str, message: str) -> None:
        issues.append(TrialIssue(number, label, field, code, message))

    if duplicate:
        issue("trial_id", "duplicate_id", "trial_id appears more than once")
    if conflicting_batch:
        issue("trial_group_id", "batch_group_conflict",
              "one batch_id is assigned to multiple trial groups")
    if column_mismatch:
        issue("row", "column_count", "row length differs from header")
    for field in sorted(formula_fields):
        issue(field, "formula_cell", "formulas are not measured source values")

    values: dict[str, Any] = {}
    for field in TRIAL_REQUIRED_COLUMNS + TRIAL_OPTIONAL_COLUMNS:
        if field not in raw or field in formula_fields:
            continue
        value = raw[field]
        try:
            if field in NUMERIC_COLUMNS:
                values[field] = _number(value, field, required=field in TRIAL_REQUIRED_COLUMNS)
            elif field == "failure_observed":
                values[field] = _failure_observed(value)
            else:
                values[field] = _text(value, field, required=field in TRIAL_REQUIRED_COLUMNS)
        except ValueError as exc:
            issue(field, "invalid_value", str(exc))

    if values.get("evidence_basis") != "measured_trial":
        issue("evidence_basis", "unsupported_evidence",
              "only measured_trial is accepted; reference or estimated life is not a label")
    transport = [values.get(field) for field in TRANSPORT_COLUMNS]
    if any(value is not None for value in transport) and not all(
        value is not None for value in transport
    ):
        issue("transport", "incomplete_exposure", "transport values travel together")
    elif all(value is not None for value in transport) and transport[1] < transport[0]:
        issue("transport_max_temperature_c", "inconsistent_temperature",
              "maximum is below transport mean")
    if issues:
        return None, tuple(issues)

    outcome_fields = {field: values.get(field) for field in TrialOutcome.__dataclass_fields__}
    try:
        outcome = TrialOutcome(**outcome_fields)
    except (TypeError, ValueError) as exc:
        issue("row", "contract_violation", str(exc))
        return None, tuple(issues)
    return TrialEntry(number, outcome, values["source_locator"]), ()


def audit_trial_outcomes(path: str | Path, *, sheet_name: str | None = None) -> TrialAudit:
    """Validate declared measured outcomes, preserving every rejection reason.

    This is not a provenance audit or authorization to train a model.
    """
    source = Path(path).resolve(strict=True)
    if source.suffix.lower() == ".csv":
        if sheet_name is not None:
            raise InputSchemaError("sheet_name is only valid for XLSX")
        raw_header, rows, selected_sheet = _read_csv(source)
    elif source.suffix.lower() == ".xlsx":
        raw_header, rows, selected_sheet = _read_xlsx(source, sheet_name)
    else:
        raise InputSchemaError("trial input must be a .csv or .xlsx file")
    header = _header(raw_header)
    nonempty_rows = [row for row in rows if any(
        value is not None and (not isinstance(value, str) or value.strip())
        for value in row.values
    )]
    identifiers = Counter(
        row.values[header.index("trial_id")].strip()
        for row in nonempty_rows
        if len(row.values) > header.index("trial_id")
        and isinstance(row.values[header.index("trial_id")], str)
        and row.values[header.index("trial_id")].strip()
    )
    batch_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in nonempty_rows:
        if len(row.values) > max(header.index("source_id"), header.index("batch_id"),
                                 header.index("trial_group_id")):
            source_id = row.values[header.index("source_id")]
            batch = row.values[header.index("batch_id")]
            group = row.values[header.index("trial_group_id")]
            if all(isinstance(value, str) and value.strip()
                   for value in (source_id, batch, group)):
                batch_groups[(source_id.strip(), batch.strip())].add(group.strip())

    entries: list[TrialEntry] = []
    issues: list[TrialIssue] = []
    for row in nonempty_rows:
        raw = dict(zip(header, row.values))
        identifier = raw.get("trial_id")
        batch = raw.get("batch_id")
        source_id = raw.get("source_id")
        formula_fields = {header[index] for index in row.formula_columns if index < len(header)}
        entry, row_issues = _parse_row(
            raw, row.number,
            duplicate=isinstance(identifier, str) and identifiers[identifier.strip()] > 1,
            conflicting_batch=(isinstance(source_id, str) and isinstance(batch, str)
                               and len(batch_groups[(source_id.strip(), batch.strip())]) > 1),
            formula_fields=formula_fields,
            column_mismatch=len(row.values) != len(header),
        )
        if entry is not None:
            entries.append(entry)
        issues.extend(row_issues)
    return TrialAudit(str(source), _sha256(source), selected_sheet,
                      len(nonempty_rows), tuple(entries), tuple(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit measured PackSense trial outcomes")
    parser.add_argument("input", type=Path)
    parser.add_argument("--sheet", help="XLSX sheet name; required if there are several sheets")
    parser.add_argument("--report", type=Path, help="new full JSON exception report path")
    args = parser.parse_args()
    try:
        audit = audit_trial_outcomes(args.input, sheet_name=args.sheet)
    except (InputSchemaError, OSError, csv.Error, BadZipFile) as exc:
        parser.exit(2, f"input error: {exc}\n")
    report = audit.report()
    if args.report:
        try:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2) + "\n")
        except FileExistsError:
            parser.exit(2, "report error: output already exists; choose a new path\n")
    print(json.dumps({key: value for key, value in report.items() if key != "issues"}, indent=2))
    return 0 if not report["rejected_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
