#!/usr/bin/env python3
"""
names_with_multiple_ids.py

Goal
----
From all JSON files in `data/actors_matched_names/`, build a single subset that
keeps ONLY names whose "actor" field has more than one distinct ID. Preserve the
full metadata dictionary for each such name. Also output a CSV with:
    name, ids
where `ids` is a semicolon-separated list of actor IDs for that name.

Inputs
------
- data/actors_matched_names/*.json
  Structure:
    {
      "<normalized_name>": {
         "actor": [[ "<ID1>", count ], [ "<ID2>", count ], ...],
         "<other_field>": [[ "<value>", count ], ...],
         ...
      },
      ...
    }

Outputs
-------
- JSON (single file): data/actors_matched_names_multiple_ids.json
- CSV  (single file): data/actors_matched_names_multiple_ids.csv

Merging logic across files
--------------------------
If the same <normalized_name> appears in multiple input files, we merge fields.
For each field we deduplicate tuples by first element (the value) and SUM the
counts when the same value appears multiple times across files.

Usage
-----
  python names_with_multiple_ids.py
  # (optional)
  python names_with_multiple_ids.py \
      --in-dir data/actors_matched_names \
      --out-json data/actors_matched_names_multiple_ids.json \
      --out-csv  data/actors_matched_names_multiple_ids.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Tuple

from tqdm import tqdm

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or U+2192 (→) used below,
# raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_ids_from_actor_field(actor_tuples: List[List[Any]]) -> List[str]:
    """Return a list of distinct IDs from the 'actor' field tuples preserving order."""
    ids: List[str] = []
    seen = set()
    for item in actor_tuples or []:
        if isinstance(item, (list, tuple)) and item:
            val = str(item[0]).strip()
            if val and val not in seen:
                seen.add(val)
                ids.append(val)
    return ids


def merge_field_tuples(tuples_a: List[List[Any]], tuples_b: List[List[Any]]) -> List[List[Any]]:
    """
    Merge two lists of [value, count] tuples.
    - Deduplicate by 'value' (first element).
    - Sum 'count' when values coincide.
    - Preserve stable order: values from A first (original order), then new values from B.
    """
    if not tuples_a:
        return tuples_b or []
    if not tuples_b:
        return tuples_a or []

    # Build index from A
    index: Dict[str, int] = {}
    merged: List[List[Any]] = []
    for v, c in tuples_a:
        v_str = str(v)
        count = int(c) if isinstance(c, (int, float, str)) and str(c).isdigit() else c
        merged.append([v_str, count])
        index[v_str] = len(merged) - 1

    # Merge B into merged
    for v, c in tuples_b:
        v_str = str(v)
        count = int(c) if isinstance(c, (int, float, str)) and str(c).isdigit() else c
        if v_str in index:
            i = index[v_str]
            # try to sum if both are numeric
            try:
                merged[i][1] = (merged[i][1] or 0) + (count or 0)
            except Exception:
                # if non-numeric, keep the original count from A
                pass
        else:
            index[v_str] = len(merged)
            merged.append([v_str, count])

    return merged


def merge_name_payloads(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two metadata dicts for the same name:
    - For each field: merge tuple-lists with merge_field_tuples
    """
    if not a:
        return b.copy()
    if not b:
        return a.copy()
    out = dict(a)
    for field, tuples_list in b.items():
        if field not in out:
            out[field] = tuples_list
        else:
            # Both sides have the field; merge tuples
            if isinstance(out[field], list) and isinstance(tuples_list, list):
                out[field] = merge_field_tuples(out[field], tuples_list)
            else:
                # Fallback: prefer 'a'
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a unified subset: names with multiple actor IDs.")
    ap.add_argument("--in-dir", type=Path, default=Path("data/actors_matched_names"),
                    help="Input folder with actors_matched_names JSONs.")
    ap.add_argument("--out-json", type=Path, default=Path("data/actors_matched_names_multiple_ids.json"),
                    help="Output JSON path.")
    ap.add_argument("--out-csv", type=Path, default=Path("data/actors_matched_names_multiple_ids.csv"),
                    help="Output CSV path.")
    args = ap.parse_args()

    files = sorted(args.in_dir.glob("*.json"))
    if not files:
        print(f"[ERR] No JSON files in {args.in_dir}")
        return 1

    unified: Dict[str, Dict[str, Any]] = {}

    # 1) Read & filter per file; merge into unified dict
    for p in tqdm(files, desc="Reading & merging", unit="file"):
        data = load_json(p)
        for name, payload in data.items():
            if not isinstance(payload, dict):
                continue
            actor_tuples = payload.get("actor", [])
            ids = extract_ids_from_actor_field(actor_tuples)
            if len(ids) > 1:
                if name in unified:
                    unified[name] = merge_name_payloads(unified[name], payload)
                else:
                    unified[name] = payload

    # 2) Write unified JSON
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(unified, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote JSON with {len(unified)} names → {args.out_json}")

    # 3) Write CSV (name, ids)
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "ids"])
        for name, payload in unified.items():
            ids = extract_ids_from_actor_field(payload.get("actor", []))
            writer.writerow([name, ";".join(ids)])
    print(f"[OK] Wrote CSV → {args.out_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
