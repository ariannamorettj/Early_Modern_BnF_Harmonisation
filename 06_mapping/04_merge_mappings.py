#!/usr/bin/env python3
"""
04_merge_mappings.py  —  Module 06, Step 4
Merges all external mapping outputs into enriched actor and edition datasets.

Inputs
------
- 05_subset_optimisation/output/bnf_actors_optimised.csv   (base actor dataset)
- 06_mapping/output/viaf_mapping.csv
- 06_mapping/output/wikidata_mapping.csv
- 06_mapping/output/estc_mapping.csv
- data/bnf_edition_data/bnf_editions_ready.csv             (base edition dataset)

Outputs
-------
output/bnf_actors_enriched.csv
    All original actor columns + viaf_id, viaf_name, qid, wikidata_label,
    isni, lc_id, bnf_ark, mapping_confidence_viaf, mapping_confidence_wikidata

output/bnf_editions_enriched.csv
    All original edition columns + estc_id, estc_title, estc_author,
    estc_year, estc_language, estc_match_type, estc_confidence

report/merge_report.json
    Coverage statistics for each enrichment dimension.

Usage
-----
python 06_mapping/04_merge_mappings.py

python 06_mapping/04_merge_mappings.py \\
    --actors    05_subset_optimisation/output/bnf_actors_optimised.csv \\
    --viaf      06_mapping/output/viaf_mapping.csv \\
    --wikidata  06_mapping/output/wikidata_mapping.csv \\
    --editions  data/bnf_edition_data/bnf_editions_ready.csv \\
    --estc      06_mapping/output/estc_mapping.csv \\
    --out-actors   06_mapping/output/bnf_actors_enriched.csv \\
    --out-editions 06_mapping/output/bnf_editions_enriched.csv \\
    --report    06_mapping/report/merge_report.json
"""

import os, csv, sys, json, argparse
from typing import Dict

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or U+2192 (→) used below,
# raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)

# ── Defaults ──────────────────────────────────────────────────────────────────
ACTORS_DEFAULT    = "05_subset_optimisation/output/bnf_actors_optimised.csv"
VIAF_DEFAULT      = "06_mapping/output/viaf_mapping.csv"
WIKIDATA_DEFAULT  = "06_mapping/output/wikidata_mapping.csv"
EDITIONS_DEFAULT  = "data/bnf_edition_data/bnf_editions_ready.csv"
ESTC_DEFAULT      = "06_mapping/output/estc_mapping.csv"
OUT_ACTORS        = "06_mapping/output/bnf_actors_enriched.csv"
OUT_EDITIONS      = "06_mapping/output/bnf_editions_enriched.csv"
REPORT_DEFAULT    = "06_mapping/report/merge_report.json"


def normalise(v) -> str:
    if v is None: return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA","N/A","NULL","NONE",""} else s


def load_index(path: str, key_col: str) -> Dict[str, dict]:
    """Load a CSV into a dict keyed by key_col."""
    index = {}
    if not os.path.exists(path):
        print(f"  [warn] {path} not found — skipping.")
        return index
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            k = normalise(row.get(key_col, ""))
            if k:
                index[k] = row
    print(f"  Loaded {len(index):,} records from {path}")
    return index


def write_csv(records, path, fields):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def run_merge(actors_path, viaf_path, wikidata_path,
              editions_path, estc_path,
              out_actors, out_editions, report_path):

    # ── Actor enrichment ──────────────────────────────────────────────────────
    viaf_idx  = load_index(viaf_path,     "BnF_ID")
    wd_idx    = load_index(wikidata_path, "BnF_ID")

    actor_records = []
    actor_fields  = None
    stats_actors  = {"total": 0, "viaf_matched": 0, "wikidata_matched": 0}

    if os.path.exists(actors_path):
        with open(actors_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            actor_fields = list(reader.fieldnames or [])
            for row in reader:
                stats_actors["total"] += 1
                bnf_id = normalise(row.get("BnF_ID", ""))

                # Merge VIAF
                vrow = viaf_idx.get(bnf_id, {})
                row["viaf_id"]                 = normalise(vrow.get("viaf_id", ""))
                row["viaf_name"]               = normalise(vrow.get("viaf_name", ""))
                row["viaf_birth_date"]         = normalise(vrow.get("birth_date", ""))
                row["viaf_death_date"]         = normalise(vrow.get("death_date", ""))
                row["mapping_confidence_viaf"] = normalise(vrow.get("confidence", ""))
                if row["viaf_id"]:
                    stats_actors["viaf_matched"] += 1

                # Merge Wikidata
                wrow = wd_idx.get(bnf_id, {})
                row["qid"]                          = normalise(wrow.get("qid", ""))
                row["wikidata_label"]               = normalise(wrow.get("wikidata_label", ""))
                row["isni"]                         = normalise(wrow.get("isni", ""))
                row["lc_id"]                        = normalise(wrow.get("lc_id", ""))
                row["bnf_ark_wikidata"]             = normalise(wrow.get("bnf_ark", ""))
                row["mapping_confidence_wikidata"]  = normalise(wrow.get("confidence", ""))
                if row["qid"]:
                    stats_actors["wikidata_matched"] += 1

                actor_records.append(row)

    # Build final actor fieldnames
    extra_actor_cols = [
        "viaf_id", "viaf_name", "viaf_birth_date", "viaf_death_date",
        "mapping_confidence_viaf",
        "qid", "wikidata_label", "isni", "lc_id", "bnf_ark_wikidata",
        "mapping_confidence_wikidata",
    ]
    final_actor_fields = (actor_fields or []) + [
        c for c in extra_actor_cols if c not in (actor_fields or [])
    ]
    write_csv(actor_records, out_actors, final_actor_fields)
    print(f"\n✓ Enriched actors   → {out_actors}")
    print(f"  VIAF matched      : {stats_actors['viaf_matched']:,} / {stats_actors['total']:,}")
    print(f"  Wikidata matched  : {stats_actors['wikidata_matched']:,} / {stats_actors['total']:,}")

    # ── Edition enrichment ────────────────────────────────────────────────────
    estc_idx = load_index(estc_path, "BnF_edition_id")

    edition_records = []
    edition_fields  = None
    stats_editions  = {"total": 0, "estc_matched": 0}

    if os.path.exists(editions_path):
        with open(editions_path, "r", encoding="utf-8", newline="",
                  errors="replace") as f:
            reader = csv.DictReader(f)
            edition_fields = list(reader.fieldnames or [])
            for row in reader:
                stats_editions["total"] += 1
                bnf_ed = normalise(row.get("bnf_id") or row.get("edition", ""))

                erow = estc_idx.get(bnf_ed, {})
                row["estc_id"]          = normalise(erow.get("estc_id", ""))
                row["estc_title"]       = normalise(erow.get("estc_title", ""))
                row["estc_author"]      = normalise(erow.get("estc_author", ""))
                row["estc_year"]        = normalise(erow.get("estc_year", ""))
                row["estc_language"]    = normalise(erow.get("estc_language", ""))
                row["estc_match_type"]  = normalise(erow.get("match_type", ""))
                row["estc_confidence"]  = normalise(erow.get("confidence", ""))
                if row["estc_id"]:
                    stats_editions["estc_matched"] += 1

                edition_records.append(row)

    extra_edition_cols = [
        "estc_id", "estc_title", "estc_author", "estc_year",
        "estc_language", "estc_match_type", "estc_confidence",
    ]
    final_edition_fields = (edition_fields or []) + [
        c for c in extra_edition_cols if c not in (edition_fields or [])
    ]
    write_csv(edition_records, out_editions, final_edition_fields)
    print(f"\n✓ Enriched editions → {out_editions}")
    print(f"  ESTC matched      : {stats_editions['estc_matched']:,} / {stats_editions['total']:,}")

    # ── Report ────────────────────────────────────────────────────────────────
    report = {"actors": stats_actors, "editions": stats_editions}
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n✓ Merge report      → {report_path}\n")


def main():
    parser = argparse.ArgumentParser(description="Merge all external mappings into enriched datasets")
    parser.add_argument("--actors",       default=ACTORS_DEFAULT)
    parser.add_argument("--viaf",         default=VIAF_DEFAULT)
    parser.add_argument("--wikidata",     default=WIKIDATA_DEFAULT)
    parser.add_argument("--editions",     default=EDITIONS_DEFAULT)
    parser.add_argument("--estc",         default=ESTC_DEFAULT)
    parser.add_argument("--out-actors",   default=OUT_ACTORS)
    parser.add_argument("--out-editions", default=OUT_EDITIONS)
    parser.add_argument("--report",       default=REPORT_DEFAULT)
    args = parser.parse_args()
    run_merge(
        args.actors, args.viaf, args.wikidata,
        args.editions, args.estc,
        args.out_actors, args.out_editions, args.report,
    )

if __name__ == "__main__":
    main()
