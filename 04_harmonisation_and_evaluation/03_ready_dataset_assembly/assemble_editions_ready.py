#!/usr/bin/env python3
"""
assemble_editions_ready.py  —  Module 04, Step 3

Assembles the "ready" editions dataset that modules 5+ (currently module 6's
06_mapping/03_map_estc_ecco.py and 04_merge_mappings.py) already expect at
data/bnf_edition_data/bnf_editions_ready.csv.

There is no separate "subset optimisation" stage for editions (unlike
actors, where module 5 does deduplication/aggregation) — so this script is
responsible for BOTH:
  1. Deduplicating/aggregating the raw acquisition rows to one row per
     edition (the raw dataset has ~35% duplicate rows per edition, from
     SPARQL multi-valued fields — same pattern as the actor dataset).
     Distinct non-empty values per field are joined with "; ", same
     convention as 05_subset_optimisation/gen_subset_optm.py.
  2. Overlaying every available field-level harmonisation output on top
     (currently: publication_place, from
     04_harmonisation_and_evaluation/01_harmonisation/publication_place/
     02_tgn_lookup/bnf_place_harmonisation.py). Fields without a harmoniser
     yet (language, publisher, dates, external_links roles) are carried
     through as their raw aggregated values — this script picks up more
     harmonisations automatically as they get implemented, without code
     changes, as long as they're registered in HARMONISATION_SOURCES below.

This keeps every harmonisation step's own output (the <field>_original /
<field>_harmonised / correction_type / confidence mapping) as the audit
trail; this script only assembles the current best-available value per
field into one integrated, traceable dataset.

Input
-----
Raw edition dataset (module 1's acquisition output):
    01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv

Harmonisation overlays (only publication_place exists so far):
    04_harmonisation_and_evaluation/01_harmonisation/publication_place/
    02_tgn_lookup/data/data_final/bnf_publication_place.csv

Output
------
data/bnf_edition_data/bnf_editions_ready.csv:
    edition, bnf_id, title, year_first, year_range, description, place,
    publisher, work, digital_copy_link, subject_topic, expression, language,
    record_type, author, editor, translator, publisher_2, illustrator,
    publication_place, publication_country, tgn_id, longitude, latitude,
    place_uncertainty_brackets, place_uncertainty_parentheses,
    place_uncertainty_question_marks

report/editions_ready_report.json:
    row counts, and which fields were harmonised vs still raw/pending.

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: periodic checkpoints while aggregating the raw
rows (~1.3M rows), plus a final checkpoint. On by default via CLI,
--no-monitor to disable.

Usage
-----
python assemble_editions_ready.py \\
    --input 01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv \\
    --publication-place 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_final/bnf_publication_place.csv \\
    --output data/bnf_edition_data/bnf_editions_ready.csv \\
    --report 04_harmonisation_and_evaluation/03_ready_dataset_assembly/report/editions_ready_report.json
"""

import os, csv, sys, json, argparse, importlib.util
from collections import defaultdict
from pathlib import Path

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) used below, raising
# UnicodeEncodeError. Reconfigure to UTF-8 up front.
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

INPUT_DEFAULT = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv"
PUBLICATION_PLACE_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/publication_place/"
    "02_tgn_lookup/data/data_final/bnf_publication_place.csv"
)
OUTPUT_DEFAULT = "data/bnf_edition_data/bnf_editions_ready.csv"
REPORT_DEFAULT = "04_harmonisation_and_evaluation/03_ready_dataset_assembly/report/editions_ready_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 50_000

RAW_DATA_FIELDS = [
    "bnf_id", "title", "year_first", "year_range", "description", "place",
    "publisher", "work", "digital_copy_link", "subject_topic", "expression",
    "language", "record_type", "author", "editor", "translator",
    "publisher_2", "illustrator",
]

PLACE_HARMONISED_FIELDS = [
    "publication_place", "publication_country", "tgn_id",
    "longitude", "latitude",
    "place_uncertainty_brackets", "place_uncertainty_parentheses",
    "place_uncertainty_question_marks",
]

# Registry of harmonisation overlays applied on top of the raw aggregation.
# Extend this as more editions-side normalisers get implemented (language,
# publisher, dates, external_links) — no other code changes needed as long
# as the loader returns {edition_uri: {new_column: value, ...}}.
HARMONISATION_SOURCES = ["publication_place"]

OUTPUT_FIELDS = ["edition"] + RAW_DATA_FIELDS + PLACE_HARMONISED_FIELDS


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def load_publication_place_overlay(path: str) -> dict[str, dict[str, str]]:
    """edition_uri -> {publication_place, publication_country, tgn_id,
    longitude, latitude, place_uncertainty_*}"""
    overlay: dict[str, dict[str, str]] = {}
    if not path or not os.path.exists(path):
        print(f"  [warn] publication_place harmonisation not found at {path!r}. "
             f"Run bnf_place_harmonisation.py first — editions_ready will carry "
             f"only the raw 'place' field.")
        return overlay

    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            edition = normalise(row.get("edition", ""))
            if not edition:
                continue
            overlay[edition] = {field: normalise(row.get(field, ""))
                                for field in PLACE_HARMONISED_FIELDS}
    print(f"  Loaded publication_place harmonisation for {len(overlay):,} editions.")
    return overlay


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = Path(__file__).resolve().parents[2]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_assemble_editions", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(input_path: str, publication_place_path: str, output_path: str, report_path: str,
       use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:

    place_overlay = load_publication_place_overlay(publication_place_path)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during assemble_editions_ready.py execution",
            print_start_message=True,
        )

    # Pass 1: aggregate raw rows by edition URI (distinct values per field).
    editions_db: dict[str, dict[str, set]] = {}
    total_rows = 0

    print(f"  Reading raw editions: {input_path}")
    with open(input_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            if total_rows % MONITOR_CHECKPOINT_EVERY == 0:
                print(f"    … {total_rows:,} rows, {len(editions_db):,} editions")
                if use_monitor:
                    monitor_state = monitor_module.update_monitor_state(
                        state=monitor_state,
                        context=f"Aggregated {total_rows:,} rows, {len(editions_db):,} editions so far",
                        print_console=True,
                    )

            edition = normalise(row.get("edition", ""))
            if not edition:
                continue

            entry = editions_db.setdefault(edition, {f: set() for f in RAW_DATA_FIELDS})
            for field in RAW_DATA_FIELDS:
                val = normalise(row.get(field, ""))
                if val:
                    entry[field].add(val)

    print(f"  Total rows: {total_rows:,}  |  Unique editions: {len(editions_db):,}")

    # Pass 2: flatten + overlay harmonised fields.
    results = []
    harmonised_counts = {field: 0 for field in PLACE_HARMONISED_FIELDS}
    for edition, fields in sorted(editions_db.items()):
        rec = {"edition": edition}
        for f in RAW_DATA_FIELDS:
            rec[f] = "; ".join(sorted(fields[f]))

        overlay = place_overlay.get(edition, {})
        for f in PLACE_HARMONISED_FIELDS:
            rec[f] = overlay.get(f, "")
            if rec[f]:
                harmonised_counts[f] += 1

        results.append(rec)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    report = {
        "total_raw_rows": total_rows,
        "unique_editions": len(editions_db),
        "harmonised_fields": {
            "publication_place": {
                "status": "harmonised" if place_overlay else "pending (source not found)",
                "editions_with_value": harmonised_counts["publication_place"],
            },
        },
        "raw_fields_pending_harmonisation": [
            "language", "publisher", "publisher_2", "author", "editor",
            "translator", "illustrator", "year_first", "year_range",
        ],
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed editions-ready assembly run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {len(results):,} editions -> {output_path}")
    print(f"  publication_place coverage: {harmonised_counts['publication_place']:,}/{len(results):,}")
    print(f"✓ Report -> {report_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the ready editions dataset from raw data + all "
                    "available editions-side harmonisation outputs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",             default=INPUT_DEFAULT)
    parser.add_argument("--publication-place", default=PUBLICATION_PLACE_DEFAULT)
    parser.add_argument("--output",            default=OUTPUT_DEFAULT)
    parser.add_argument("--report",            default=REPORT_DEFAULT)
    parser.add_argument("--monitor-script",    default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",        action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.publication_place, args.output, args.report,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
