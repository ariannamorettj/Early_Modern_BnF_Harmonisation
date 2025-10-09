#!/usr/bin/env python3
"""
actors_name_matching.py

Read each unified agent CSV in `data/unified_agents/` and produce a JSON file
per dataset in `data/actors_matched_ids/`.

Rules (per your spec):
  • Only these fields are considered in the analysis (if present):
      year, actor, actor_birth, actor_country, actor_death, actor_end,
      actor_gender, actor_language, actor_link_close, actor_link_exact,
      actor_name, actor_profession, actor_start
  • The JSON top-level keys are the NORMALIZED string of `actor_name`
    (case-insensitive, trimmed, punctuation normalized so that each part
    of the name is separated by exactly one space) for actors appearing
    more than once.
  • For each repeated actor_name, we build a dictionary where each OTHER
    relevant field maps to a list of [value, count] pairs.
  • Empty strings (including whitespace-only) are ignored and do not count.

Example output (simplified):
{
  "THOMAS HOBBES": {
    "year": [["1651", 2], ["1652", 1]],
    "actor_country": [["England", 3]]
  }
}

Run:
  python actors_name_matching.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
from tqdm import tqdm

# --- Configuration -----------------------------------------------------------
UNIFIED_DIR = Path("data") / "unified_agents"
OUTPUT_DIR = Path("data") / "actors_matched_names"

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

# Function to normalize actor_name field
_name_norm_re = re.compile(r"[\s.,]+", re.UNICODE)

def normalize_actor_name(val: str) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    # Replace sequences of whitespace, commas, or dots with single space
    s = _name_norm_re.sub(" ", s)
    # Normalize case: make consistent upper/lower (here we choose upper)
    s = s.upper()
    return s


def normalize_value(val: str) -> str:
    if val is None:
        return ""
    return str(val).strip()


def value_counts_for_rows(rows: pd.DataFrame, columns: List[str]) -> Dict[str, List[Tuple[str, int]]]:
    out: Dict[str, List[Tuple[str, int]]] = {}
    for col in columns:
        counter: Counter[str] = Counter()
        for v in rows[col].astype(str):
            nv = normalize_value(v)
            if nv:
                counter[nv] += 1
        if counter:
            out[col] = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return out


def analyze_file(csv_path: Path) -> Dict[str, Dict[str, List[Tuple[str, int]]]]:
    try:
        df = pd.read_csv(
            str(csv_path),
            dtype=str,
            encoding="utf-8-sig",
            keep_default_na=False,
        )
    except Exception:
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
    if not relevant_present or "actor_name".lower() not in colmap:
        return {}

    actor_name_col = colmap["actor_name"]

    # Normalize actor_name and find those occurring more than once
    normalized_names = df[actor_name_col].apply(normalize_actor_name)
    counts = normalized_names.value_counts()
    repeated_names = set(counts[counts > 1].index)
    if not repeated_names:
        return {}

    other_cols = [c for c in relevant_present if c != actor_name_col]

    result: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}
    for name in tqdm(sorted(repeated_names), desc=f"Actors in {csv_path.name}", unit="actor_name"):
        rows = df[normalized_names == name]
        per_col_counts = value_counts_for_rows(rows, other_cols)
        if per_col_counts:
            result[name] = per_col_counts

    return result


def output_name_for(csv_path: Path) -> Path:
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
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[OK] Wrote {out_path} with {len(result)} repeated actors.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
