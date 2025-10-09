#!/usr/bin/env python3
"""
actors_id_matching.py

Read each unified agent CSV in `data/unified_agents/` and produce a JSON file
per dataset in `data/actors_matched_ids/`.

Rules (per your spec):
  • Only these fields are considered in the analysis (if present):
      year, actor, actor_birth, actor_country, actor_death, actor_end,
      actor_gender, actor_language, actor_link_close, actor_link_exact,
      actor_name, actor_profession, actor_start
  • The JSON top-level keys are ACTOR values that appear more than once.
  • For each repeated actor, we build a dictionary where each OTHER relevant
    field maps to a list of [value, count] pairs.
  • Empty strings (including whitespace-only) are ignored and do not count.

Example output (simplified):
{
  "actor_id": {
    "year": [["1651", 2], ["1652", 1]],
    "actor_country": [["England", 3]]
  }
}

Notes:
  • The actor key is taken from a column named "actor" (case-insensitive), id BnF.
  • If no actor column is found, that CSV is skipped with a warning.
  • Only the intersection between the RELEVANT_COLUMNS and the actual CSV
    columns is analyzed (others are ignored).

Run:
  python actors_id_matching.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
from tqdm import tqdm

# --- Configuration -----------------------------------------------------------
UNIFIED_DIR = Path("data") / "unified_agents"
OUTPUT_DIR = Path("data") / "actors_matched_ids"

# Columns relevant to the analysis (case-insensitive matching)
RELEVANT_COLUMNS = [
    "year",
    "actor",
    "actor_birth",
    "actor_country",
    "actor_death",
    "actor_end",
    "actor_gender",
    "actor_language",
    "actor_link_close",
    "actor_link_exact",
    "actor_name",
    "actor_profession",
    "actor_start",
]

# Candidate names for the actor column (prefer exact 'actor')
ACTOR_COLUMN_CANDIDATES = ["actor", "agent", "name", "person"]


def find_column_case_insensitive(columns: Iterable[str], target: str) -> str | None:
    """Return the actual column name matching `target` (case-insensitive)."""
    lowered = {c.lower(): c for c in columns}
    return lowered.get(target.lower())


def find_actor_column(columns: Iterable[str]) -> str | None:
    """Return which column is the actor identifier.

    Preference order: 'actor' (any case). If absent, try the fallbacks in
    ACTOR_COLUMN_CANDIDATES case-insensitively.
    """
    # Prefer exact idea of 'actor'
    col = find_column_case_insensitive(columns, "actor")
    if col:
        return col
    lowered = {c.lower(): c for c in columns}
    for cand in ACTOR_COLUMN_CANDIDATES:
        if cand in lowered:
            return lowered[cand]
    return None


def normalize_value(val: str) -> str:
    """Normalize a cell content to a comparable string, trimming whitespace.

    Returns an empty string for None/NaN/whitespace-only values.
    """
    if val is None:
        return ""
    s = str(val).strip()
    return s


def value_counts_for_rows(rows: pd.DataFrame, columns: List[str]) -> Dict[str, List[Tuple[str, int]]]:
    """Compute value frequencies for the selected columns within `rows`.

    Returns: {column -> list of (value, count)}; values are non-empty strings
    sorted by count desc, then by value asc for determinism.
    """
    out: Dict[str, List[Tuple[str, int]]] = {}
    for col in columns:
        counter: Counter[str] = Counter()
        # Use .astype(str) to avoid dtype issues; normalize and ignore empties.
        for v in rows[col].astype(str):
            nv = normalize_value(v)
            if nv:
                counter[nv] += 1
        if counter:
            out[col] = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return out


def analyze_file(csv_path: Path) -> Dict[str, Dict[str, List[Tuple[str, int]]]]:
    """Analyze a unified CSV and build the mapping: actor -> {field -> [[val, n], ...]}.
    """
    try:
        df = pd.read_csv(
            str(csv_path),
            dtype=str,
            encoding="utf-8-sig",
            keep_default_na=False,
        )
    except Exception:
        # Fallback to a permissive encoding if needed
        df = pd.read_csv(
            str(csv_path),
            dtype=str,
            encoding="latin-1",
            keep_default_na=False,
        )

    if df.empty:
        return {}

    # Reduce to only relevant columns that exist in this file
    existing_cols = list(df.columns)
    colmap = {c.lower(): c for c in existing_cols}
    relevant_present = [colmap[c.lower()] for c in RELEVANT_COLUMNS if c.lower() in colmap]

    if not relevant_present:
        return {}

    # Determine actor column
    actor_col = find_actor_column(relevant_present)
    if actor_col is None:
        print(f"[WARN] No actor column found in {csv_path.name}; skipping.", file=sys.stderr)
        return {}

    # Normalize actors and find those occurring more than once
    normalized_actors = df[actor_col].apply(normalize_value)
    counts = normalized_actors.value_counts()
    repeated_actors = set(counts[counts > 1].index)
    if not repeated_actors:
        return {}

    # Other columns to analyze = relevant minus the actor column
    other_cols = [c for c in relevant_present if c != actor_col]

    result: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}
    for actor in tqdm(sorted(repeated_actors), desc=f"Actors in {csv_path.name}", unit="actor"):
        rows = df[normalized_actors == actor]
        per_col_counts = value_counts_for_rows(rows, other_cols)
        if per_col_counts:
            result[actor] = per_col_counts

    return result


def output_name_for(csv_path: Path) -> Path:
    """Derive the output JSON path from the input CSV path.

    Example: unified_aut.csv -> actors_aut.json
    """
    stem = csv_path.stem
    role_suffix = stem.replace("unified_", "")
    return OUTPUT_DIR / f"actors_{role_suffix}.json"


def main() -> int:
    inputs = sorted(UNIFIED_DIR.glob("*.csv"))
    if not inputs:
        print(f"[ERR] No CSV files under {UNIFIED_DIR}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for csv_path in tqdm(inputs, desc="Datasets", unit="file"):
        result = analyze_file(csv_path)
        out_path = output_name_for(csv_path)
        with out_path.open("w", encoding="utf-8") as f:
            # Tuples become lists in JSON; ensure pretty printing.
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[OK] Wrote {out_path} with {len(result)} repeated actors.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
