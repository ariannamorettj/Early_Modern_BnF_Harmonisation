"""Compute the average number of distinct values per field per actor.

Reads the actor dataset from a ZIP archive, groups rows by actor URI, and for
each field computes how many distinct non-null values each actor has. It then
averages that count across all actors that have at least one value for that
field.

This measures field cardinality in the dataset: a value of 1.0 means every
actor has exactly one distinct value for that field; a value of 5.0 means
actors have on average five distinct values (typical for fields like
actor_link_exact, where one actor maps to several authority links).

Actors with no value for a given field are excluded from that field's average.
Null sentinels (NA, N/A, None, none, null, NULL, empty string) are treated as
missing values and excluded from the count.

The output is a JSON file containing:

- metadata about the run;
- per-field results sorted by descending average cardinality, each with:
  - the average number of distinct values per actor;
  - the number of actors that had at least one value for that field;
  - the total number of actors in the dataset.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

# Resolve sampling_utils from 02_sampling regardless of where this script lives.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_sampling"))

from sampling_utils import (
    DEFAULT_ENCODING,
    build_output_path,
    current_timestamp,
    iter_filtered_csvs,
    scan_zip_archive,
)

DEFAULT_OUTPUT_DIR = os.path.join("03_analysis", "data")
DEFAULT_ACTOR_FIELD = "actor"

NULL_SENTINELS = {"NA", "N/A", "None", "none", "null", "NULL", ""}


def compute_field_cardinality(
    zip_path: str,
    *,
    actor_field: str = DEFAULT_ACTOR_FIELD,
    encoding: str = DEFAULT_ENCODING,
) -> dict[str, object]:
    """Group rows by actor URI and compute average distinct values per field.

    Returns a dict mapping each field name to its average cardinality and
    coverage statistics.
    """

    _, _, csv_files = scan_zip_archive(zip_path, encoding=encoding)

    # actor_uri -> field -> set of distinct values
    actor_field_values: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    columns: tuple[str, ...] = ()

    for _, csv_content in iter_filtered_csvs(csv_files):
        if csv_content.columns:
            columns = csv_content.columns
        for row in csv_content.rows:
            actor_uri = row.get(actor_field)
            if actor_uri is None or str(actor_uri).strip() in NULL_SENTINELS:
                continue
            actor_uri = str(actor_uri).strip()

            for col in csv_content.columns:
                if col == actor_field:
                    continue
                value = row.get(col)
                if value is None:
                    continue
                value = str(value).strip()
                if value in NULL_SENTINELS:
                    continue
                actor_field_values[actor_uri][col].add(value)

    total_actors = len(actor_field_values)

    if total_actors == 0:
        return {
            "total_actors": 0,
            "fields": {},
        }

    # For each field, collect the distinct-value counts across actors.
    field_counts: dict[str, list[int]] = defaultdict(list)
    for actor_data in actor_field_values.values():
        for field, values in actor_data.items():
            field_counts[field].append(len(values))

    # Build per-field results sorted by descending average cardinality.
    fields_result = {}
    for field, counts in sorted(
        field_counts.items(),
        key=lambda item: -mean(item[1]),
    ):
        fields_result[field] = {
            "average_distinct_values_per_actor": round(mean(counts), 4),
            "actors_with_field": len(counts),
            "total_actors": total_actors,
        }

    return {
        "total_actors": total_actors,
        "fields": fields_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute the average number of distinct values per field per actor "
            "from an actor ZIP dataset."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the actor ZIP dataset.",
    )
    parser.add_argument(
        "--actor-field",
        default=DEFAULT_ACTOR_FIELD,
        help=(
            f"Column used to identify individual actors. "
            f"Default: {DEFAULT_ACTOR_FIELD}"
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


def build_name_params(args: argparse.Namespace) -> dict[str, object]:
    params = {}
    if args.actor_field != DEFAULT_ACTOR_FIELD:
        params["actor_field"] = args.actor_field
    if args.encoding != DEFAULT_ENCODING:
        params["encoding"] = args.encoding
    return params


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"Input dataset not found: {args.input}", file=sys.stderr)
        return 1

    result = compute_field_cardinality(
        args.input,
        actor_field=args.actor_field,
        encoding=args.encoding,
    )

    if result["total_actors"] == 0:
        print(
            f"No actors found in {args.input} "
            f"(column '{args.actor_field}' missing or all null).",
            file=sys.stderr,
        )
        return 1

    timestamp = current_timestamp()
    payload = {
        "generated_at": timestamp,
        "input_dataset": args.input,
        "actor_field": args.actor_field,
        **result,
    }

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
        f"[actors: {result['total_actors']}, "
        f"fields analysed: {len(result['fields'])}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


'''
python 03_analysis/04_actor_field_cardinality.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 03_analysis/data
'''