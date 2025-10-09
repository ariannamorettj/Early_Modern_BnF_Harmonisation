#!/usr/bin/env python3
"""
agents_main.py

Unify agent CSVs by role (aut, edt, ill, pbl, trl) across Early Modern
period year folders, add a "year" column, and save five consolidated
datasets under data/unified_agents.

Directory layout expected (example):

  data/
    results_agents/
      1540/
        aut/
          authors_1540.csv
          readme.txt
        edt/
          editors-1540.csv
        ill/
        pbl/
        trl/
        notes.txt
      1541/
        aut/
          authors_1541_partA.csv
          authors_1541_partB.csv
        ...

This script will:
  1) Scan each year directory under data/results_agents.
  2) For each role directory (aut, edt, ill, pbl, trl), read ALL *.csv files
     found directly inside it (other file types are ignored).
  3) Concatenate rows per role across years, taking the UNION of columns found
     in all CSVs for that role.
  4) Add a column "year" for every row based on the parent directory name.
  5) Save five unified CSVs to data/unified_agents as:
       - unified_aut.csv
       - unified_edt.csv
       - unified_ill.csv
       - unified_pbl.csv
       - unified_trl.csv

Notes:
  - CSV dialects are auto-detected (comma/semicolon/tab) via pandas with
    sep=None and engine="python".
  - Encoding is attempted in order: UTF-8 with BOM, UTF-8, Latin-1.
  - All columns are read as strings to avoid dtype conflicts across files.
  - If a role/year folder contains multiple CSVs, they are all appended.
  - If a role has no rows at all, an empty file with just a header may be created.

Run:
  python agents_main.py

"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pandas as pd

# --- Configuration -----------------------------------------------------------
ROOT_DIR = Path("data") / "results_agents"
OUTPUT_DIR = Path("data") / "unified_agents"
ROLES = ["aut", "edt", "ill", "pbl", "trl"]


def read_csv_auto(path: Path) -> pd.DataFrame:
    """Read a CSV with best-effort handling of encodings and delimiters."""
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(
                str(path),           # Path → str for type checker friendliness
                sep=None,            # auto-detect delimiter
                engine="python",     # needed for sep=None
                dtype=str,           # keep everything as strings
                encoding=enc,
                keep_default_na=False,  # keep empty cells as ""
                na_values=None
            )
        except Exception as e:
            last_err = e
    raise RuntimeError(
        f"Failed to parse CSV {path} with common encodings. Last error: {last_err}"
    )


def collect_role_frames(role: str, root_dir: Path) -> List[pd.DataFrame]:
    """Scan all year folders under root_dir and collect DataFrames for a given role.

    The function looks for CSVs directly under {year}/{role}/ and appends a
    "year" column derived from the year directory name.
    """
    frames: List[pd.DataFrame] = []

    if not root_dir.exists():
        print(f"[WARN] Root directory not found: {root_dir}", file=sys.stderr)
        return frames

    # Iterate year folders (only directories, ignore files like year-level .txt)
    for year_dir in sorted([p for p in root_dir.iterdir() if p.is_dir()]):
        year = year_dir.name
        role_dir = year_dir / role
        if not role_dir.exists() or not role_dir.is_dir():
            # Role folder missing for this year: skip silently
            continue

        # Gather all CSVs inside the role folder (non-recursive by design)
        csv_files = sorted(role_dir.glob("*.csv"))
        if not csv_files:
            # No CSVs in this role/year: skip
            continue

        for csv_path in csv_files:
            try:
                df = read_csv_auto(csv_path)
            except Exception as e:
                print(f"[WARN] Skipping unreadable CSV {csv_path}: {e}", file=sys.stderr)
                continue

            # Ensure we have a "year" column with the parent folder's name
            # If the source already contains a 'year' column, we overwrite it to be consistent
            df["year"] = year

            frames.append(df)

    return frames


def unify_frames(frames: List[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate a list of DataFrames with union of columns.

    Because all frames are read with dtype=str, concatenation will align columns
    by name. Missing columns will be introduced automatically. We then reorder
    columns so that 'year' comes first, followed by all other columns in a
    stable, human-friendly order (alphabetical).
    """
    if not frames:
        # Return an empty DataFrame with just the 'year' column to keep schema predictable
        return pd.DataFrame(columns=["year"], dtype=str)

    unified = pd.concat(frames, ignore_index=True, sort=False)

    # Reorder columns: 'year' first, then the rest sorted alphabetically
    cols = list(unified.columns)
    other_cols = [c for c in cols if c != "year"]
    ordered_cols = ["year"] + sorted(other_cols)
    unified = unified.reindex(columns=ordered_cols)

    return unified


def save_unified(df: pd.DataFrame, role: str, out_dir: Path) -> Path:
    """Save a unified DataFrame for a role to CSV and return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"unified_{role}.csv"
    # Use UTF-8 with BOM for better Excel compatibility; index omitted.
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


def main() -> int:
    any_written = False
    for role in ROLES:
        frames = collect_role_frames(role, ROOT_DIR)
        unified = unify_frames(frames)
        out_path = save_unified(unified, role, OUTPUT_DIR)
        print(f"[OK] Wrote {out_path} with {len(unified):,} rows and {len(unified.columns):,} columns.")
        any_written = True

    if not any_written:
        print("[INFO] No data written. Check that your input tree exists and contains CSVs.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
