#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
reduce_actors_dataset.py
------------------------
Build a unified actors table from ALL CSV files under data/unified_agents.

Outputs (written to the 'data' folder):
  1) data/all_actors_merged.csv
     Columns: actor, actor_name, actor_profession, actor_link_exact, actor_link_close
     (missing fields in sources are left empty). INCLUDES perfect duplicates.

  2) data/all_actors_merged_dedup.csv
     Reduced version with perfect duplicates removed across ALL the above columns.

  3) data/all_actors_profession_conflicts.json
     A dictionary keyed by actor.
     For each actor, lists cases where (after dedup) there are differences in one or more of:
     actor_profession, actor_link_exact, actor_link_close.
     Includes normalized value sets (pipe-split) and raw cell value counts.

Dependencies:
  - pandas
  - tqdm

Run:
  python reduce_actors_dataset.py
"""

from pathlib import Path
import json
import pandas as pd
from tqdm import tqdm

# Input root and output folder
INPUT_ROOT = Path("data/unified_agents")
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Columns of interest (if missing in sources, they will be created empty)
COLUMNS = [
    "actor",
    "actor_name",
    "actor_profession",
    "actor_link_exact",
    "actor_link_close",
]

def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure all required columns exist; add empty ones if missing."""
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df

def read_one_csv(csv_path: Path) -> pd.DataFrame:
    """Read a CSV as strings and return only the columns of interest (adding missing ones as empty)."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df = _ensure_columns(df)
    return df[COLUMNS].copy()

def split_pipe_values(value: str) -> list[str]:
    """
    Split pipe-separated values into individual items.
    Returns [] for empty/None. Trims whitespace.
    """
    if value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    if "|" in s:
        return [x.strip() for x in s.split("|") if x.strip()]
    return [s]

def main():
    csv_files = sorted(INPUT_ROOT.rglob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in: {INPUT_ROOT.resolve()}")
        return

    parts = []
    print(f"Found {len(csv_files)} CSV files. Merging...")
    for f in tqdm(csv_files, desc="Reading CSV (unified_agents)"):
        try:
            df = read_one_csv(f)
            parts.append(df)
        except Exception as e:
            print(f"Could not read {f}: {e}")

    if not parts:
        print("No valid data read.")
        return

    merged = pd.concat(parts, ignore_index=True)

    # 1) Unified CSV - includes perfect duplicates
    out_merged = OUTPUT_DIR / "all_actors_merged.csv"
    merged.to_csv(out_merged, index=False)
    print(f"Unified table written to: {out_merged} (rows: {len(merged)})")

    # 2) Perfect dedup across all columns
    dedup = merged.drop_duplicates(subset=COLUMNS, keep="first")
    out_dedup = OUTPUT_DIR / "all_actors_merged_dedup.csv"
    dedup.to_csv(out_dedup, index=False)
    print(f"Deduplicated table written to: {out_dedup} (rows: {len(dedup)})")

    # 3) Conflicts per actor: differences in profession/links after perfect dedup
    print("Analyzing profession/link conflicts (per actor)...")
    conflicts_dict = {}

    grouped = dedup.groupby(["actor"], dropna=False)

    def split_pipe_values(v: str):
        """
        Split a pipe-separated cell into individual trimmed values.
        Returns [] for empty/None.
        """
        s = str(v).strip()
        if not s:
            return []
        return [x.strip() for x in s.split("|")] if "|" in s else [s]

    for group_key, grp in tqdm(grouped, total=grouped.ngroups, desc="Grouping by actor"):
        # Some pandas versions return a 1-tuple even when grouping by a single column.
        # Unwrap it if needed.
        if isinstance(group_key, tuple) and len(group_key) == 1:
            actor_val = group_key[0]
        else:
            actor_val = group_key

        actor_key = str(actor_val)  # JSON key: actor IRI as a plain string

        # Collect distinct non-empty names seen for this actor
        actor_names = sorted({str(x).strip() for x in grp["actor_name"].tolist() if str(x).strip() != ""})

        # Professions: normalized set (non-empty) + per-cell counts for diagnostics
        professions = sorted({p.strip() for p in grp["actor_profession"].astype(str).tolist() if p.strip() != ""})
        prof_counts = grp["actor_profession"].value_counts(dropna=False).to_dict()
        prof_counts = {("" if (k != k or k is None) else str(k)): int(v) for k, v in prof_counts.items()}

        # link_exact: normalized set (after splitting pipes) + raw per-cell counts
        exact_values = set()
        for v in grp["actor_link_exact"].astype(str).tolist():
            exact_values.update(split_pipe_values(v))
        link_exact = sorted([v for v in exact_values if v])
        exact_counts_raw = grp["actor_link_exact"].value_counts(dropna=False).to_dict()
        exact_counts_raw = {("" if (k != k or k is None) else str(k)): int(v) for k, v in exact_counts_raw.items()}

        # link_close: normalized set (after splitting pipes) + raw per-cell counts
        close_values = set()
        for v in grp["actor_link_close"].astype(str).tolist():
            close_values.update(split_pipe_values(v))
        link_close = sorted([v for v in close_values if v])
        close_counts_raw = grp["actor_link_close"].value_counts(dropna=False).to_dict()
        close_counts_raw = {("" if (k != k or k is None) else str(k)): int(v) for k, v in close_counts_raw.items()}

        # Flag a conflict if any of the three normalized sets has more than one distinct non-empty value
        has_prof_conflict = len(professions) > 1
        has_exact_conflict = len(link_exact) > 1
        has_close_conflict = len(link_close) > 1

        if has_prof_conflict or has_exact_conflict or has_close_conflict:
            conflicts_dict[actor_key] = {
                "actor_names": actor_names,
                "professions": professions,
                "profession_counts_by_cell": prof_counts,  # counts on raw cell values
                "link_exact_values": link_exact,  # normalized (pipe-split) set
                "link_exact_counts_by_cell": exact_counts_raw,
                "link_close_values": link_close,  # normalized (pipe-split) set
                "link_close_counts_by_cell": close_counts_raw,
                "rows_in_group": int(len(grp)),
            }

    out_conflicts = OUTPUT_DIR / "all_actors_profession_conflicts.json"
    with out_conflicts.open("w", encoding="utf-8") as w:
        json.dump(conflicts_dict, w, ensure_ascii=False, indent=2)

    print(f"Conflicts JSON written to: {out_conflicts} (actors with conflicts: {len(conflicts_dict)})")

if __name__ == "__main__":
    main()
