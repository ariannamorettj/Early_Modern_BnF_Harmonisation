"""Shared utilities for the 02_sampling inspection scripts.

This module centralises the logic reused by the separate command-line tools in
`02_sampling`. It supports recursive traversal of ZIP archives, including nested
ZIP files, CSV loading, optional filtering by internal CSV file and by detected
year, timestamped output-name construction, unique-value extraction, grouped
value counting, and row extraction for field=value sampling.

The utilities are intentionally generic so that the entry scripts can stay
small and focused:

- `01_zip_tree.py` renders the archive tree and file counts;
- `02_column_names.py` reports all column names found across the ZIP;
- `03_field_value_row_sample.py` extracts all rows, or a bounded sample of rows,
  matching one selected field=value condition;
- scripts later moved to the analysis module may still reuse the unique-value
  and grouped-count helpers defined here.
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import zipfile
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

DEFAULT_OUTPUT_DIR = os.path.join("02_sampling", "data")
DEFAULT_ENCODING = "utf-8"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
YEAR_PATTERN = re.compile(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)")
SOURCE_PATH_FIELD = "__internal_csv_path"


@dataclass(frozen=True)
class CsvContent:
    """Container for one CSV file extracted from a ZIP archive."""

    columns: tuple[str, ...]
    rows: list[dict[str, str | None]]


def current_timestamp() -> str:
    """Return the module-wide timestamp format."""

    return datetime.now().strftime(TIMESTAMP_FORMAT)


def sanitize_token(value: object, max_length: int = 80) -> str:
    """Normalise an arbitrary value so it can safely appear in a file name."""

    token = str(value).strip()
    if not token:
        token = "empty"
    token = token.replace(os.sep, "-")
    token = token.replace(" ", "-")
    token = re.sub(r"[^A-Za-z0-9._+-]+", "-", token)
    token = re.sub(r"-+", "-", token).strip("-._")
    if not token:
        token = "value"
    if len(token) > max_length:
        token = token[:max_length].rstrip("-._")
    return token


def get_entry_script_name(entry_script: str | None = None) -> str:
    """Return the basename of the entry script without its extension."""

    if entry_script is None:
        entry_script = __file__
    return Path(entry_script).stem


def build_output_path(
    *,
    output_dir: str,
    entry_script: str,
    params: OrderedDict[str, object] | dict[str, object] | None = None,
    dataset_index: int | None = None,
    timestamp: str | None = None,
    suffix: str = ".txt",
) -> str:
    """Construct a timestamped output path.

    The input dataset path is intentionally excluded from the output filename.
    Only the entry script name, relevant runtime parameters, an optional dataset
    index, and the timestamp are used.
    """

    os.makedirs(output_dir, exist_ok=True)
    tokens = [get_entry_script_name(entry_script)]

    for key, value in (params or {}).items():
        if value is None or value is False:
            continue
        if isinstance(value, (list, tuple, set)):
            joined = "+".join(sanitize_token(item, max_length=30) for item in value)
            tokens.append(f"{sanitize_token(key, max_length=30)}-{joined}")
        elif value is True:
            tokens.append(sanitize_token(key, max_length=40))
        else:
            tokens.append(f"{sanitize_token(key, max_length=30)}-{sanitize_token(value)}")

    if dataset_index is not None:
        tokens.append(f"set{dataset_index:02d}")

    tokens.append(timestamp or current_timestamp())
    filename = "_".join(token for token in tokens if token) + suffix
    return os.path.join(output_dir, filename)


def _walk_zip(
    zf: zipfile.ZipFile,
    *,
    prefix: str = "",
    encoding: str = DEFAULT_ENCODING,
    structure: list[tuple[str, str]] | None = None,
    ext_counter: Counter[str] | None = None,
    csv_files: OrderedDict[str, CsvContent] | None = None,
) -> tuple[list[tuple[str, str]], Counter[str], OrderedDict[str, CsvContent]]:
    """Traverse a ZIP archive recursively and collect structure and CSV content."""

    if structure is None:
        structure = []
    if ext_counter is None:
        ext_counter = Counter()
    if csv_files is None:
        csv_files = OrderedDict()

    for name in zf.namelist():
        full_path = os.path.join(prefix, name) if prefix else name

        if name.endswith("/"):
            structure.append((full_path, "dir"))
            continue

        if name.lower().endswith(".zip"):
            ext_counter["zip"] += 1
            structure.append((full_path, "zip"))
            with zf.open(name) as nested_handle:
                nested_data = nested_handle.read()
            with zipfile.ZipFile(io.BytesIO(nested_data)) as nested_zf:
                _walk_zip(
                    nested_zf,
                    prefix=full_path,
                    encoding=encoding,
                    structure=structure,
                    ext_counter=ext_counter,
                    csv_files=csv_files,
                )
            continue

        ext = os.path.splitext(name)[1].lower() or "[no_extension]"
        ext_counter[ext] += 1
        structure.append((full_path, "file"))

        if name.lower().endswith(".csv"):
            with zf.open(name) as raw_handle:
                text_handle = io.TextIOWrapper(raw_handle, encoding=encoding)
                reader = csv.DictReader(text_handle)
                columns = tuple(reader.fieldnames or ())
                rows = list(reader)
            csv_files[full_path] = CsvContent(columns=columns, rows=rows)

    return structure, ext_counter, csv_files


def scan_zip_archive(
    zip_path: str,
    *,
    encoding: str = DEFAULT_ENCODING,
) -> tuple[list[tuple[str, str]], Counter[str], OrderedDict[str, CsvContent]]:
    """Read one ZIP archive recursively and return structure plus CSV payloads."""

    with zipfile.ZipFile(zip_path) as zf:
        return _walk_zip(zf, encoding=encoding)


def extract_years_from_path(path: str) -> list[int]:
    """Extract all 4-digit years that look like file-level year markers."""

    years = [int(match.group(0)) for match in YEAR_PATTERN.finditer(path)]
    seen: set[int] = set()
    ordered: list[int] = []
    for year in years:
        if year not in seen:
            seen.add(year)
            ordered.append(year)
    return ordered


def path_matches_years(path: str, years: Iterable[int] | None) -> bool:
    """Return True if the internal path matches the requested years.

    Matching is based on 4-digit year tokens detected in the internal CSV path,
    for example `raw_edition_data_for_the_year_1454.csv`. If a year filter is
    requested and no year can be detected from the path, the file is excluded.
    """

    if years is None:
        return True
    requested = {int(year) for year in years}
    found = set(extract_years_from_path(path))
    return bool(found & requested)


def iter_filtered_csvs(
    csv_files: OrderedDict[str, CsvContent],
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
) -> Iterator[tuple[str, CsvContent]]:
    """Yield CSV files filtered by optional internal filename and year set."""

    for path, csv_content in csv_files.items():
        if target_file is not None and not path.endswith(target_file):
            continue
        if not path_matches_years(path, years):
            continue
        yield path, csv_content


def group_csvs_by_columns(
    csv_files: OrderedDict[str, CsvContent],
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
) -> OrderedDict[tuple[str, ...], list[tuple[str, list[dict[str, str | None]]]]]:
    """Group CSV files by identical column structure."""

    grouped: OrderedDict[tuple[str, ...], list[tuple[str, list[dict[str, str | None]]]]] = OrderedDict()
    for path, csv_content in iter_filtered_csvs(csv_files, target_file=target_file, years=years):
        grouped.setdefault(csv_content.columns, []).append((path, csv_content.rows))
    return grouped


def collect_column_names(
    csv_files: OrderedDict[str, CsvContent],
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
) -> OrderedDict[str, list[str]]:
    """Return all column names and the internal CSV files where they occur."""

    columns_map: OrderedDict[str, list[str]] = OrderedDict()
    for path, csv_content in iter_filtered_csvs(csv_files, target_file=target_file, years=years):
        for column in csv_content.columns:
            columns_map.setdefault(column, [])
            if path not in columns_map[column]:
                columns_map[column].append(path)
    return columns_map


def collect_unique_column_values(
    csv_files: OrderedDict[str, CsvContent],
    column: str,
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
    skip_empty_values: bool = False,
) -> set[str]:
    """Collect the unique values found for one selected column."""

    values: set[str] = set()
    for _, csv_content in iter_filtered_csvs(csv_files, target_file=target_file, years=years):
        for row in csv_content.rows:
            if column not in row:
                continue
            value = row[column]
            if value is None:
                continue
            if skip_empty_values and value == "":
                continue
            values.add(value)
    return values


def collect_grouped_value_counts(
    csv_files: OrderedDict[str, CsvContent],
    primary_field: str,
    secondary_field: str,
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
    skip_empty_values: bool = False,
) -> OrderedDict[str, OrderedDict[str, int]]:
    """Collect secondary-value counts grouped by a primary field value."""

    grouped: OrderedDict[str, Counter[str]] = OrderedDict()

    for _, csv_content in iter_filtered_csvs(csv_files, target_file=target_file, years=years):
        for row in csv_content.rows:
            if primary_field not in row or secondary_field not in row:
                continue

            primary_value = row[primary_field]
            secondary_value = row[secondary_field]

            if primary_value is None or secondary_value is None:
                continue
            if skip_empty_values and (primary_value == "" or secondary_value == ""):
                continue

            if primary_value not in grouped:
                grouped[primary_value] = Counter()
            grouped[primary_value][secondary_value] += 1

    result: OrderedDict[str, OrderedDict[str, int]] = OrderedDict()
    for primary_value in sorted(grouped, key=lambda item: item.lower()):
        counter = grouped[primary_value]
        result[primary_value] = OrderedDict(
            (secondary_value, counter[secondary_value])
            for secondary_value in sorted(counter, key=lambda item: item.lower())
        )
    return result


def collect_matching_rows(
    csv_files: OrderedDict[str, CsvContent],
    field: str,
    value: str | None = None,
    *,
    target_file: str | None = None,
    years: Iterable[int] | None = None,
) -> list[dict[str, str]]:
    """Collect rows matching one field, optionally restricted to one exact value.

    Two operating modes:

    - if `value` is provided, only rows where `field == value` are collected
      (exact match, Mode 1);
    - if `value` is None, rows are collected when `field` is present and
      non-empty (Mode 2).

    Each returned row includes an additional `__internal_csv_path` field so the
    original internal CSV source remains visible after rows from multiple files
    are merged into one output sample.
    """

    matches: list[dict[str, str]] = []

    for path, csv_content in iter_filtered_csvs(
        csv_files,
        target_file=target_file,
        years=years,
    ):
        for row in csv_content.rows:
            if field not in row:
                continue

            row_value = row[field]
            if row_value is None:
                continue

            if value is None:
                # Mode 2: collect rows where the field is present and non-empty.
                if row_value == "":
                    continue
            else:
                # Mode 1: collect rows where the field exactly matches the value.
                if row_value != value:
                    continue

            output_row = {
                key: ("" if cell_value is None else str(cell_value))
                for key, cell_value in row.items()
            }
            output_row[SOURCE_PATH_FIELD] = path
            matches.append(output_row)

    return matches


def sample_matching_rows(
    rows: list[dict[str, str]],
    *,
    max_rows: int | None = None,
    seed: int | None = None,
) -> list[dict[str, str]]:
    """Return all matching rows or a bounded random sample of them."""

    if max_rows is None:
        return rows
    if max_rows < 1:
        raise ValueError("max_rows must be at least 1 when provided")
    if len(rows) <= max_rows:
        return rows

    rng = random.Random(seed) if seed is not None else random.Random()
    return rng.sample(rows, max_rows)


def get_row_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    """Derive a stable field order for CSV export."""

    ordered: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                ordered.append(field)

    if SOURCE_PATH_FIELD not in seen:
        ordered.append(SOURCE_PATH_FIELD)

    return ordered


def render_zip_tree_report(
    *,
    zip_path: str,
    structure: list[tuple[str, str]],
    ext_counter: Counter[str],
    timestamp: str,
) -> str:
    """Render the ZIP tree report as text."""

    lines: list[str] = []
    lines.append("ZIP TREE REPORT")
    lines.append("---------------")
    lines.append(f"Generated at: {timestamp}")
    lines.append(f"Input dataset: {zip_path}")
    lines.append("")
    lines.append("File counts by extension:")
    if ext_counter:
        for ext, count in sorted(ext_counter.items(), key=lambda item: item[0]):
            lines.append(f"{ext}: {count}")
    else:
        lines.append("No files found.")
    lines.append("")
    lines.append("Archive tree:")
    if structure:
        for path, kind in structure:
            lines.append(f"{kind}: {path}")
    else:
        lines.append("No paths found.")
    return "\n".join(lines) + "\n"


def render_column_names_report(
    *,
    zip_path: str,
    columns_map: OrderedDict[str, list[str]],
    years: Iterable[int] | None,
    target_file: str | None,
    timestamp: str,
) -> str:
    """Render the column-name report as text."""

    lines: list[str] = []
    lines.append("COLUMN NAMES REPORT")
    lines.append("-------------------")
    lines.append(f"Generated at: {timestamp}")
    lines.append(f"Input dataset: {zip_path}")
    lines.append(f"Years filter: {', '.join(str(year) for year in years) if years else 'not set'}")
    lines.append(f"Restricted to file: {target_file if target_file else 'no'}")
    lines.append(f"Unique column names found: {len(columns_map)}")
    lines.append("")

    if not columns_map:
        lines.append("No column names found for the selected scope.")
        return "\n".join(lines) + "\n"

    for column in sorted(columns_map, key=lambda item: item.lower()):
        files = columns_map[column]
        lines.append(f"Column: {column}")
        lines.append(f"Found in {len(files)} file(s)")
        for path in files:
            lines.append(f"  - {path}")
        lines.append("")

    return "\n".join(lines)


def render_unique_values_report(
    *,
    zip_path: str,
    column: str,
    values: set[str],
    years: Iterable[int] | None,
    target_file: str | None,
    skip_empty_values: bool,
    timestamp: str,
) -> str:
    """Render the unique-values report as text."""

    sorted_values = sorted(values, key=lambda item: item.lower())
    lines: list[str] = []
    lines.append("UNIQUE COLUMN VALUES REPORT")
    lines.append("---------------------------")
    lines.append(f"Generated at: {timestamp}")
    lines.append(f"Input dataset: {zip_path}")
    lines.append(f"Column requested: {column}")
    lines.append(f"Years filter: {', '.join(str(year) for year in years) if years else 'not set'}")
    lines.append(f"Restricted to file: {target_file if target_file else 'no'}")
    lines.append(f"Empty strings skipped: {'yes' if skip_empty_values else 'no'}")
    lines.append(f"Unique values found: {len(sorted_values)}")
    lines.append("")

    if sorted_values:
        lines.extend(sorted_values)
    else:
        lines.append("[no values found]")

    return "\n".join(lines) + "\n"


def build_actor_json_report(
    *,
    zip_path: str,
    primary_field: str,
    secondary_field: str,
    grouped_counts: OrderedDict[str, OrderedDict[str, int]],
    years: Iterable[int] | None,
    target_file: str | None,
    skip_empty_values: bool,
    timestamp: str,
) -> dict[str, object]:
    """Build the JSON payload for the actor-oriented grouped value report."""

    return {
        "generated_at": timestamp,
        "input_dataset": zip_path,
        "primary_field": primary_field,
        "secondary_field": secondary_field,
        "years_filter": list(years) if years else None,
        "restricted_to_file": target_file,
        "skip_empty_values": skip_empty_values,
        "group_count": len(grouped_counts),
        "groups": grouped_counts,
    }


def write_text_report(report_path: str, report_text: str) -> str:
    """Write a text report to disk and return its path."""

    with open(report_path, "w", encoding=DEFAULT_ENCODING) as handle:
        handle.write(report_text)
    return report_path


def write_json_report(report_path: str, payload: dict[str, object]) -> str:
    """Write a JSON report to disk and return its path."""

    with open(report_path, "w", encoding=DEFAULT_ENCODING) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return report_path


def write_rows_csv(
    output_path: str,
    rows: list[dict[str, str]],
    *,
    fieldnames: list[str] | None = None,
) -> str:
    """Write extracted rows to CSV and return the output path."""

    final_fieldnames = fieldnames or get_row_fieldnames(rows)

    with open(output_path, "w", encoding=DEFAULT_ENCODING, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=final_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in final_fieldnames})

    return output_path