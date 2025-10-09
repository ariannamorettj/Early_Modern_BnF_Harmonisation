#!/usr/bin/env python3
"""
final_dataset_analysis/counting_types.py

Scan all CSVs in `data/unified_dataset/unified_chunks/`, split the `record_type`
field on `;`, and produce:

1) record_type_counts.json
   - Keys: individual record_type values (after splitting and trimming)
   - Values: total number of occurrences across all rows/files

2) record_type_entity_cardinality.json
   - Counts how many rows have 0, 1, 2, ... N record_type values (after splitting & de-dup)
     {
       "entities_with_0_types": X,
       "entities_with_1_type": Y,
       "entities_with_2_types": Z,
       ...
     }

Notes
-----
- Empty/whitespace-only tokens are ignored.
- Within a single row, duplicate types are de-duplicated for the per-entity
  cardinality count; for the global counts we still count each distinct type
  once per row (i.e., duplicates within the same row are ignored to avoid
  inflating counts due to repeated tokens).
- CSV delimiter is auto-detected, encoding tried as UTF-8 with/without BOM,
  then Latin-1.

Usage
-----
  python final_dataset_analysis/counting_types.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Set

import pandas as pd
from tqdm import tqdm

INPUT_DIR = Path("data") / "unified_dataset" / "unified_chunks"
OUTPUT_DIR = Path("final_dataset_analysis") / "reports"

TARGET_COLUMN = "record_type"


def read_csv_best_effort(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(
                str(path),
                sep=None,
                engine="python",
                dtype=str,
                encoding=enc,
                keep_default_na=False,
                na_values=None,
            )
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to read {path}: {last_err}")


def split_types(value: str) -> List[str]:
    if value is None:
        return []
    tokens = [tok.strip() for tok in str(value).split(";")]
    return [t for t in tokens if t]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    type_counter: Counter[str] = Counter()
    entity_cardinality_counts: defaultdict[int, int] = defaultdict(int)

    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        print(f"[ERR] No CSV files in {INPUT_DIR}")
        return 1

    for csv_path in tqdm(files, desc="Files", unit="file"):
        try:
            df = read_csv_best_effort(csv_path)
        except Exception as e:
            print(f"[WARN] Skipping {csv_path}: {e}")
            continue

        colmap = {c.lower(): c for c in df.columns}
        col = colmap.get(TARGET_COLUMN.lower())
        if not col:
            continue

        for raw in df[col].astype(str):
            types = split_types(raw)
            unique_per_row: Set[str] = set(types)

            # Count cardinalities
            entity_cardinality_counts[len(unique_per_row)] += 1

            # Count types globally
            for t in unique_per_row:
                type_counter[t] += 1

    # Write outputs
    (OUTPUT_DIR / "record_type_counts.json").write_text(
        json.dumps(dict(type_counter), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (OUTPUT_DIR / "record_type_entity_cardinality.json").write_text(
        json.dumps({f"entities_with_{k}_types": v for k, v in sorted(entity_cardinality_counts.items())}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"[OK] Wrote {(OUTPUT_DIR / 'record_type_counts.json')}")
    print(f"[OK] Wrote {(OUTPUT_DIR / 'record_type_entity_cardinality.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
