#!/usr/bin/env python3
"""
unique_values_per_field.py

Read all CSVs in `data/unified_agents/` and collect, for each selected field,
the set of **distinct non-empty values** seen across all files. Write a JSON
mapping field → sorted list of unique values to `data/unique_values_per_field/unique_values.json`.

Fields considered (if present in a file):
  - actor_birth
  - actor_country
  - actor_death
  - actor_end
  - actor_language
  - actor_start

Notes
-----
- All files are read as strings; empty/whitespace-only cells are ignored.
- Delimiter is auto-detected with pandas (sep=None, engine="python").
- Encoding attempts in order: UTF-8 with BOM, UTF-8, Latin-1.
- Sorting is alphabetical using a case-insensitive key while preserving the
  original value in the output.

Usage
-----
  python unique_values_per_field.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd
from tqdm import tqdm

INPUT_DIR = Path("data") / "unified_agents"
OUTPUT_DIR = Path("data") / "unique_values_per_field"
OUTPUT_JSON = OUTPUT_DIR / "unique_values.json"

TARGET_FIELDS: List[str] = [
    "actor_birth",
    "actor_country",
    "actor_death",
    "actor_end",
    "actor_language",
    "actor_start",
]


def read_csv_best_effort(path: Path) -> pd.DataFrame:
    """Read a CSV with autodetected delimiter and robust encoding fallbacks."""
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    last_err: Exception | None = None
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
    raise RuntimeError(f"Failed to parse {path} with common encodings. Last error: {last_err}")


def normalize(value: str) -> str:
    """Trim whitespace; return empty string for None/NaN/whitespace-only."""
    if value is None:
        return ""
    s = str(value).strip()
    return s


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize sets for each target field
    uniques: Dict[str, Set[str]] = {field: set() for field in TARGET_FIELDS}

    csv_files = sorted(INPUT_DIR.glob("*.csv"))
    if not csv_files:
        print(f"[ERR] No CSV files found in {INPUT_DIR}")
        return 1

    for csv_path in tqdm(csv_files, desc="Files", unit="file"):
        try:
            df = read_csv_best_effort(csv_path)
        except Exception as e:
            print(f"[WARN] Skipping unreadable CSV {csv_path}: {e}")
            continue

        # Build a lower→actual name map for case-insensitive matching
        lower_to_actual = {c.lower(): c for c in df.columns}

        for field in TARGET_FIELDS:
            colname = lower_to_actual.get(field.lower())
            if not colname:
                continue  # field not present in this file
            # Stream unique non-empty values into the set
            for v in df[colname].astype(str):
                nv = normalize(v)
                if nv:
                    uniques[field].add(nv)

    # Convert sets to sorted lists (alphabetically, case-insensitive sort key)
    result = {f: sorted(list(vals), key=lambda x: (x.casefold(), x)) for f, vals in uniques.items()}

    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
