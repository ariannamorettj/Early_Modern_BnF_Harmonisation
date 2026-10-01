"""Text-integrity check: count corrupted or unwrapped text per column.

Streams each input CSV and counts, per column, the cells with an issue
defined in 02_sampling/text_integrity.py:

  invalid_utf8, replacement_char   the original characters are lost;
  double_encoded                   UTF-8 read as Latin-1 ("Ã©");
  control_char                     stray control characters;
  serialised_rdf_literal           a SPARQL literal kept as text ("France"@fr).

Run it on every stage of a table (raw, ready, optimised, enriched) to see
where a problem appears or disappears: a count that is zero at the source and
non-zero later points at the step that introduced it. The JSON report keeps
up to --examples example values per column and issue.

Output: 03_analysis/data/06_text_integrity_check_<timestamp>.json

Usage
-----
python 03_analysis/06_text_integrity_check.py \\
    --input 01_data_retrieval/02_actors/actors_data/actor_data.csv \\
            04_harmonisation_and_evaluation/output/bnf_actors_ready.csv \\
            06_mapping/output/bnf_actors_enriched.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_sampling"))

from sampling_utils import build_output_path, current_timestamp  # noqa: E402
from text_integrity import ISSUE_TYPES, iter_csv_rows, row_issues  # noqa: E402

DEFAULT_OUTPUT_DIR = os.path.join("03_analysis", "data")
DEFAULT_EXAMPLES = 5


def check_file(path: str, examples: int = DEFAULT_EXAMPLES) -> dict:
    """Per-column issue counts for one CSV, plus a few example values."""
    rows = 0
    rows_with_issue = 0
    counts: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for line_no, row, valid in iter_csv_rows(path):
        rows += 1
        found = row_issues(row, valid)
        if found:
            rows_with_issue += 1
        for col, types in found.items():
            for t in types:
                counts[col][t] += 1
                if len(samples[col][t]) < examples:
                    samples[col][t].append({"line": line_no, "value": (row.get(col) or "")[:200]})
    totals = Counter()
    for c in counts.values():
        totals.update(c)
    return {
        "file": path,
        "rows": rows,
        "rows_with_any_issue": rows_with_issue,
        "totals": {t: totals.get(t, 0) for t in ISSUE_TYPES},
        "by_column": {col: dict(c) for col, c in sorted(counts.items())},
        "examples": {col: dict(v) for col, v in sorted(samples.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="+", required=True, help="CSV file(s) to check")
    parser.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = {"issue_types": list(ISSUE_TYPES), "files": []}
    for path in args.input:
        if not os.path.exists(path):
            print(f"[skip] not found: {path}")
            continue
        result = check_file(path, args.examples)
        report["files"].append(result)
        print(f"{path}: {result['rows']:,} rows, {result['rows_with_any_issue']:,} with an issue")
        for t in ISSUE_TYPES:
            n = result["totals"][t]
            if n:
                cols = ", ".join(f"{c} ({v[t]:,})" for c, v in result["by_column"].items() if t in v)
                print(f"  {t:<24} {n:,} cells: {cols}")

    out = build_output_path(output_dir=args.output_dir, entry_script=__file__,
                            timestamp=current_timestamp(), suffix=".json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"Report -> {out}")


if __name__ == "__main__":
    main()
