#!/usr/bin/env python3
"""
editions_additional_analysis.py

Purpose
-------
Produce separate JSON reports for
`unified_dataset` chunks stored in `data/unified_dataset/unified_chunks/`.

Inputs
------
- A folder of CSV files (one per year chunk) having columns like:
  edition, expression, work, record_type, ... (plus many agent-related fields).
- Cells in edition/expression/work may contain multiple URIs separated by ';'.

What this script computes (separate outputs)
-------------------------------------------
1) work_link_summary.json
   "How many work ids map to editions and how many to expressions? One of these
   must exist; not all editions need to connect to a work id."
   → Counts of works linked to ≥1 edition / ≥1 expression / both / neither.
   → Also counts of unique editions and expressions that are linked from any work.

2) edition_expression_checks.json
   "editions > expressions, but no editions with multiple expressions; check which
   editions do not pair with an expression and vice versa"
   →
     - List of editions with more than one linked expression.
     - List of editions with zero expressions.
     - List of expressions with zero editions.
     - Totals and small samples for quick inspection.

3) focus_uris.json  (optional)
   If you set FOCUS_URIS to a list of specific URIs of interest, the script will
   report whether each URI appears as an edition/expression/work, and summarize
   its pairings.

Filtering by record type (subset of books)
-----------------------------------------
- Use `--record-type <VALUE>` to filter the analysis to rows where `record_type`
  equals that value (case-insensitive). If omitted, analyze all rows.

Outputs
-------
- All JSON files are written to `final_dataset_analysis/reports/`.

Usage
-----
python final_dataset_analysis/editions_additional_analysis.py \
  --csv-dir data/unified_dataset/unified_chunks \
  --out-dir final_dataset_analysis/reports \
  --record-type http://purl.org/dc/dcmitype/Text


Notes
-----
- All counting uses unique URIs (after splitting ';').
- Empty strings are ignored.
- The script is memory-friendly: it streams rows file-by-file and stores only
  the necessary associations as Python sets.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from tqdm import tqdm

# ----------------------------- Configuration ---------------------------------
DEFAULT_CSV_DIR = Path("data/unified_dataset/unified_chunks")
DEFAULT_OUT_DIR = Path("final_dataset_analysis/reports")

# to focus on specific URIs, add them here (edition/expression/work)
FOCUS_URIS: List[str] = [
    # "http://data.bnf.fr/ark:/12148/cb120082823#about",
    # "http://data.bnf.fr/temp-work/4af10e9259288f9417c5fd6664f22753/#about",
]

# Columns we care about
COL_EDITION = "edition"
COL_EXPRESSION = "expression"
COL_WORK = "work"
COL_RECORD_TYPE = "record_type"

# ------------------------------- Helpers -------------------------------------

def parse_multi(value: str) -> List[str]:
    """Split semicolon-separated values into a clean list.

    - None or empty → []
    - Trims whitespace around each token
    - Drops empty tokens
    """
    if not value:
        return []
    return [tok.strip() for tok in value.split(";") if tok and tok.strip()]


def norm(s: str | None) -> str:
    return (s or "").strip()


# ------------------------------ Core logic -----------------------------------

def scan_rows(csv_dir: Path, record_type_filter: str | None):
    """Yield normalized (editions, expressions, works, row_ok) for each row in all CSVs.

    - Applies record_type filter if provided.
    - Each of editions/expressions/works is a *set* (duplicates within a row removed).
    """
    files = sorted([p for p in csv_dir.iterdir() if p.suffix.lower() == ".csv"])
    for file_path in tqdm(files, desc="Files", unit="file"):
        with file_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Make sure required columns exist; if not, skip file
            headers = {h.lower(): h for h in reader.fieldnames or []}
            miss = [c for c in [COL_EDITION, COL_EXPRESSION, COL_WORK] if c not in headers]
            if miss:
                continue
            col_edition = headers[COL_EDITION]
            col_expression = headers[COL_EXPRESSION]
            col_work = headers[COL_WORK]
            col_record_type = headers.get(COL_RECORD_TYPE)

            for row in reader:
                if record_type_filter and col_record_type:
                    if norm(row.get(col_record_type)).lower() != record_type_filter.lower():
                        continue

                editions = set(parse_multi(row.get(col_edition, "")))
                expressions = set(parse_multi(row.get(col_expression, "")))
                works = set(parse_multi(row.get(col_work, "")))
                yield editions, expressions, works


def build_indexes(csv_dir: Path, record_type_filter: str | None):
    """Scan once and build association maps and global sets needed downstream."""
    # Global unique sets
    all_editions: Set[str] = set()
    all_expressions: Set[str] = set()
    all_works: Set[str] = set()

    # Pairings (many-to-many)
    edition_to_expressions: Dict[str, Set[str]] = defaultdict(set)
    expression_to_editions: Dict[str, Set[str]] = defaultdict(set)

    work_to_editions: Dict[str, Set[str]] = defaultdict(set)
    work_to_expressions: Dict[str, Set[str]] = defaultdict(set)

    for editions, expressions, works in scan_rows(csv_dir, record_type_filter):
        all_editions.update(editions)
        all_expressions.update(expressions)
        all_works.update(works)

        # edition ↔ expression
        for ed in editions:
            edition_to_expressions[ed].update(expressions)
        for ex in expressions:
            expression_to_editions[ex].update(editions)

        # work ↔ edition / expression
        for wk in works:
            work_to_editions[wk].update(editions)
            work_to_expressions[wk].update(expressions)

    return {
        "all_editions": all_editions,
        "all_expressions": all_expressions,
        "all_works": all_works,
        "edition_to_expressions": edition_to_expressions,
        "expression_to_editions": expression_to_editions,
        "work_to_editions": work_to_editions,
        "work_to_expressions": work_to_expressions,
    }


# ------------------------------ Reports --------------------------------------

def report_work_link_summary(indexes: dict, out_dir: Path, record_type_filter: str | None) -> Path:
    """Create work_link_summary.json with counts for works → editions/expressions."""
    work_to_editions = indexes["work_to_editions"]
    work_to_expressions = indexes["work_to_expressions"]

    works = set(indexes["all_works"]) | set(work_to_editions.keys()) | set(work_to_expressions.keys())

    works_with_editions = {w for w in works if work_to_editions.get(w)}
    works_with_expressions = {w for w in works if work_to_expressions.get(w)}

    summary = {
        "filter": {"record_type": record_type_filter},
        "works_total": len(works),
        "works_with_edition": len(works_with_editions),
        "works_with_expression": len(works_with_expressions),
        "works_with_both": len(works_with_editions & works_with_expressions),
        "works_with_neither": len(works - works_with_editions - works_with_expressions),
        "unique_editions_linked_from_works": len({ed for s in work_to_editions.values() for ed in s}),
        "unique_expressions_linked_from_works": len({ex for s in work_to_expressions.values() for ex in s}),
    }

    out_path = out_dir / "work_link_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def report_edition_expression_checks(indexes: dict, out_dir: Path, record_type_filter: str | None) -> Path:
    """Create edition_expression_checks.json with the required cardinality checks."""
    all_editions: Set[str] = indexes["all_editions"]
    all_expressions: Set[str] = indexes["all_expressions"]
    ed2ex: Dict[str, Set[str]] = indexes["edition_to_expressions"]
    ex2ed: Dict[str, Set[str]] = indexes["expression_to_editions"]

    # Editions with +1 expressions
    ed_with_multi_ex = {ed: sorted(list(exs)) for ed, exs in ed2ex.items() if len(exs) > 1}

    # Editions with zero expressions (include editions never seen in ed2ex)
    ed_without_ex = sorted([ed for ed in all_editions if not ed2ex.get(ed)])

    # Expressions with zero editions
    ex_without_ed = sorted([ex for ex in all_expressions if not ex2ed.get(ex)])

    report = {
        "filter": {"record_type": record_type_filter},
        "counts": {
            "editions_total": len(all_editions),
            "expressions_total": len(all_expressions),
            "editions_with_multiple_expressions": len(ed_with_multi_ex),
            "editions_without_expression": len(ed_without_ex),
            "expressions_without_edition": len(ex_without_ed),
        },
        "editions_with_multiple_expressions": ed_with_multi_ex,
        "editions_without_expression": ed_without_ex,
        "expressions_without_edition": ex_without_ed,
        # small samples for quick eyeballing
        "samples": {
            "editions_with_multiple_expressions": list(ed_with_multi_ex.keys())[:10],
            "editions_without_expression": ed_without_ex[:10],
            "expressions_without_edition": ex_without_ed[:10],
        },
    }

    out_path = out_dir / "edition_expression_checks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def report_focus_uris(indexes: dict, out_dir: Path, record_type_filter: str | None, focus_uris: List[str]) -> Path | None:
    """If focus URIs are provided, report their presence and pairings."""
    if not focus_uris:
        return None

    ed2ex = indexes["edition_to_expressions"]
    ex2ed = indexes["expression_to_editions"]
    w2ed = indexes["work_to_editions"]
    w2ex = indexes["work_to_expressions"]

    all_editions = indexes["all_editions"]
    all_expressions = indexes["all_expressions"]
    all_works = indexes["all_works"]

    focus = {}
    for uri in focus_uris:
        focus[uri] = {
            "is_edition": uri in all_editions,
            "is_expression": uri in all_expressions,
            "is_work": uri in all_works,
            "edition_links": sorted(list(ed2ex.get(uri, set()))) if uri in all_editions else [],
            "expression_links": sorted(list(ex2ed.get(uri, set()))) if uri in all_expressions else [],
            "work_to_editions": sorted(list(w2ed.get(uri, set()))) if uri in all_works else [],
            "work_to_expressions": sorted(list(w2ex.get(uri, set()))) if uri in all_works else [],
        }

    payload = {
        "filter": {"record_type": record_type_filter},
        "focus": focus,
    }

    out_path = out_dir / "focus_uris.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# --------------------------------- CLI ---------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Answer targeted questions about edition/expression/work relations.")
    ap.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR, help="Folder with unified CSV chunks.")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Where to write JSON reports.")
    ap.add_argument("--record-type", type=str, default=None, help="Optional filter on record_type (e.g., http://purl.org/dc/dcmitype/Text).")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    indexes = build_indexes(args.csv_dir, args.record_type)

    p1 = report_work_link_summary(indexes, args.out_dir, args.record_type)
    print(f"[OK] Wrote {p1}")

    p2 = report_edition_expression_checks(indexes, args.out_dir, args.record_type)
    print(f"[OK] Wrote {p2}")

    p3 = report_focus_uris(indexes, args.out_dir, args.record_type, FOCUS_URIS)
    if p3:
        print(f"[OK] Wrote {p3}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
