#!/usr/bin/env python3
"""
name_normaliser.py  —  Module 04, actor_name heuristic rules.

Scope of this implementation
-----------------------------
Only ONE rule is implemented so far: derive_from_first_last.

    When actor_name is empty/missing but actor_first_name and/or
    actor_last_name are present, derive actor_name from them. This fixes
    cases such as "Lucretius", whose BnF record carries the name only in
    actor_last_name while actor_name and actor_first_name are NA — making
    the actor effectively unsearchable by name downstream.

    When actor_name is already present, this script currently passes it
    through unchanged (correction_type = "none").

    When all three fields are empty, the row is left empty
    (correction_type = "unresolved_missing") — nothing to derive from.

All OTHER anomalies documented in this module's README (initials-only,
embedded titles/roles, aliases, multi-value cells, bracket/encoding noise,
Roman numerals — see 04_harmonisation_and_evaluation/README.md section 3.1)
are NOT implemented yet. They are intentionally left as future incremental
work rather than attempted here.

Input
-----
Raw actor dataset (CSV, or ZIP containing one or more CSVs) with columns:
    actor, actor_name, actor_first_name, actor_last_name
e.g. 01_data_retrieval/02_actors/actors_data/actor_data.csv (module 1's raw
acquisition output).

Each actor URI typically appears on multiple rows in that raw dataset (one
row per external-link binding returned by the SPARQL acquisition query), and
actor_name / actor_first_name / actor_last_name are repeated identically
across an actor's rows. This script therefore deduplicates by actor URI
before applying the rule — the output has exactly one row per unique actor.

Output (actor_name_harmonised.csv)
-----------------------------------
    actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by module 1's query_agents.R / query_editions.R and by
06_mapping/02_map_wikidata.py: one checkpoint per processed actor, plus a
final checkpoint on completion. Reports land in
00_monitor/report/name_normaliser_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python name_normaliser.py \\
    --input  01_data_retrieval/02_actors/actors_data/actor_data.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output

# disable the monitor report
python name_normaliser.py --no-monitor
"""

import os, csv, sys, zipfile, argparse, importlib.util
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
OUTPUT_DIR_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output"
)
OUTPUT_FILENAME_DEFAULT = "actor_name_harmonised.csv"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"

OUTPUT_FIELDS = [
    "actor_uri", "actor_name_original", "actor_name_harmonised",
    "correction_type", "confidence",
]


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and 06_mapping's scripts."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_name_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, actor_uri, correction_type):
    if monitor_module is None:
        return monitor_state
    context = (f"Processed actor {actor_uri} (index {index}/{total}) "
              f"- correction_type={correction_type}")
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


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


def derive_actor_name(actor_name: str, first_name: str, last_name: str) -> dict:
    """
    Apply the derive_from_first_last rule to one actor's already-deduplicated
    field values (all three already normalise()'d — empty string means
    absent).

    Returns a dict with keys:
        - harmonised: str
        - correction_type: str ('none', 'derived_from_first_last',
          or 'unresolved_missing')
        - confidence: str ('high' or 'low')
    """
    if actor_name:
        return {"harmonised": actor_name, "correction_type": "none", "confidence": "high"}

    derived = " ".join(part for part in (first_name, last_name) if part)
    if derived:
        return {
            "harmonised": derived,
            "correction_type": "derived_from_first_last",
            "confidence": "high",
        }

    return {"harmonised": "", "correction_type": "unresolved_missing", "confidence": "low"}


def collect_unique_actors(input_path: str) -> dict[str, dict[str, str]]:
    """
    Deduplicate raw rows by actor URI, keeping the first non-empty value seen
    for actor_name / actor_first_name / actor_last_name per actor.
    """
    actors: dict[str, dict[str, str]] = {}
    for row in iter_actor_rows(input_path):
        actor_uri = normalise(row.get("actor", ""))
        if not actor_uri:
            continue
        entry = actors.setdefault(actor_uri, {
            "actor_name": "", "actor_first_name": "", "actor_last_name": "",
        })
        for field in ("actor_name", "actor_first_name", "actor_last_name"):
            if not entry[field]:
                val = normalise(row.get(field, ""))
                if val:
                    entry[field] = val
    return actors


def run(input_path: str, output_dir: str,
       output_filename: str = OUTPUT_FILENAME_DEFAULT,
       use_monitor: bool = False,
       monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:
    """
    Load the input CSV/ZIP, apply derive_actor_name() to each unique actor,
    and write the output mapping CSV. Returns the output file path.
    """
    actors = collect_unique_actors(input_path)
    total = len(actors)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    stats = {"none": 0, "derived_from_first_last": 0, "unresolved_missing": 0}

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during name_normaliser.py execution",
            print_start_message=True,
        )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, (actor_uri, fields) in enumerate(sorted(actors.items())):
            result = derive_actor_name(
                fields["actor_name"], fields["actor_first_name"], fields["actor_last_name"])
            stats[result["correction_type"]] = stats.get(result["correction_type"], 0) + 1
            writer.writerow({
                "actor_uri": actor_uri,
                "actor_name_original": fields["actor_name"],
                "actor_name_harmonised": result["harmonised"],
                "correction_type": result["correction_type"],
                "confidence": result["confidence"],
            })
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i + 1, total,
                actor_uri, result["correction_type"])

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actor_name harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {len(actors):,} actors -> {output_path}")
    print(f"  derived_from_first_last : {stats['derived_from_first_last']:,}")
    print(f"  none (already present)  : {stats['none']:,}")
    print(f"  unresolved_missing      : {stats['unresolved_missing']:,}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_name heuristic normaliser "
                    "(derive-from-first-last rule only — see module docstring)")
    parser.add_argument("--input", default=INPUT_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Output directory")
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.output, args.output_filename,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
