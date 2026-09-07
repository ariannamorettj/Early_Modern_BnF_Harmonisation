#!/usr/bin/env python3
"""
bnf_place_harmonisation.py  —  Module 04, publication_place (TGN lookup approach)

Original approach and harmonisation tables by Iiro, adapted from work done
for the HPB (Heritage of the Printed Book) database. Ported here from the
original pandas-based implementation to a stdlib-only implementation (same
algorithm, no pandas/numpy dependency) and integrated into this repo's
module conventions: CLI-parameterised paths (the original hardcoded
`os.chdir()`/relative-path logic no longer matched the current repo layout),
a report file, and the project's standard monitor integration. The original
pandas version remains available in git history for comparison.

Strategy
--------
BnF's raw `place` field (rdam:P30279) is typically formatted as
"City (Country)". For each raw place string:
  1. str_after_last_parentheses() splits the string at the LAST parenthesised
     group into a city part and a country part (unchanged from the original
     implementation).
  2. The city part is cleaned into `city_harmonised` (strip brackets/
     parentheses/question marks, commas, a handful of leading particles —
     same replacement chain as the original).
  3. `city_harmonised` is looked up in a manually curated harmonisation
     table (--place-table) mapping to a TGN (Getty Thesaurus of Geographic
     Names) id, canonical city name, canonical country name, and
     coordinates.
  4. If the TGN lookup doesn't resolve a country, the raw country part
     (step 1) is looked up in a separate country-only harmonisation table
     (--country-table) as a fallback — same two-step logic as the original.

Uncertainty flags (place_uncertainty_brackets/parentheses/question_marks)
record whether the raw city string itself carried bracket/parenthesis/
question-mark markers — i.e. whether the BnF catalogue already flagged this
place as uncertain, independent of whether the TGN lookup succeeded.

Input
-----
Raw edition dataset (module 1's acquisition output) with columns including
`edition` and `place`, e.g.
01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv
This is currently the first (and only) harmonisation step on the editions
side, so it reads directly from module 1's raw output; once other
editions-side fields are harmonised, this should be revisited to read from
whatever the most up-to-date editions dataset is at that point.

Output
------
data/data_final/bnf_publication_place.csv (path via --output):
    edition, place_original, place_uncertainty_brackets,
    place_uncertainty_parentheses, place_uncertainty_question_marks,
    tgn_id, publication_place, publication_country, longitude, latitude

report/publication_place_report.json (path via --report):
    summary statistics (distinct places, TGN match rate, country-fallback
    rate, unmatched rate)

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by module 1's query_agents.R / query_editions.R and by the
06_mapping / name_normaliser.py scripts. The monitor-related code is marked
with clearly delimited comment blocks below so it's obvious what was added
on top of the original harmonisation logic. One checkpoint every 500
distinct place strings processed, plus a final checkpoint on completion.
Reports land in 00_monitor/report/bnf_place_harmonisation_<timestamp>_py.txt.
Disable with --no-monitor.

Usage
-----
python bnf_place_harmonisation.py \\
    --input 01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv \\
    --place-table 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_work/bnf_place_name_harmonisation_table_final.csv \\
    --country-table 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_work/bnf_country_harmonisation_table.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_final/bnf_publication_place.csv \\
    --report 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/report/publication_place_report.json
"""

import os, csv, sys, re, json, argparse, importlib.util
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
_TGN_LOOKUP_DIR = ("04_harmonisation_and_evaluation/01_harmonisation/"
                   "publication_place/02_tgn_lookup")
PLACE_TABLE_DEFAULT   = f"{_TGN_LOOKUP_DIR}/data/data_work/bnf_place_name_harmonisation_table_final.csv"
COUNTRY_TABLE_DEFAULT = f"{_TGN_LOOKUP_DIR}/data/data_work/bnf_country_harmonisation_table.csv"
OUTPUT_DEFAULT         = f"{_TGN_LOOKUP_DIR}/data/data_final/bnf_publication_place.csv"
REPORT_DEFAULT         = f"{_TGN_LOOKUP_DIR}/report/publication_place_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 500  # distinct place strings per checkpoint

OUTPUT_FIELDS = [
    "edition", "place_original",
    "place_uncertainty_brackets", "place_uncertainty_parentheses",
    "place_uncertainty_question_marks",
    "tgn_id", "publication_place", "publication_country",
    "longitude", "latitude",
]


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def str_after_last_parentheses(x):
    """
    Parse city-level and country-level place information from a string.
    Extracts text before and after the last set of parentheses.
    (Logic unchanged from the original implementation.)
    """
    if x is None or x == "":
        return ["", ""]

    matches = [m.start() for m in re.finditer(r'\(', x)]
    if not matches:
        # No parentheses found
        return [x.strip(), ""]

    x_loc_max = max(matches)
    n_string = len(x)

    sub_string_after_last = x[x_loc_max:n_string]
    sub_string_after_last = re.sub(r'[\(\)]', '', sub_string_after_last).strip()

    sub_string_before_last = x[:x_loc_max].strip()

    return [sub_string_before_last, sub_string_after_last]


# Same chain of replacements as the original implementation's pandas
# .str.replace() chain, applied in order.
_CITY_HARMONISE_PREFIXES = ["In ", "A ", "À ", "Tot ", "Te ", "T' ", "t ", "t' "]


def harmonise_city_string(city: str) -> str:
    """Clean a raw city string into its harmonised lookup key."""
    s = re.sub(r'[\[\]]', '', city)
    s = re.sub(r'[\(\)]', '', s)
    s = re.sub(r'\?', '', s)
    s = s.replace(',', '')
    for prefix in _CITY_HARMONISE_PREFIXES:
        s = s.replace(prefix, '')
    return s.strip()


def load_place_table(path: str) -> dict:
    """city_harmonised -> {tgn_id, publication_place, publication_country,
    longitude, latitude}"""
    table = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = normalise(row.get("city_harmonised", ""))
            if key and key not in table:
                table[key] = {
                    "tgn_id": normalise(row.get("tgn_id", "")),
                    "publication_place": normalise(row.get("publication_place", "")),
                    "publication_country": normalise(row.get("publication_country", "")),
                    "longitude": normalise(row.get("longitude", "")),
                    "latitude": normalise(row.get("latitude", "")),
                }
    return table


def load_country_table(path: str) -> dict:
    """raw country string -> country_harmonised"""
    table = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = normalise(row.get("country", ""))
            if key and key not in table:
                table[key] = normalise(row.get("country_harmonised", ""))
    return table


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──
#
# Everything in this section, and the clearly-delimited blocks referencing it
# inside run() below, was added on top of the original harmonisation logic
# (str_after_last_parentheses, harmonise_city_string, the TGN/country lookup
# chain in run()). Nothing else in this file was changed for monitoring.

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and this repo's other
    module 04/05/06 scripts."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_place_harmonisation", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(input_path: str, place_table_path: str, country_table_path: str,
       output_path: str, report_path: str,
       use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:

    place_table = load_place_table(place_table_path)
    country_table = load_country_table(country_table_path)

    # Pass 1: first (edition -> place) seen per edition, and every distinct
    # raw place string across the dataset.
    edition_to_place: dict[str, str] = {}
    distinct_places: set[str] = set()
    with open(input_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            edition = normalise(row.get("edition", ""))
            place = normalise(row.get("place", ""))
            if not edition:
                continue
            if edition not in edition_to_place:
                edition_to_place[edition] = place
            if place:
                distinct_places.add(place)

    total_editions = len(edition_to_place)
    sorted_places = sorted(distinct_places)

    # ═══════════════════════ MONITOR INTEGRATION — start ═══════════════════
    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during bnf_place_harmonisation.py execution",
            print_start_message=True,
        )
    # ═════════════════════════════════════════════════════════════════════

    # Pass 2: parse each distinct place string once (city/country split,
    # uncertainty flags, harmonised city key).
    place_info: dict[str, dict] = {}
    for i, place in enumerate(sorted_places):
        city, country_raw = str_after_last_parentheses(place)
        place_info[place] = {
            "city": city,
            "country_raw": country_raw,
            "brackets": bool(re.search(r'[\[\]]', city)),
            "parentheses": bool(re.search(r'[\(\)]', city)),
            "question_marks": bool(re.search(r'\?', city)),
            "city_harmonised": harmonise_city_string(city),
        }

        # ═══════════════ MONITOR INTEGRATION — periodic checkpoint ═════════
        if use_monitor and (i + 1) % MONITOR_CHECKPOINT_EVERY == 0:
            monitor_state = monitor_module.update_monitor_state(
                state=monitor_state,
                context=f"Parsed {i + 1:,}/{len(sorted_places):,} distinct place strings",
                print_console=True,
            )
        # ═════════════════════════════════════════════════════════════════

    # Pass 3: build the final per-edition rows via the TGN lookup, falling
    # back to the country-only table when the TGN table doesn't resolve a
    # country (same two-step logic as the original implementation).
    stats = {
        "total_editions": total_editions,
        "distinct_places": len(distinct_places),
        "tgn_matched": 0,
        "country_fallback_used": 0,
        "unmatched": 0,
    }

    results = []
    for edition, place in sorted(edition_to_place.items()):
        rec = {f: "" for f in OUTPUT_FIELDS}
        rec["edition"] = edition
        rec["place_original"] = place

        info = place_info.get(place)
        if info is None:
            results.append(rec)
            stats["unmatched"] += 1
            continue

        rec["place_uncertainty_brackets"] = str(info["brackets"])
        rec["place_uncertainty_parentheses"] = str(info["parentheses"])
        rec["place_uncertainty_question_marks"] = str(info["question_marks"])

        tgn = place_table.get(info["city_harmonised"])
        if tgn:
            rec["tgn_id"] = tgn["tgn_id"]
            rec["publication_place"] = tgn["publication_place"]
            rec["publication_country"] = tgn["publication_country"]
            rec["longitude"] = tgn["longitude"]
            rec["latitude"] = tgn["latitude"]
            stats["tgn_matched"] += 1

        if not rec["publication_country"]:
            fallback = country_table.get(info["country_raw"], "")
            if fallback:
                rec["publication_country"] = fallback
                stats["country_fallback_used"] += 1

        if not tgn and not rec["publication_country"]:
            stats["unmatched"] += 1

        results.append(rec)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # ═══════════════════════ MONITOR INTEGRATION — finish ═══════════════════
    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed publication-place harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )
    # ═════════════════════════════════════════════════════════════════════

    print(f"\n✓ Wrote {len(results):,} editions -> {output_path}")
    print(f"  TGN matched           : {stats['tgn_matched']:,}")
    print(f"  Country fallback used : {stats['country_fallback_used']:,}")
    print(f"  Unmatched             : {stats['unmatched']:,}")
    print(f"✓ Report -> {report_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="BnF publication place harmonisation (TGN lookup)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",          default=INPUT_DEFAULT)
    parser.add_argument("--place-table",    default=PLACE_TABLE_DEFAULT)
    parser.add_argument("--country-table",  default=COUNTRY_TABLE_DEFAULT)
    parser.add_argument("--output",         default=OUTPUT_DEFAULT)
    parser.add_argument("--report",         default=REPORT_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",     action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.place_table, args.country_table, args.output, args.report,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
