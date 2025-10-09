#!/usr/bin/env python3
"""
find_entities_without_record_type.py

Identify entities (editions) that do **not** have a declared record type.

It scans CSV chunks, looking for rows where the `record_type` field is empty or
contains only separators/whitespace. If multiple editions are present in a row
(semicolon-separated), each edition is checked and collected.

Input:
  - CSVs: data/unified_dataset/unified_chunks/*.csv
    (must contain columns 'edition' and 'record_type'; values can be ';'-separated)

Output:
  - JSON: final_dataset_analysis/reports/editions_without_record_type.json
    (array of unique edition IDs with no declared type)
  - CSV:  final_dataset_analysis/reports/editions_without_record_type.csv
    (one edition ID per line)

RUN:
    python final_dataset_analysis/find_entities_without_record_type.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List, Set

import pandas as pd
from tqdm import tqdm

# Paths
CSV_DIR = Path("data/unified_dataset/unified_chunks")
OUT_DIR = Path("final_dataset_analysis/reports")
OUT_JSON = OUT_DIR / "editions_without_record_type.json"
OUT_CSV = OUT_DIR / "editions_without_record_type.csv"

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
                keep_default_na=False
            )

        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to read {path}: {last_err}")


def split_semi(value: str) -> List[str]:
    if value is None:
        return []
    return [tok.strip() for tok in str(value).split(";") if tok and tok.strip()]


def main() -> int:
    # Ensure input availability
    files = sorted(CSV_DIR.glob("*.csv"))
    if not files:
        print(f"[ERR] No CSV files in {CSV_DIR}")
        return 1

    editions_without_type: Set[str] = set()

    for csv_path in tqdm(files, desc="Files", unit="file"):
        try:
            df = read_csv_best_effort(csv_path)
        except Exception as e:
            print(f"[WARN] Skipping {csv_path}: {e}")
            continue

        # case-insensitive columns
        colmap = {c.lower(): c for c in df.columns}
        col_edition = colmap.get(COL_EDITION.lower())
        col_rtype = colmap.get(COL_RECORD_TYPE.lower())
        if not col_edition:
            print(f"[WARN] Missing '{COL_EDITION}' in {csv_path.name}; skipping file")
            continue
        if not col_rtype:
            # If record_type column is entirely missing, every edition in the file qualifies
            for ed_cell in df[col_edition].astype(str):
                for ed in split_semi(ed_cell):
                    editions_without_type.add(ed)
            continue

        # Row-wise examination
        for ed_cell, rt_cell in zip(df[col_edition].astype(str), df[col_rtype].astype(str)):
            editions = split_semi(ed_cell)
            if not editions:
                continue

            rtypes = split_semi(rt_cell)
            if len(rtypes) == 0:
                for ed in editions:
                    editions_without_type.add(ed)

    # Write outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON array
    OUT_JSON.write_text(
        json.dumps(sorted(editions_without_type), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # CSV (one per line)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["edition"])  # header
        for ed in sorted(editions_without_type):
            writer.writerow([ed])

    print(
        f"[OK] Found {len(editions_without_type)} editions without a declared record_type.\n"
        f"     JSON: {OUT_JSON}\n"
        f"     CSV : {OUT_CSV}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
