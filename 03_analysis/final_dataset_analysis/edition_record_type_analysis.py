#!/usr/bin/env python3
"""
edition_record_type_analysis.py

Build a report mapping:
  edition -> [ {record_type_uri: label}, ... ]
for those rows where *all* record_type values (split on ';') are present among
the keys of `final_dataset_analysis/reports/bnf_ark_titles.json`.

Input:
  - JSON whitelist: final_dataset_analysis/reports/bnf_ark_titles.json
    (keys = record_type URIs to accept; values = human labels)
  - CSVs: data/unified_dataset/unified_chunks/*.csv
    (must contain columns 'edition' and 'record_type'; values can be ';'-separated)

Output:
  - JSON: final_dataset_analysis/reports/edition_to_allowed_record_types.json

RUN:
    python final_dataset_analysis/edition_record_type_analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd
from tqdm import tqdm

# Paths
CSV_DIR = Path("data/unified_dataset/unified_chunks")
TITLES_JSON = Path("final_dataset_analysis/reports/bnf_ark_titles.json")
OUT_JSON = Path("final_dataset_analysis/reports/edition_to_allowed_record_types.json")

# Columns
COL_EDITION = "edition"
COL_RECORD_TYPE = "record_type"

def read_csv_best_effort(path: Path) -> pd.DataFrame:
    """Read CSV with autodetected delimiter and robust encodings."""
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

def split_semi(value: str) -> List[str]:
    if value is None:
        return []
    return [tok.strip() for tok in str(value).split(";") if tok and tok.strip()]

def main() -> int:
    # Load whitelist (and labels) from bnf_ark_titles.json
    if not TITLES_JSON.exists():
        print(f"[ERR] Missing whitelist file: {TITLES_JSON}")
        return 1
    titles_map: Dict[str, str] = json.loads(TITLES_JSON.read_text(encoding="utf-8"))
    whitelist: Set[str] = set(titles_map.keys())
    if not whitelist:
        print(f"[ERR] Whitelist is empty in {TITLES_JSON}")
        return 1

    # Iterate CSVs
    files = sorted(CSV_DIR.glob("*.csv"))
    if not files:
        print(f"[ERR] No CSV files in {CSV_DIR}")
        return 1

    # edition -> list of {type_uri: label}
    out_map: Dict[str, List[Dict[str, str]]] = {}

    for csv_path in tqdm(files, desc="Files", unit="file"):
        try:
            df = read_csv_best_effort(csv_path)
        except Exception as e:
            print(f"[WARN] Skipping {csv_path}: {e}")
            continue

        # case-insensitive column resolution
        colmap = {c.lower(): c for c in df.columns}
        col_edition = colmap.get(COL_EDITION.lower())
        col_rtype = colmap.get(COL_RECORD_TYPE.lower())
        if not col_edition or not col_rtype:
            continue

        # Row-wise filtering and mapping
        for ed_cell, rt_cell in zip(df[col_edition].astype(str), df[col_rtype].astype(str)):
            editions = [e for e in split_semi(ed_cell) if e]
            if not editions:
                continue

            rtypes = [t for t in split_semi(rt_cell) if t]
            if not rtypes:
                continue

            # Keep this row ONLY if *all* record types are in the whitelist
            if not set(rtypes).issubset(whitelist):
                continue

            labeled = [{t: titles_map.get(t, t)} for t in rtypes]

            # Assign allowed types (with labels) to each edition in the row
            for ed in editions:
                # If same edition appears multiple times, keep the first mapping encountered
                if ed not in out_map:
                    out_map[ed] = labeled

    # Save JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {OUT_JSON} with {len(out_map)} editions.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
