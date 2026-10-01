"""Sample the entities whose text has an integrity problem.

Streams one CSV (the raw acquisition tables, or any later stage), finds the
rows with an issue from text_integrity.py (corrupted characters, double
encoding, control characters, serialised RDF literals such as "France"@fr),
and writes a reproducible random sample of them for manual inspection.

Rows are grouped by entity (the first column, or --entity-column), so an
actor spread over several link rows counts once. Reservoir sampling with a
fixed seed keeps memory flat on the 690 MB editions table and makes a re-run
return the same sample.

Output (02_sampling/data/):
  05_text_issue_sample_...csv   one row per sampled entity and problem cell:
                                entity, column, issue types, value, line
  and a console summary of how many entities have each issue type.

Usage
-----
python 02_sampling/05_text_issue_sample.py \\
    --input 01_data_retrieval/02_actors/actors_data/actor_data.csv --n 50
python 02_sampling/05_text_issue_sample.py \\
    --input 06_mapping/output/bnf_actors_enriched.csv --issue serialised_rdf_literal
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from collections import Counter, OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sampling_utils import DEFAULT_OUTPUT_DIR, build_output_path, current_timestamp  # noqa: E402
from text_integrity import ISSUE_TYPES, iter_csv_rows, row_issues  # noqa: E402

DEFAULT_N = 50
DEFAULT_SEED = 42
OUTPUT_FIELDS = ["entity", "column", "issues", "value", "line"]


def sample_issues(path: str, n: int, seed: int, issue: str | None = None,
                  entity_column: str | None = None) -> tuple[list[dict], Counter, int]:
    """Return (sampled cells, entities per issue type, entities with any issue)."""
    rng = random.Random(seed)
    per_issue: dict[str, set[str]] = {t: set() for t in ISSUE_TYPES}
    reservoir: list[tuple[str, list[dict]]] = []
    seen_entities: set[str] = set()
    candidates = 0

    for line_no, row, valid in iter_csv_rows(path):
        found = row_issues(row, valid)
        if issue:
            found = {c: t for c, t in found.items() if issue in t}
        if not found:
            continue
        key_col = entity_column or next(iter(row))
        entity = row.get(key_col, "") or f"line {line_no}"
        for types in found.values():
            for t in types:
                per_issue[t].add(entity)
        if entity in seen_entities:
            continue
        seen_entities.add(entity)
        cells = [{"entity": entity, "column": col, "issues": ";".join(types),
                  "value": row.get(col, ""), "line": line_no}
                 for col, types in found.items()]
        candidates += 1
        # Reservoir sampling over entities (Algorithm R).
        if len(reservoir) < n:
            reservoir.append((entity, cells))
        else:
            j = rng.randrange(candidates)
            if j < n:
                reservoir[j] = (entity, cells)

    counts = Counter({t: len(v) for t, v in per_issue.items() if v})
    sampled = [cell for _, cells in sorted(reservoir, key=lambda x: x[1][0]["line"]) for cell in cells]
    return sampled, counts, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="CSV file to scan")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help=f"entities to sample (default {DEFAULT_N})")
    parser.add_argument("--issue", choices=ISSUE_TYPES, help="only this issue type")
    parser.add_argument("--entity-column", help="column identifying the entity (default: first column)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    sampled, counts, total = sample_issues(args.input, args.n, args.seed, args.issue, args.entity_column)

    out = build_output_path(
        output_dir=args.output_dir, entry_script=__file__,
        params=OrderedDict([("issue", args.issue), ("n", args.n)]),
        timestamp=current_timestamp(), suffix=".csv",
    )
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(sampled)

    print(f"Scanned {args.input}")
    print(f"Entities with at least one issue: {total:,}")
    for t in ISSUE_TYPES:
        print(f"  {t:<24} {counts.get(t, 0):,} entities")
    print(f"Sample of {min(args.n, total)} entities -> {out}")


if __name__ == "__main__":
    main()
