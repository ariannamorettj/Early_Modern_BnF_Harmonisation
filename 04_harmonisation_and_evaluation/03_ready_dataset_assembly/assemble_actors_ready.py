#!/usr/bin/env python3
"""
assemble_actors_ready.py  —  Module 04, Step 3

Assembles the "ready" actors dataset consumed by
05_subset_optimisation/gen_subset_optm.py.

Unlike editions (see assemble_editions_ready.py in this same folder), this
script does NOT deduplicate/aggregate rows to one row per actor —
deduplication and aggregation into a research-oriented subset is module 5's
job (gen_subset_optm.py), which reads this script's output as its base
instead of the truly raw acquisition data. This script preserves the raw
row-level granularity (including the duplicate rows per actor URI coming
from multi-valued external links) and only patches in field-level
corrections from whichever harmonisation outputs are available.

Three actors-side harmonisations are wired in so far: actor_name (via
04_harmonisation_and_evaluation/01_harmonisation/actor_name/
01_heuristic_rules/name_normaliser.py), actor_dates (via
04_harmonisation_and_evaluation/01_harmonisation/actor_dates/
01_heuristic_rules/dates_normaliser.py), and external_links (via
04_harmonisation_and_evaluation/01_harmonisation/external_links/
01_heuristic_rules/external_links_normaliser.py). This script picks up more
harmonisations automatically as they get implemented, without code changes,
as long as they're registered in HARMONISATION_SOURCES below.

actor_name, actor_dates and external_links use different overlay semantics:
  - actor_name only FILLS a field that was empty at the source (a name that
    already exists is never second-guessed by a heuristic rule).
  - actor_dates REPLACES the raw value whenever a harmonised EDTF form is
    available, even if the raw field was already populated — harmonising a
    date always means reformatting it (e.g. "17.." -> "17XX", "-43" ->
    "-0043"), so the raw value is never itself the canonical target the way
    an existing actor_name can be.
  - external_links also REPLACES, but keyed per (actor_uri, field, RAW
    VALUE) rather than per actor: unlike actor_dates (one value per field
    per actor), actor_link_close/actor_link_exact are inherently multi-row
    per actor (see external_links_normaliser.py's module docstring on row
    multiplicity) — every raw row already carries its own distinct link
    value, so the overlay must replace the specific value that specific row
    carries, not aggregate across the whole actor. Only replaced when the
    normaliser produced a non-empty link_harmonised (malformed/unresolvable
    links are left as their raw value, same "don't blank out what we can't
    confidently improve" convention as actor_dates' missing/non_parseable
    rows).

Input
-----
Raw actor dataset (module 1's acquisition output):
    01_data_retrieval/02_actors/actors_data/actor_data.csv (or .zip)

Harmonisation overlays:
    04_harmonisation_and_evaluation/01_harmonisation/actor_name/
    01_heuristic_rules/output/actor_name_harmonised.csv
    04_harmonisation_and_evaluation/01_harmonisation/actor_dates/
    01_heuristic_rules/output/actor_dates_harmonised.csv
    04_harmonisation_and_evaluation/01_harmonisation/external_links/
    01_heuristic_rules/output/external_links_harmonised.csv

Output
------
04_harmonisation_and_evaluation/output/bnf_actors_ready.csv:
    same columns and same row-level granularity as the raw input, with
    actor_name filled in, actor_birth/actor_death/actor_start/actor_end
    replaced with their EDTF form, and actor_link_exact/actor_link_close
    replaced with their harmonised (RDF-unwrapped, authority-classified)
    form wherever a correction was available.

report/actors_ready_report.json:
    row counts, and which fields were harmonised vs still raw/pending.

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: periodic checkpoints while patching the raw rows,
plus a final checkpoint. On by default via CLI, --no-monitor to disable.

Usage
-----
python assemble_actors_ready.py \\
    --input 01_data_retrieval/02_actors/actors_data/actor_data.csv \\
    --actor-name-harmonised 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output/actor_name_harmonised.csv \\
    --actor-dates-harmonised 04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/output/actor_dates_harmonised.csv \\
    --external-links-harmonised 04_harmonisation_and_evaluation/01_harmonisation/external_links/01_heuristic_rules/output/external_links_harmonised.csv \\
    --output 04_harmonisation_and_evaluation/output/bnf_actors_ready.csv \\
    --report 04_harmonisation_and_evaluation/03_ready_dataset_assembly/report/actors_ready_report.json
"""

import os, csv, sys, json, zipfile, argparse, importlib.util
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

INPUT_DEFAULT = "01_data_retrieval/02_actors/actors_data/actor_data.csv"
ACTOR_NAME_HARMONISED_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "01_heuristic_rules/output/actor_name_harmonised.csv"
)
ACTOR_DATES_HARMONISED_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_dates/"
    "01_heuristic_rules/output/actor_dates_harmonised.csv"
)
EXTERNAL_LINKS_HARMONISED_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/external_links/"
    "01_heuristic_rules/output/external_links_harmonised.csv"
)
OUTPUT_DEFAULT = "04_harmonisation_and_evaluation/output/bnf_actors_ready.csv"
REPORT_DEFAULT = "04_harmonisation_and_evaluation/03_ready_dataset_assembly/report/actors_ready_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 20_000

RAW_FIELDS = [
    "actor", "actor_birth", "actor_name", "actor_first_name", "actor_last_name",
    "entity_type", "first_year", "actor_country", "actor_language",
    "actor_gender", "actor_profession", "actor_death", "actor_start",
    "actor_end", "actor_link_exact", "actor_link_close",
]

DATE_FIELDS = ["actor_birth", "actor_death", "actor_start", "actor_end"]
LINK_FIELDS = ["actor_link_exact", "actor_link_close"]

HARMONISATION_SOURCES = ["actor_name", "actor_dates", "external_links"]


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def iter_actor_rows(path: str):
    """Yield row dicts from a plain CSV, or from every CSV inside a ZIP."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name, "r") as f:
                    lines = (line.decode("utf-8", errors="replace") for line in f)
                    yield from csv.DictReader(lines)
    else:
        with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
            yield from csv.DictReader(f)


def load_actor_name_harmonised(path: str) -> dict[str, str]:
    """actor_uri -> derived actor_name, restricted to rows where a name was
    actually derived (correction_type == 'derived_from_first_last')."""
    mapping: dict[str, str] = {}
    if not path or not os.path.exists(path):
        print(f"  [warn] Actor-name harmonised mapping not found at {path!r}. "
             f"Run name_normaliser.py first — actors_ready will carry actor_name "
             f"as-is.")
        return mapping

    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("correction_type") != "derived_from_first_last":
                continue
            uri  = normalise(row.get("actor_uri", ""))
            name = normalise(row.get("actor_name_harmonised", ""))
            if uri and name:
                mapping[uri] = name
    print(f"  Loaded {len(mapping):,} derived actor names.")
    return mapping


def load_actor_dates_harmonised(path: str) -> dict[str, dict[str, str]]:
    """actor_uri -> {field: date_harmonised}, restricted to rows where the
    heuristic/LLM normaliser actually produced an EDTF value (i.e. skips
    'missing' and 'non_parseable' rows, which carry an empty
    date_harmonised — see dates_normaliser.py). Unlike actor_name, every
    field present here is meant to REPLACE the raw value, not just fill an
    empty one (see module docstring)."""
    mapping: dict[str, dict[str, str]] = {}
    if not path or not os.path.exists(path):
        print(f"  [warn] Actor-dates harmonised mapping not found at {path!r}. "
             f"Run dates_normaliser.py first — actors_ready will carry actor_birth/"
             f"actor_death/actor_start/actor_end as-is.")
        return mapping

    rows_loaded = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            uri = normalise(row.get("actor_uri", ""))
            field = normalise(row.get("field", ""))
            harmonised = normalise(row.get("date_harmonised", ""))
            if uri and field in DATE_FIELDS and harmonised:
                mapping.setdefault(uri, {})[field] = harmonised
                rows_loaded += 1
    print(f"  Loaded {rows_loaded:,} harmonised date values for {len(mapping):,} actors.")
    return mapping


def load_external_links_harmonised(path: str) -> dict[tuple[str, str, str], str]:
    """(actor_uri, field, link_original) -> link_harmonised, restricted to
    rows where external_links_normaliser.py actually produced a non-empty
    harmonised value (skips 'missing'/'malformed' rows, whose
    link_harmonised is empty — same convention as
    load_actor_dates_harmonised()'s missing/non_parseable skip). Keyed per
    raw value, not per actor, because a single actor can carry multiple
    distinct links per field (see module docstring)."""
    mapping: dict[tuple[str, str, str], str] = {}
    if not path or not os.path.exists(path):
        print(f"  [warn] External-links harmonised mapping not found at {path!r}. "
             f"Run external_links_normaliser.py first — actors_ready will carry "
             f"actor_link_exact/actor_link_close as-is.")
        return mapping

    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            uri = normalise(row.get("actor_uri", ""))
            field = normalise(row.get("field", ""))
            original = normalise(row.get("link_original", ""))
            harmonised = normalise(row.get("link_harmonised", ""))
            if uri and field in LINK_FIELDS and original and harmonised:
                mapping[(uri, field, original)] = harmonised
    print(f"  Loaded {len(mapping):,} harmonised link values.")
    return mapping


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = Path(__file__).resolve().parents[2]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_assemble_actors", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(input_path: str, actor_name_harmonised_path: str, actor_dates_harmonised_path: str,
       output_path: str, report_path: str,
       external_links_harmonised_path: str = EXTERNAL_LINKS_HARMONISED_DEFAULT,
       use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:

    name_overlay = load_actor_name_harmonised(actor_name_harmonised_path)
    dates_overlay = load_actor_dates_harmonised(actor_dates_harmonised_path)
    links_overlay = load_external_links_harmonised(external_links_harmonised_path)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during assemble_actors_ready.py execution",
            print_start_message=True,
        )

    total_rows = 0
    filled_actor_name = 0
    replaced_dates = {field: 0 for field in DATE_FIELDS}
    replaced_links = {field: 0 for field in LINK_FIELDS}
    seen_actors: set[str] = set()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=RAW_FIELDS)
        writer.writeheader()

        for row in iter_actor_rows(input_path):
            total_rows += 1
            if total_rows % MONITOR_CHECKPOINT_EVERY == 0:
                print(f"    … {total_rows:,} rows")
                if use_monitor:
                    monitor_state = monitor_module.update_monitor_state(
                        state=monitor_state,
                        context=f"Patched {total_rows:,} rows so far",
                        print_console=True,
                    )

            rec = {field: normalise(row.get(field, "")) for field in RAW_FIELDS}
            actor_uri = rec["actor"]
            if actor_uri:
                seen_actors.add(actor_uri)

            if not rec["actor_name"] and actor_uri:
                derived_name = name_overlay.get(actor_uri, "")
                if derived_name:
                    rec["actor_name"] = derived_name
                    filled_actor_name += 1

            if actor_uri:
                actor_dates = dates_overlay.get(actor_uri)
                if actor_dates:
                    for field, harmonised_value in actor_dates.items():
                        rec[field] = harmonised_value
                        replaced_dates[field] += 1

            if actor_uri:
                for field in LINK_FIELDS:
                    raw_val = rec[field]
                    if not raw_val:
                        continue
                    harmonised_value = links_overlay.get((actor_uri, field, raw_val))
                    if harmonised_value:
                        rec[field] = harmonised_value
                        replaced_links[field] += 1

            writer.writerow(rec)

    report = {
        "total_raw_rows": total_rows,
        "unique_actors": len(seen_actors),
        "harmonised_fields": {
            "actor_name": {
                "status": "harmonised" if name_overlay else "pending (source not found)",
                "rows_filled": filled_actor_name,
            },
            "actor_dates": {
                "status": "harmonised" if dates_overlay else "pending (source not found)",
                "rows_replaced": replaced_dates,
            },
            "external_links": {
                "status": "harmonised" if links_overlay else "pending (source not found)",
                "rows_replaced": replaced_links,
            },
        },
        "raw_fields_pending_harmonisation": [],
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actors-ready assembly run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {total_rows:,} rows ({len(seen_actors):,} actors) -> {output_path}")
    print(f"  actor_name filled: {filled_actor_name:,}")
    for field, count in replaced_dates.items():
        print(f"  {field} replaced: {count:,}")
    for field, count in replaced_links.items():
        print(f"  {field} replaced: {count:,}")
    print(f"✓ Report -> {report_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the ready actors dataset from raw data + all "
                    "available actors-side harmonisation outputs "
                    "(row-level granularity preserved; deduplication is module 5's job)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",                  default=INPUT_DEFAULT)
    parser.add_argument("--actor-name-harmonised",  default=ACTOR_NAME_HARMONISED_DEFAULT)
    parser.add_argument("--actor-dates-harmonised", default=ACTOR_DATES_HARMONISED_DEFAULT)
    parser.add_argument("--external-links-harmonised", default=EXTERNAL_LINKS_HARMONISED_DEFAULT)
    parser.add_argument("--output",                 default=OUTPUT_DEFAULT)
    parser.add_argument("--report",                 default=REPORT_DEFAULT)
    parser.add_argument("--monitor-script",         default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",             action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.actor_name_harmonised, args.actor_dates_harmonised,
        args.output, args.report,
        external_links_harmonised_path=args.external_links_harmonised,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
