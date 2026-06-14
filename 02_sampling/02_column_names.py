"""Report all column names found across one or more ZIP datasets.

This script scans CSV files contained in each input ZIP, including CSV files
located inside nested ZIP archives. It returns the complete set of discovered
column names and, for each column, the internal CSV files where that column is
present.

An optional year filter can be applied. Year filtering is based on 4-digit year
markers detected in internal CSV paths, such as
`raw_edition_data_for_the_year_1454.csv`.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict

from sampling_utils import (
    DEFAULT_ENCODING,
    DEFAULT_OUTPUT_DIR,
    build_output_path,
    collect_column_names,
    current_timestamp,
    render_column_names_report,
    scan_zip_archive,
    write_text_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report all column names found across one or more ZIP datasets."
    )
    parser.add_argument("inputs", nargs="+", help="Path(s) to ZIP dataset(s) to inspect.")
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


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    params["target_file"] = args.target_file
    params["years"] = args.years
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
        columns_map = collect_column_names(
            csv_files,
            target_file=args.target_file,
            years=args.years,
        )
        report_text = render_column_names_report(
            zip_path=zip_path,
            columns_map=columns_map,
            years=args.years,
            target_file=args.target_file,
            timestamp=timestamp,
        )
        report_path = build_output_path(
            output_dir=args.output_dir,
            entry_script=__file__,
            params=build_name_params(args),
            dataset_index=index if len(args.inputs) > 1 else None,
            timestamp=timestamp,
            suffix=".txt",
        )
        write_text_report(report_path, report_text)
        created.append(report_path)
        print(report_path)

    return 0 if created or args.skip_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())


# Sample run:
# python 02_sampling/02_column_names.py \
#   01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip
#
# Sample run restricted to specific years:
# python 02_sampling/02_column_names.py \
#   01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
#   --years 1454 1455 1456
#
# Sample run restricted to one internal CSV file:
# python 02_sampling/02_column_names.py \
#   01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
#   --target-file raw_edition_data_for_the_year_1454.csv
#
# Sample run with multiple ZIP inputs:
'''python 02_sampling/02_column_names.py \
01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
--output-dir 02_sampling/data \
--skip-missing'''