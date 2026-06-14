"""Dataset Profiler: Compute comprehensive field metrics across a ZIP dataset.

For each field in a ZIP dataset containing CSV files, this script calculates:
- The total number of rows (to compute fill rates).
- The total number of non-empty values.
- The number of unique values.
- The percentage of presence (fill rate).
- The top 10 most used values.

Null values are identified using standard sentinels (NA, N/A, None, null, etc.).
Results are written as a timestamped JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, OrderedDict
from pathlib import Path

# Resolve sampling_utils from 02_sampling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_sampling"))

from sampling_utils import (
    DEFAULT_ENCODING,
    build_output_path,
    current_timestamp,
    iter_filtered_csvs,
    scan_zip_archive,
)

DEFAULT_OUTPUT_DIR = os.path.join("03_analysis", "data")
NULL_SENTINELS = {"NA", "N/A", "None", "none", "null", "NULL", ""}


def profile_dataset(
    zip_path: str,
    *,
    encoding: str = DEFAULT_ENCODING,
    target_file: str | None = None,
    years: list[int] | None = None,
) -> dict[str, object]:
    """Scan all matching CSVs in the ZIP and compute metrics for each field."""
    _, _, csv_files = scan_zip_archive(zip_path, encoding=encoding)

    # Track total rows seen across all matched files
    total_rows = 0
    # field_name -> Counter of values
    field_counters: dict[str, Counter[str]] = {}

    for path, csv_content in iter_filtered_csvs(
        csv_files, target_file=target_file, years=years
    ):
        file_rows_count = len(csv_content.rows)
        total_rows += file_rows_count

        for row in csv_content.rows:
            for col in csv_content.columns:
                val = row.get(col)
                if val is None:
                    continue
                val_str = str(val).strip()
                
                # Check for null sentinels
                if val_str in NULL_SENTINELS:
                    continue

                if col not in field_counters:
                    field_counters[col] = Counter()
                field_counters[col][val_str] += 1

    # Compile the final statistics for each field
    fields_profile = OrderedDict()

    # Sort fields alphabetically for deterministic output
    for col in sorted(field_counters.keys(), key=lambda x: x.lower()):
        counter = field_counters[col]
        total_values = sum(counter.values())
        unique_values = len(counter)
        fill_rate = round((total_values / total_rows) * 100, 4) if total_rows > 0 else 0.0

        # Extract the top 10 most common values
        top_10 = [
            {"value": value, "count": count}
            for value, count in counter.most_common(10)
        ]

        fields_profile[col] = {
            "total_values": total_values,
            "unique_values": unique_values,
            "fill_rate_percent": fill_rate,
            "top_10_values": top_10,
        }

    return {
        "total_rows": total_rows,
        "fields": fields_profile,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute comprehensive field metrics (fill rate, unique count, top 10 values) across a ZIP dataset."
    )
    parser.add_argument("inputs", nargs="+", help="Path(s) to ZIP dataset(s) to profile.")
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
        "--skip-missing",
        action="store_true",
        help="Skip missing input datasets instead of stopping execution.",
    )
    return parser.parse_args()


def build_name_params(zip_path: str, args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    zip_name = os.path.basename(zip_path).lower()
    if "actor" in zip_name:
        params["dataset"] = "ACTOR"
    elif "edition" in zip_name or "bib" in zip_name:
        params["dataset"] = "BIB_RES"
    else:
        params["dataset"] = os.path.splitext(zip_name)[0].upper()

    params["target_file"] = args.target_file
    params["years"] = args.years
    params["encoding"] = None if args.encoding == DEFAULT_ENCODING else args.encoding
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

        print(f"Profiling dataset: {zip_path}...")
        profile = profile_dataset(
            zip_path,
            encoding=args.encoding,
            target_file=args.target_file,
            years=args.years,
        )

        payload = {
            "generated_at": timestamp,
            "input_dataset": zip_path,
            "years_filter": args.years,
            "restricted_to_file": args.target_file,
            **profile,
        }

        output_path = build_output_path(
            output_dir=args.output_dir,
            entry_script=__file__,
            params=build_name_params(zip_path, args),
            dataset_index=index if len(args.inputs) > 1 else None,
            timestamp=timestamp,
            suffix=".json",
        )

        abs_output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_output_path), exist_ok=True)
        with open(abs_output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

        created.append(abs_output_path)
        print(
            f"Successfully profiled {zip_path} -> {abs_output_path} "
            f"[total rows: {profile['total_rows']}, fields profiled: {len(profile['fields'])}]"
        )

    return 0 if created or args.skip_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 03_analysis/05_dataset_profiler.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 03_analysis/data

python 03_analysis/05_dataset_profiler.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --output-dir 03_analysis/data
'''
