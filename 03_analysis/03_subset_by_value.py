"""Extract all rows matching a field=value condition from a ZIP dataset.

Given a ZIP dataset, a field name, and an exact value, this script collects
every row where that field matches that value and writes them to a CSV file.

Unlike the sampling script in 02_sampling, no row limit or random sampling is
applied: all matching rows are always written. The output CSV includes an
additional `__internal_csv_path` column to preserve the provenance of each row
inside the ZIP archive.

If no matching rows are found, a diagnostic message is printed to standard
error and no output file is written.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict
from pathlib import Path

# Resolve sampling_utils from 02_sampling regardless of where this script lives.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_sampling"))

from sampling_utils import (
    DEFAULT_ENCODING,
    DEFAULT_OUTPUT_DIR,
    build_output_path,
    collect_matching_rows,
    current_timestamp,
    scan_zip_archive,
    write_rows_csv,
)

DEFAULT_OUTPUT_DIR = os.path.join("03_analysis", "data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract all rows matching a field=value condition from a ZIP dataset. "
            "All matching rows are written with no row limit."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the ZIP dataset to inspect.",
    )
    parser.add_argument(
        "--field",
        required=True,
        help="Column name used to filter rows.",
    )
    parser.add_argument(
        "--value",
        required=True,
        help="Exact value that the selected field must match.",
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
    return parser.parse_args()


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    params["field"] = args.field
    params["value"] = args.value
    params["target_file"] = args.target_file
    params["years"] = args.years
    params["encoding"] = None if args.encoding == DEFAULT_ENCODING else args.encoding
    return params


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"Input dataset not found: {args.input}", file=sys.stderr)
        return 1

    _, _, csv_files = scan_zip_archive(args.input, encoding=args.encoding)

    matching_rows = collect_matching_rows(
        csv_files,
        field=args.field,
        value=args.value,
        target_file=args.target_file,
        years=args.years,
    )

    if not matching_rows:
        print(
            f"No rows found in {args.input} "
            f"where '{args.field}' == '{args.value}'.",
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

    os.makedirs(args.output_dir, exist_ok=True)
    write_rows_csv(output_path, matching_rows)
    print(f"{output_path} [rows written: {len(matching_rows)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 03_analysis/03_subset_by_value.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --field language \
  --value "<http://id.loc.gov/vocabulary/iso639-2/syr>" \
  --output-dir 03_analysis/data

python 03_analysis/03_subset_by_value.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --field entity_type \
  --value "<http://xmlns.com/foaf/0.1/Person>" \
  --output-dir 03_analysis/data

python 03_analysis/03_subset_by_value.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --field language \
  --value "<http://id.loc.gov/vocabulary/iso639-2/lat>" \
  --years 1454 1455 1456 \
  --output-dir 03_analysis/data
'''