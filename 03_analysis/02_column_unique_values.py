"""Report the unique values and their occurrence counts for one selected column.

This script scans the CSV files contained in each input ZIP, including nested
ZIP archives, and returns the complete set of unique values found for a single
requested column together with how many times each value appears. It can be
restricted to one internal CSV filename and can optionally limit the inspection
to a set of years.

The output is a JSON file containing:

- the column inspected;
- the total number of values found (including duplicates);
- the number of distinct values;
- a dictionary of distinct values mapped to their occurrence counts,
  sorted from most to least frequent.

Year filtering is based on 4-digit year markers detected in internal CSV paths,
for example `raw_edition_data_for_the_year_1454.csv`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, OrderedDict
from pathlib import Path

# Resolve sampling_utils from 02_sampling regardless of where this script lives.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_sampling"))

from sampling_utils import (
    DEFAULT_ENCODING,
    DEFAULT_OUTPUT_DIR,
    build_output_path,
    current_timestamp,
    iter_filtered_csvs,
    scan_zip_archive,
)


def collect_value_counts(
    csv_files: object,
    column: str,
    *,
    target_file: str | None = None,
    years: list[int] | None = None,
    skip_empty_values: bool = False,
) -> Counter[str]:
    """Return a Counter of all values found for the requested column."""

    counter: Counter[str] = Counter()

    for _, csv_content in iter_filtered_csvs(
        csv_files,
        target_file=target_file,
        years=years,
    ):
        for row in csv_content.rows:
            value = row.get(column)
            if value is None:
                continue
            value = str(value).strip()
            if skip_empty_values and value == "":
                continue
            counter[value] += 1

    return counter


def build_payload(
    zip_path: str,
    column: str,
    counter: Counter[str],
    *,
    years: list[int] | None,
    target_file: str | None,
    skip_empty_values: bool,
    timestamp: str,
) -> dict[str, object]:
    """Assemble the JSON payload sorted by descending frequency."""

    sorted_values = OrderedDict(
        (value, count)
        for value, count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0])
        )
    )

    return {
        "generated_at": timestamp,
        "input_dataset": zip_path,
        "column": column,
        "years_filter": years,
        "restricted_to_file": target_file,
        "skip_empty_values": skip_empty_values,
        "total_value_occurrences": sum(counter.values()),
        "distinct_value_count": len(counter),
        "values": sorted_values,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report unique values and occurrence counts for one column "
            "across a ZIP dataset. Output is JSON."
        )
    )
    parser.add_argument("inputs", nargs="+", help="Path(s) to ZIP dataset(s) to inspect.")
    parser.add_argument(
        "--column",
        required=True,
        help="Name of the column whose values should be counted.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where JSON reports will be written. Default: %(default)s",
    )
    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help="Encoding used when reading CSV files inside the ZIP. Default: %(default)s",
    )
    parser.add_argument(
        "--target-file",
        default=None,
        help="Optional internal CSV filename restriction.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=None,
        help="Optional list of years used to restrict the internal CSV files considered.",
    )
    parser.add_argument(
        "--skip-empty-values",
        action="store_true",
        help="Ignore empty strings when collecting values.",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip missing input datasets instead of stopping execution.",
    )
    return parser.parse_args()


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    params["column"] = args.column
    params["target_file"] = args.target_file
    params["years"] = args.years
    params["skip_empty_values"] = args.skip_empty_values
    params["encoding"] = None if args.encoding == DEFAULT_ENCODING else args.encoding
    params["skip_missing"] = args.skip_missing
    return params


def main() -> int:
    args = parse_args()
    timestamp = current_timestamp()
    created: list[str] = []

    for index, zip_path in enumerate(args.inputs, start=1):
        if not os.path.exists(zip_path):
            message = f"Input dataset not found: {zip_path}"
            if args.skip_missing:
                print(message + " [skipped]", file=sys.stderr)
                continue
            raise FileNotFoundError(message)

        _, _, csv_files = scan_zip_archive(zip_path, encoding=args.encoding)
        counter = collect_value_counts(
            csv_files,
            args.column,
            target_file=args.target_file,
            years=args.years,
            skip_empty_values=args.skip_empty_values,
        )

        if not counter:
            print(
                f"No values found for column '{args.column}' in {zip_path}.",
                file=sys.stderr,
            )
            continue

        payload = build_payload(
            zip_path=zip_path,
            column=args.column,
            counter=counter,
            years=args.years,
            target_file=args.target_file,
            skip_empty_values=args.skip_empty_values,
            timestamp=timestamp,
        )
        report_path = build_output_path(
            output_dir=args.output_dir,
            entry_script=__file__,
            params=build_name_params(args),
            dataset_index=index if len(args.inputs) > 1 else None,
            timestamp=timestamp,
            suffix=".json",
        )
        os.makedirs(args.output_dir, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

        created.append(report_path)
        print(
            f"{report_path} "
            f"[distinct values: {payload['distinct_value_count']}, "
            f"total occurrences: {payload['total_value_occurrences']}]"
        )

    return 0 if created or args.skip_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 03_analysis/02_column_unique_values.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --column entity_type \
  --skip-empty-values \
  --output-dir 03_analysis/data

python 03_analysis/02_column_unique_values.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --column language \
  --skip-empty-values \
  --output-dir 03_analysis/data

python 03_analysis/02_column_unique_values.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --column language \
  --skip-empty-values \
  --years 1454 1455 \
  --output-dir 03_analysis/data
'''