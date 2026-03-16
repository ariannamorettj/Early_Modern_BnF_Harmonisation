#!/usr/bin/env python3
"""
actors_one_to_may_fields_analysis.py

Goal
----
For each JSON produced in `data/actors_matched_ids/` (one per agent role),
compute, **for every field**, the average number of distinct values observed
per actor (i.e., the average length of the list of [value, count] tuples).

Example (per your spec):
  actor_start: 1
  actor_link_exact: 5

Outputs
-------
- One JSON summary per input file, written to
  `final_dataset_analysis/reports/actors_field_cardinality_<stem>.json`, where
  <stem> is the input filename without extension (e.g., actors_aut).
- One overall JSON with the averages aggregated across **all** five files:
  `final_dataset_analysis/reports/actors_field_cardinality_ALL.json`.

Notes
-----
- The input JSON structure is:
    {
      "<actor_key>": {
        "<field>": [["<value>", <count>], ...],
        ...
      },
      ...
    }
  This script does **not** re-count occurrences; it simply takes the length of
  the list for each field (per actor) and averages over actors.
- Actors that **do not** contain a given field are **excluded** from that field's
  average (i.e., the denominator is the number of actors that have that field).
- Empty strings should not appear here because input generation already filtered
  them out. If present, they are ignored upstream.

Usage
-----
  python actors_one_to_may_fields_analysis.py \
    --in-dir data/actors_matched_ids \
    --out-dir data/field_to_values_average
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, List

from tqdm import tqdm


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def per_file_field_averages(data: dict) -> Dict[str, float]:
    """Compute average tuple-count per field for a single role JSON.

    For each field, count how many distinct values (tuples) each actor has,
    then average across actors that have that field.
    """
    # field -> list of counts observed per actor
    per_field_counts: Dict[str, List[int]] = defaultdict(list)

    for actor_payload in data.values():
        if not isinstance(actor_payload, dict):
            continue
        for field, tuples_list in actor_payload.items():
            if not isinstance(tuples_list, list):
                continue
            per_field_counts[field].append(len(tuples_list))

    # Average per field (only over actors that had the field)
    return {field: float(mean(counts)) for field, counts in per_field_counts.items() if counts}


def write_json(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute average #values per field for actors JSONs.")
    ap.add_argument("--in-dir", type=Path, default=Path("data/actors_matched_ids"), help="Input folder with actors_*.json files.")
    ap.add_argument("--out-dir", type=Path, default=Path("final_dataset_analysis/reports"), help="Output folder for summaries.")
    args = ap.parse_args()

    inputs = sorted(args.in_dir.glob("*.json"))
    if not inputs:
        print(f"[ERR] No JSON files in {args.in_dir}")
        return 1

    # Collect per-file results and also aggregate for an overall average
    overall_field_values: Dict[str, List[float]] = defaultdict(list)

    for in_path in tqdm(inputs, desc="Files", unit="file"):
        data = load_json(in_path)
        averages = per_file_field_averages(data)

        # Save per-file summary
        out_name = f"actors_field_cardinality_{in_path.stem}.json"
        out_path = args.out_dir / out_name
        write_json(averages, out_path)
        print(f"[OK] Wrote {out_path}")

        # Accumulate into overall buckets (we average the per-actor means equally per file)
        for field, avg in averages.items():
            overall_field_values[field].append(avg)

    # Compute overall averages across files (mean of the per-file means)
    overall = {field: float(mean(vals)) for field, vals in overall_field_values.items() if vals}
    write_json(overall, args.out_dir / "actors_field_cardinality_ALL.json")
    print(f"[OK] Wrote {args.out_dir / 'actors_field_cardinality_ALL.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
