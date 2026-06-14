"""Aggregate distinct values of one field for all rows matching a given name.

Given a ZIP dataset, a name value, and a target field, this script collects
every row where the name field matches the requested name, then counts how many
times each distinct value of the target field appears across those rows.

The result is written as a JSON file containing:

- the name field used for filtering;
- the name value that was searched;
- the target field whose values were aggregated;
- the total number of matching rows;
- a dictionary of distinct values mapped to their occurrence counts,
  sorted from most to least frequent.

Designed primarily for actor data, but works on any CSV-inside-ZIP dataset
that has the requested columns.
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

DEFAULT_NAME_FIELD = "actor_last_name"


def aggregate_field_values_for_name(
    zip_path: str,
    name_value: str,
    target_field: str,
    *,
    name_field: str = DEFAULT_NAME_FIELD,
    encoding: str = DEFAULT_ENCODING,
) -> dict[str, object]:
    """Return aggregated value counts for `target_field` filtered by `name_field == name_value`.

    Rows where `target_field` is absent, None, or empty are silently skipped
    for the value count, but still contribute to `total_matching_rows`.
    """

    _, _, csv_files = scan_zip_archive(zip_path, encoding=encoding)

    total_matching = 0
    counter: Counter[str] = Counter()

    for _, csv_content in iter_filtered_csvs(csv_files):
        for row in csv_content.rows:
            # Filter by name field.
            row_name = row.get(name_field)
            if row_name is None or row_name != name_value:
                continue

            total_matching += 1

            # Aggregate target field value.
            raw_value = row.get(target_field)
            if raw_value is None or str(raw_value).strip() == "":
                continue
            counter[str(raw_value)] += 1

    # Sort by descending frequency, then alphabetically for ties.
    sorted_values = OrderedDict(
        (value, count)
        for value, count in sorted(
            counter.items(), key=lambda item: (-item[1], item[0])
        )
    )

    return {
        "name_field": name_field,
        "name_value": name_value,
        "target_field": target_field,
        "total_matching_rows": total_matching,
        "distinct_value_count": len(sorted_values),
        "values": sorted_values,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate distinct values of one field for all rows matching "
            "a given actor name."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the ZIP dataset to inspect.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Name value to search for (matched against --name-field).",
    )
    parser.add_argument(
        "--field",
        required=True,
        help="Target field whose distinct values are aggregated.",
    )
    parser.add_argument(
        "--name-field",
        default=DEFAULT_NAME_FIELD,
        help=(
            f"Column used to match the actor name. Default: {DEFAULT_NAME_FIELD}. "
            "Other candidates: actor_name, actor_first_name."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the output JSON will be written. Default: %(default)s",
    )
    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help="Encoding used when reading CSV files inside the ZIP. Default: %(default)s",
    )
    return parser.parse_args()


def build_name_params(args: argparse.Namespace) -> OrderedDict[str, object]:
    params = OrderedDict()
    params["name"] = args.name
    params["field"] = args.field
    if args.name_field != DEFAULT_NAME_FIELD:
        params["name_field"] = args.name_field
    params["encoding"] = None if args.encoding == DEFAULT_ENCODING else args.encoding
    return params


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"Input dataset not found: {args.input}", file=sys.stderr)
        return 1

    payload = aggregate_field_values_for_name(
        args.input,
        name_value=args.name,
        target_field=args.field,
        name_field=args.name_field,
        encoding=args.encoding,
    )

    if payload["total_matching_rows"] == 0:
        print(
            f"No rows found in {args.input} where "
            f"'{args.name_field}' == '{args.name}'.",
            file=sys.stderr,
        )
        return 1

    timestamp = current_timestamp()
    output_path = build_output_path(
        output_dir=args.output_dir,
        entry_script=__file__,
        params=build_name_params(args),
        timestamp=timestamp,
        suffix=".json",
    )

    os.makedirs(args.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(
        f"{output_path} "
        f"[matching rows: {payload['total_matching_rows']}, "
        f"distinct values: {payload['distinct_value_count']}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 03_analysis/01_field_values.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --first_name "Nicolas" \
  --field actor_link_exact \
  --output-dir 03_analysis/data

python 03_analysis/01_field_values.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --name "Thomas d'Aquin" \
  --field actor_link_exact \
  --output-dir 03_analysis/data

python 03_analysis/01_field_values.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --name "Thomas d'Aquin" \
  --field entity_type \
  --name-field actor_name \
  --output-dir 03_analysis/data
'''