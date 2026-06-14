"""Extract the first N best-populated rows from a ZIP dataset.

Scans CSV files inside one ZIP archive (including nested ZIP files) and
collects the first rows with the fewest missing or null values. The strategy
is iterative:

1. First attempt: collect rows where every field is non-null (max_missing=0).
2. If fewer than n_rows are found, retry allowing 1 null field per row.
3. Continue increasing the tolerance by 1 at each attempt until either
   n_rows rows are collected or every field is allowed to be null.

At each attempt the archive is scanned from the beginning so that the best
rows (fewest missing fields) are always preferred. The attempt that
succeeded is reported in the console output.

The output is a CSV file written to the output directory, with an additional
`__internal_csv_path` column that records which internal CSV file each row
came from.

Null values are detected as: None, empty string after strip, or any of the
literal null sentinels used in the BnF CSVs ("NA", "N/A", "None", "none",
"null", "NULL").
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict

from sampling_utils import (
    DEFAULT_ENCODING,
    DEFAULT_OUTPUT_DIR,
    SOURCE_PATH_FIELD,
    build_output_path,
    current_timestamp,
    iter_filtered_csvs,
    scan_zip_archive,
    write_rows_csv,
)

DEFAULT_N_ROWS = 10

NULL_SENTINELS = {"NA", "N/A", "None", "none", "null", "NULL", ""}


def count_null_fields(row: dict, columns: tuple[str, ...]) -> int:
    """Return the number of fields that are null or a null sentinel."""

    count = 0
    for col in columns:
        value = row.get(col)
        if value is None or str(value).strip() in NULL_SENTINELS:
            count += 1
    return count


def collect_rows_with_tolerance(
    csv_files: object,
    *,
    n_rows: int,
    max_missing: int,
) -> list[dict[str, str]]:
    """Collect up to n_rows rows that have at most max_missing null fields."""

    collected: list[dict[str, str]] = []

    for path, csv_content in iter_filtered_csvs(csv_files):
        if not csv_content.columns:
            continue

        for row in csv_content.rows:
            if count_null_fields(row, csv_content.columns) > max_missing:
                continue

            output_row = {
                col: ("" if row.get(col) is None else str(row[col]))
                for col in csv_content.columns
            }
            output_row[SOURCE_PATH_FIELD] = path
            collected.append(output_row)

            if len(collected) >= n_rows:
                return collected

    return collected


def collect_best_rows(
    zip_path: str,
    *,
    n_rows: int = DEFAULT_N_ROWS,
    encoding: str = DEFAULT_ENCODING,
) -> tuple[list[dict[str, str]], int]:
    """Return the first n_rows best-populated rows and the tolerance used.

    Iterates from max_missing=0 upward until enough rows are found.
    Returns a tuple of (rows, max_missing_used).
    """

    _, _, csv_files = scan_zip_archive(zip_path, encoding=encoding)

    # Determine total number of columns from the first CSV found.
    total_columns = 0
    for _, csv_content in iter_filtered_csvs(csv_files):
        if csv_content.columns:
            total_columns = len(csv_content.columns)
            break

    for max_missing in range(total_columns + 1):
        rows = collect_rows_with_tolerance(
            csv_files,
            n_rows=n_rows,
            max_missing=max_missing,
        )
        if len(rows) >= n_rows:
            return rows, max_missing
        if rows and max_missing == total_columns:
            # Exhausted all tolerances; return whatever was found.
            return rows, max_missing

    return [], 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract the first N best-populated rows from a ZIP dataset "
            "for quick structural inspection. Uses an iterative fallback "
            "strategy that progressively relaxes the null-field tolerance."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the ZIP dataset to inspect.",
    )
    parser.add_argument(
        "--n-rows",
        type=int,
        default=DEFAULT_N_ROWS,
        help=f"Number of rows to collect. Default: {DEFAULT_N_ROWS}",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the output CSV will be written. Default: %(default)s",
    )
    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help="Encoding used when reading CSV files inside the ZIP. Default: %(default)s",
    )
    return parser.parse_args()


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    params["n_rows"] = args.n_rows
    params["encoding"] = None if args.encoding == DEFAULT_ENCODING else args.encoding
    return params


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"Input dataset not found: {args.input}", file=sys.stderr)
        return 1

    rows, tolerance_used = collect_best_rows(
        args.input,
        n_rows=args.n_rows,
        encoding=args.encoding,
    )

    if not rows:
        print(
            f"No rows found in {args.input}.",
            file=sys.stderr,
        )
        return 1

    timestamp = current_timestamp()
    output_path = build_output_path(
        output_dir=args.output_dir,
        entry_script=__file__,
        params=build_name_params(args),
        timestamp=timestamp,
        suffix=".csv",
    )

    write_rows_csv(output_path, rows)
    print(
        f"{output_path} "
        f"[rows written: {len(rows)}, null fields allowed per row: {tolerance_used}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --output-dir 02_sampling/data

python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --output-dir 02_sampling/data

python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 02_sampling/data
'''