"""Generate a tree-style structural report for one or more ZIP datasets.

This script is the first inspection step of the reorganised `02_sampling`
module. It traverses each input ZIP recursively, including nested ZIP files,
and writes a text report containing file counts by extension together with the
full internal archive tree.

The output filename includes the entry script name, relevant runtime
parameters, an optional dataset index when multiple ZIP files are processed in
one run, and a timestamp. The input dataset path is kept as a runtime parameter
but excluded from the output filename.
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
    current_timestamp,
    render_zip_tree_report,
    scan_zip_archive,
    write_text_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a tree-style structural report for one or more ZIP datasets."
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
        "--skip-missing",
        action="store_true",
        help="Skip missing input datasets instead of stopping execution.",
    )
    return parser.parse_args()


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
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

        structure, ext_counter, _ = scan_zip_archive(zip_path, encoding=args.encoding)
        report_text = render_zip_tree_report(
            zip_path=zip_path,
            structure=structure,
            ext_counter=ext_counter,
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
''' python 02_sampling/01_zip_tree.py \
01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip
'''
# Sample run with multiple ZIP inputs:
''' python 02_sampling/01_zip_tree.py \
01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
--output-dir 02_sampling/data \
--skip-missing
'''