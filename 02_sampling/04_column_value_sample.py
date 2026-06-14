"""Sample well-distributed values for one or more columns from a ZIP dataset.

This script scans CSV files inside input ZIP archives and collects unique 
non-empty values for either a specific column or all discovered columns.
It then selects a requested number of values that are evenly distributed 
across the sorted set of unique values, providing a structural sample 
of what the column contents look like.

When a specific column is requested, it generates a single output report.
When no column is requested, it generates a separate output report for 
each column discovered in the input dataset.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict
from typing import Iterable

from sampling_utils import (
    DEFAULT_ENCODING,
    DEFAULT_OUTPUT_DIR,
    build_output_path,
    collect_column_names,
    collect_unique_column_values,
    current_timestamp,
    scan_zip_archive,
    write_text_report,
)


def sample_well_distributed_values(values: set[str], n_values: int) -> list[str]:
    """Return an evenly distributed sample of unique values."""
    if not values:
        return []
    
    sorted_values = sorted(values, key=lambda item: item.lower())
    n = len(sorted_values)
    
    if n <= n_values:
        return sorted_values
        
    step = n / n_values
    return [sorted_values[int(i * step)] for i in range(n_values)]


def render_sample_report(
    *,
    zip_path: str,
    column: str,
    sampled_values: list[str],
    total_unique: int,
    years: Iterable[int] | None,
    target_file: str | None,
    timestamp: str,
) -> str:
    """Render the sampled values report as text."""
    lines: list[str] = []
    lines.append("COLUMN VALUE SAMPLE REPORT")
    lines.append("--------------------------")
    lines.append(f"Generated at: {timestamp}")
    lines.append(f"Input dataset: {zip_path}")
    lines.append(f"Column requested: {column}")
    lines.append(f"Years filter: {', '.join(str(year) for year in years) if years else 'not set'}")
    lines.append(f"Restricted to file: {target_file if target_file else 'no'}")
    lines.append(f"Total unique non-empty values found: {total_unique}")
    lines.append(f"Sampled values count: {len(sampled_values)}")
    lines.append("")

    if sampled_values:
        for val in sampled_values:
            lines.append(val)
    else:
        lines.append("[no values found]")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample well-distributed values for a given column (or all columns)."
    )
    parser.add_argument(
        "inputs", 
        nargs="+", 
        help="Path(s) to ZIP dataset(s) to inspect."
    )
    parser.add_argument(
        "--column",
        default=None,
        help="Specific column to sample. If not provided, generates a sample for every column found.",
    )
    parser.add_argument(
        "--n-values",
        type=int,
        default=10,
        help="Number of well-distributed values to sample per column. Default: 10",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where reports will be written. Default: %(default)s",
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


def build_name_params(args: argparse.Namespace, column: str, zip_path: str) -> OrderedDict[str, object]:
    params = OrderedDict()
    dataset_name = "ACTOR" if "actor" in zip_path.lower() else "BIB_RES"
    params[f"column_{dataset_name}"] = column
    params["n_values"] = args.n_values
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

        _, _, csv_files = scan_zip_archive(zip_path, encoding=args.encoding)

        # Determine which columns to process
        if args.column:
            target_columns = [args.column]
        else:
            columns_map = collect_column_names(
                csv_files,
                target_file=args.target_file,
                years=args.years,
            )
            target_columns = list(columns_map.keys())
            if not target_columns:
                print(f"No columns found in {zip_path} matching criteria.", file=sys.stderr)
                continue

        dataset_index = index if len(args.inputs) > 1 else None

        for column in target_columns:
            unique_values = collect_unique_column_values(
                csv_files,
                column=column,
                target_file=args.target_file,
                years=args.years,
                skip_empty_values=True,
            )
            
            sampled_values = sample_well_distributed_values(unique_values, args.n_values)
            
            report_text = render_sample_report(
                zip_path=zip_path,
                column=column,
                sampled_values=sampled_values,
                total_unique=len(unique_values),
                years=args.years,
                target_file=args.target_file,
                timestamp=timestamp,
            )
            
            report_path = build_output_path(
                output_dir=args.output_dir,
                entry_script=__file__,
                params=build_name_params(args, column, zip_path),
                dataset_index=dataset_index,
                timestamp=timestamp,
                suffix=".txt",
            )
            
            write_text_report(report_path, report_text)
            created.append(report_path)
            print(report_path)

    return 0 if created or args.skip_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ==============================================================================
# SAMPLE RUNS
# ==============================================================================
# 
# Esempio 1: Un file per ciascuna colonna trovata (parametro --column NON specificato)
# Crea automaticamente un file txt per ogni singola colonna presente nel dataset
# python 02_sampling/04_column_value_sample.py \
#   01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
#   --n-values 15
#
# Esempio 2: Singola colonna specificata (parametro --column specificato)
# Estrae un campione ben distribuito solo per la colonna richiesta
# python 02_sampling/04_column_value_sample.py \
#   01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
#   --column "actor_name" \
#   --n-values 20
#
# Esempio 3: Tutte le colonne per il dataset degli attori
# Estrae un file di sample per ciascuna colonna presente nel dataset degli attori
# python 02_sampling/04_column_value_sample.py \
#   01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
#   --n-values 15


#### CHIAMATE COMPLETE
'''
python 02_sampling/04_column_value_sample.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --n-values 150
'''

'''
python 02_sampling/04_column_value_sample.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --n-values 150
'''