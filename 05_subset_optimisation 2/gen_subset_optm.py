#!/usr/bin/env python3
"""
gen_subset_optm.py  –  Step 2 of the BnF subset-optimisation pipeline.

Reads the actor ZIP dataset and the roles mapping produced by roles_enricher.py,
then produces:

1. output/bnf_actors_optimised.csv          – full dataset, one row per actor
2. output/bnf_actors_optimised_minimal.csv  – BnF_ID + actor_name + link_exact + link_close
3. report/summary_report.txt                – statistics
4. report/dedup_report.json                 – deduplication detail (when --dedup-field is used)

Key parameters
--------------
--year-from / --year-to
    If provided, only actors that appear in at least one edition within the
    given year range (as determined by roles_enricher.py) are retained.
    Requires --roles-mapping to carry year-filtered data.

--dedup-field FIELD
    Deduplicate rows that share the same value on FIELD.
    - Rows with identical values on ALL other fields collapse into one.
    - Rows that differ on some other field: the differing values are
      collected and joined with ", " in that field's cell.
    - A JSON report lists every deduplication group where at least one
      field carried more than one distinct value.

Without --dedup-field the script simply aggregates by BnF_ID (original
behaviour), treating every field as potentially multi-valued ("; "-joined).

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by module 1's query_agents.R / query_editions.R and by the
06_mapping scripts: periodic checkpoints while reading the actor ZIP, plus a
final checkpoint on completion. Reports land in
00_monitor/report/gen_subset_optm_<timestamp>_py.txt. Disable with
--no-monitor.
"""

import os
import csv
import sys
import json
import zipfile
import argparse
import importlib.util
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

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

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_ZIP_DEFAULT      = "data/bnf_agents_data_querying/actor_queries_results.zip"
ROLES_MAPPING_DEFAULT  = "id_roles/actor_roles_links.csv"
ACTOR_NAME_HARMONISED_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "01_heuristic_rules/output/actor_name_harmonised.csv"
)
OUTPUT_DIR_DEFAULT     = "output"
REPORT_DIR_DEFAULT     = "report"
OUTPUT_FILENAME        = "bnf_actors_optimised.csv"
MINIMAL_FILENAME       = "bnf_actors_optimised_minimal.csv"
REPORT_FILENAME        = "summary_report.txt"
DEDUP_REPORT_FILENAME  = "dedup_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 20_000  # matches the existing progress-print cadence

ALL_DATA_FIELDS = [
    "actor_name", "actor_first_name", "actor_last_name",
    "actor_birth", "actor_death", "actor_start", "actor_end",
    "first_year", "entity_type", "actor_gender",
    "actor_country", "actor_language",
    "actor_link_exact", "actor_link_close",
]

# actor_profession is REMOVED from ALL_DATA_FIELDS – it is now derived
# from the roles mapping and stored as role_edition_map / roles.

OUTPUT_FIELDS = ["BnF_ID"] + ALL_DATA_FIELDS + ["role_edition_map", "roles"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def iter_csv_in_zip(zip_path: str):
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name, "r") as f:
                lines = (line.decode("utf-8", errors="replace") for line in f)
                reader = csv.DictReader(lines)
                for row in reader:
                    yield name, row


# ── Roles mapping loader ──────────────────────────────────────────────────────

def load_roles_mapping(mapping_path: str) -> Dict[str, Dict[str, str]]:
    """
    Reads actor_roles_links.csv (produced by roles_enricher.py).
    Columns expected: actor, role_edition_map, roles
    Returns { actor_id: { "role_edition_map": "...", "roles": "..." } }
    """
    mapping: Dict[str, Dict[str, str]] = {}
    if not mapping_path or not os.path.exists(mapping_path):
        print(f"  [warn] Roles mapping not found at {mapping_path!r}. Skipping enrichment.")
        return mapping

    print(f"  Loading roles mapping from: {mapping_path}")
    with open(mapping_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = normalise(row.get("actor", ""))
            if not aid:
                continue
            mapping[aid] = {
                "role_edition_map": normalise(row.get("role_edition_map", "")),
                "roles":            normalise(row.get("roles", "")),
            }
    print(f"  Loaded {len(mapping):,} actors from roles mapping.")
    return mapping


# ── Module-4 actor_name harmonised mapping loader ──────────────────────────────

def load_actor_name_harmonised(path: str) -> Dict[str, str]:
    """
    Reads the output of module 4's name_normaliser.py
    (actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence)
    and returns {actor_uri: actor_name_harmonised}, restricted to rows where a
    name was actually derived (correction_type == "derived_from_first_last").
    Rows with correction_type == "none" carry no new information (actor_name
    was already present) and are not needed here.
    """
    mapping: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        print(f"  [warn] Actor-name harmonised mapping not found at {path!r}. "
             f"Skipping actor_name fill (run name_normaliser.py first).")
        return mapping

    print(f"  Loading actor_name harmonised mapping from: {path}")
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("correction_type") != "derived_from_first_last":
                continue
            uri  = normalise(row.get("actor_uri", ""))
            name = normalise(row.get("actor_name_harmonised", ""))
            if uri and name:
                mapping[uri] = name
    print(f"  Loaded {len(mapping):,} derived actor names.")
    return mapping


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and the 06_mapping scripts."""
    project_root = Path(__file__).resolve().parents[1]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_gen_subset_optm", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Actor data reader ─────────────────────────────────────────────────────────

def read_actor_data(
    zip_path: str,
    roles_mapping: Dict[str, Dict[str, str]],
    year_filter_active: bool,
    actor_name_harmonised: Dict[str, str] | None = None,
    monitor_module=None,
    monitor_state=None,
) -> Tuple[List[Dict[str, str]], Dict[str, Any], int, int, int, Any]:
    """
    Reads the actor ZIP and aggregates by BnF_ID.

    If year_filter_active is True, only actors present in roles_mapping
    (which was built from year-filtered editions) are retained.

    If actor_name_harmonised is given ({actor_uri: derived_name}, from
    module 4's name_normaliser.py) and an actor's aggregated actor_name is
    empty, the derived name is used to fill it.

    If monitor_module is given, a checkpoint is written every
    MONITOR_CHECKPOINT_EVERY rows (same cadence as the existing progress
    print below).

    Returns (flat_records, merge_tracking, total_rows, duplicate_rows,
    filled_from_harmonised_count, monitor_state)
    """
    # actor_id -> field -> set of values
    actors_db: Dict[str, Dict[str, Set[str]]] = {}
    merge_tracking: Dict[str, Dict[str, Any]] = {}
    row_signatures: Dict[str, List[str]] = {}

    total_rows = 0
    dup_rows   = 0

    print(f"  Reading actor ZIP: {zip_path}")
    for _, row in iter_csv_in_zip(zip_path):
        total_rows += 1
        if total_rows % MONITOR_CHECKPOINT_EVERY == 0:
            print(f"    … {total_rows:,} rows, {len(actors_db):,} actors")
            if monitor_module is not None:
                monitor_state = monitor_module.update_monitor_state(
                    state=monitor_state,
                    context=f"Read {total_rows:,} rows, {len(actors_db):,} actors so far",
                    print_console=True,
                )

        bnf_id = normalise(row.get("actor", ""))
        if not bnf_id:
            continue

        # Year filter: skip actors not present in the roles mapping
        if year_filter_active and bnf_id not in roles_mapping:
            continue

        # Duplicate detection
        sig = "|".join(normalise(row.get(f, "")) for f in ALL_DATA_FIELDS)
        if bnf_id in row_signatures:
            if sig in row_signatures[bnf_id]:
                dup_rows += 1
                continue
            row_signatures[bnf_id].append(sig)
        else:
            row_signatures[bnf_id] = [sig]

        if bnf_id not in actors_db:
            actors_db[bnf_id] = {f: set() for f in ALL_DATA_FIELDS}
            merge_tracking[bnf_id] = {"merge_count": 0, "fields_with_variations": {}}

        entry    = actors_db[bnf_id]
        tracking = merge_tracking[bnf_id]
        row_varies = False

        for field in ALL_DATA_FIELDS:
            val = normalise(row.get(field, ""))
            if val:
                if val not in entry[field] and entry[field]:
                    row_varies = True
                    tracking["fields_with_variations"].setdefault(field, []).append(val)
                entry[field].add(val)

        if row_varies:
            tracking["merge_count"] += 1

    print(f"  Total rows: {total_rows:,}  |  Duplicates: {dup_rows:,}  |  Unique actors: {len(actors_db):,}")

    # Flatten
    flat: List[Dict[str, str]] = []
    filled_from_harmonised = 0
    for bnf_id, fields in sorted(actors_db.items()):
        rec: Dict[str, str] = {"BnF_ID": bnf_id}
        for f in ALL_DATA_FIELDS:
            rec[f] = "; ".join(sorted(fields[f]))
        if not rec["actor_name"] and actor_name_harmonised:
            derived_name = actor_name_harmonised.get(bnf_id, "")
            if derived_name:
                rec["actor_name"] = derived_name
                filled_from_harmonised += 1
        rm = roles_mapping.get(bnf_id, {})
        rec["role_edition_map"] = rm.get("role_edition_map", "")
        rec["roles"]            = rm.get("roles", "")
        flat.append(rec)

    if actor_name_harmonised:
        print(f"  Filled actor_name from module-4 harmonised mapping: "
             f"{filled_from_harmonised:,} actor(s)")

    return flat, merge_tracking, total_rows, dup_rows, filled_from_harmonised, monitor_state


# ── Deduplication ─────────────────────────────────────────────────────────────

def dedup_records(
    records: List[Dict[str, str]],
    dedup_field: str,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """
    Collapse rows that share the same value on `dedup_field`.

    - If all other fields are identical across a group → single row.
    - If some fields differ → values are joined with ", " (sorted, unique).

    Returns (deduplicated_records, dedup_report)
    """
    if dedup_field not in OUTPUT_FIELDS and dedup_field not in ALL_DATA_FIELDS:
        raise ValueError(f"--dedup-field {dedup_field!r} is not a recognised column.")

    # group by dedup_field value
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for rec in records:
        key = rec.get(dedup_field, "")
        groups[key].append(rec)

    dedup_report: Dict[str, Any] = {}
    out_records: List[Dict[str, str]] = []

    all_fields = OUTPUT_FIELDS  # includes BnF_ID, data fields, role columns

    for key, group in groups.items():
        if len(group) == 1:
            out_records.append(group[0])
            continue

        # Collect values per field across all rows in the group
        field_values: Dict[str, Set[str]] = {f: set() for f in all_fields}
        for row in group:
            for f in all_fields:
                v = row.get(f, "")
                if v:
                    field_values[f].add(v)

        # Build merged record
        merged: Dict[str, str] = {}
        for f in all_fields:
            vals = sorted(field_values[f])
            merged[f] = ", ".join(vals)

        out_records.append(merged)

        # Report: only fields with more than one distinct value
        variations = {
            f: sorted(field_values[f])
            for f in all_fields
            if len(field_values[f]) > 1 and f != dedup_field
        }
        if variations:
            dedup_report[key] = variations

    return out_records, dedup_report


# ── Output writers ────────────────────────────────────────────────────────────

def write_csv(records: List[Dict[str, str]], path: str, fields: List[str]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def write_json(data: Any, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_report(
    records: List[Dict[str, str]],
    merge_tracking: Dict[str, Any],
    total_rows: int,
    dup_rows: int,
    report_path: str,
    dedup_field: str | None,
    filled_from_harmonised: int = 0,
):
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    n = len(records)
    merged_n = sum(1 for t in merge_tracking.values() if t["fields_with_variations"])

    with open(report_path, "w", encoding="utf-8") as f:
        sep = "=" * 70
        f.write(sep + "\nBnF DATASET OPTIMISATION REPORT\n" + sep + "\n\n")

        f.write("BASIC STATISTICS\n" + "-" * 70 + "\n")
        f.write(f"Total source rows processed : {total_rows:,}\n")
        f.write(f"Exact duplicate rows        : {dup_rows:,}\n")
        f.write(f"Net rows (excl. duplicates) : {total_rows - dup_rows:,}\n")
        f.write(f"Unique actors in output     : {n:,}\n")
        if dedup_field:
            f.write(f"Deduplication field         : {dedup_field}\n")
        f.write(f"Actors with merged records  : {merged_n:,}\n")
        rate = merged_n / n * 100 if n else 0
        f.write(f"Merge rate                  : {rate:.2f}%\n")
        f.write(f"actor_name filled from module-4 mapping : {filled_from_harmonised:,}\n\n")

        f.write(sep + "\nFIELD STATISTICS\n" + "-" * 70 + "\n")
        f.write(f"{'Field':<25} {'Filled':>8}  {'Fill%':>7}  {'Avg/actor':>10}\n")
        f.write("-" * 70 + "\n")
        for field in ALL_DATA_FIELDS + ["role_edition_map", "roles"]:
            filled = sum(1 for r in records if r.get(field, ""))
            items  = sum(
                len([x for x in r.get(field, "").split(";") if x.strip()])
                for r in records
            )
            fill_pct = filled / n * 100 if n else 0
            avg      = items / n if n else 0
            f.write(f"{field:<25} {filled:>8,}  {fill_pct:>6.1f}%  {avg:>10.4f}\n")

        # Variation detail
        var_fields = defaultdict(int)
        for t in merge_tracking.values():
            for fld in t["fields_with_variations"]:
                var_fields[fld] += 1
        if var_fields:
            f.write("\n" + sep + "\nFIELDS WITH VARIATIONS\n" + "-" * 70 + "\n")
            for fld, cnt in sorted(var_fields.items(), key=lambda x: -x[1]):
                f.write(f"  {fld:<25} {cnt:,} entities\n")

        f.write("\n" + sep + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BnF Actor Dataset Optimizer – Step 2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input-zip",      default=INPUT_ZIP_DEFAULT)
    parser.add_argument("--roles-mapping",  default=ROLES_MAPPING_DEFAULT)
    parser.add_argument("--actor-name-harmonised", default=ACTOR_NAME_HARMONISED_DEFAULT,
                        help="Path to module 4's actor_name_harmonised.csv "
                             "(fills actor_name when empty). Pass '' to disable.")
    parser.add_argument("--output-dir",     default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--report-dir",     default=REPORT_DIR_DEFAULT)
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    parser.add_argument(
        "--year-from", type=int, default=None,
        help="Retain only actors present in editions from this year.",
    )
    parser.add_argument(
        "--year-to", type=int, default=None,
        help="Retain only actors present in editions up to this year.",
    )
    parser.add_argument(
        "--dedup-field", default=None,
        help=(
            "Collapse rows sharing the same value on this field. "
            "Differing values in other fields are joined with ', '."
        ),
    )
    args = parser.parse_args()

    year_filter_active = (args.year_from is not None) or (args.year_to is not None)

    print("\n" + "=" * 60)
    print("STEP 2 – gen_subset_optm.py")
    if year_filter_active:
        print(f"  Year filter: {args.year_from or '?'} – {args.year_to or '?'}")
    if args.dedup_field:
        print(f"  Dedup field: {args.dedup_field}")
    print("=" * 60)

    roles_mapping = load_roles_mapping(args.roles_mapping)
    actor_name_harmonised = load_actor_name_harmonised(args.actor_name_harmonised)

    use_monitor = not args.no_monitor
    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(args.monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during gen_subset_optm.py execution",
            print_start_message=True,
        )

    records, merge_tracking, total_rows, dup_rows, filled_from_harmonised, monitor_state = read_actor_data(
        zip_path=args.input_zip,
        roles_mapping=roles_mapping,
        year_filter_active=year_filter_active,
        actor_name_harmonised=actor_name_harmonised,
        monitor_module=monitor_module,
        monitor_state=monitor_state,
    )

    dedup_report = {}
    if args.dedup_field:
        print(f"\n  Deduplicating on field: {args.dedup_field!r} …")
        records, dedup_report = dedup_records(records, args.dedup_field)
        print(f"  Records after dedup: {len(records):,}")

    # ── Write full CSV ────────────────────────────────────────────────────────
    full_path = os.path.join(args.output_dir, args.output_filename)
    write_csv(records, full_path, OUTPUT_FIELDS)
    print(f"\n  ✓ Full dataset      → {full_path}")

    # ── Write minimal CSV ─────────────────────────────────────────────────────
    minimal_fields = ["BnF_ID", "actor_name", "actor_link_exact", "actor_link_close"]
    minimal_path   = os.path.join(args.output_dir, MINIMAL_FILENAME)
    write_csv(records, minimal_path, minimal_fields)
    print(f"  ✓ Minimal dataset   → {minimal_path}")

    # ── Write dedup report ────────────────────────────────────────────────────
    if args.dedup_field:
        dedup_path = os.path.join(args.report_dir, DEDUP_REPORT_FILENAME)
        write_json(dedup_report, dedup_path)
        print(f"  ✓ Dedup report      → {dedup_path}  ({len(dedup_report):,} groups with variations)")

    # ── Write merge-tracking JSON ─────────────────────────────────────────────
    filtered_tracking = {
        k: v for k, v in merge_tracking.items() if v["fields_with_variations"]
    }
    merge_path = os.path.join(args.report_dir, "merged_entities.json")
    write_json(filtered_tracking, merge_path)
    print(f"  ✓ Merge tracking    → {merge_path}")

    # ── Write stats report ────────────────────────────────────────────────────
    report_path = os.path.join(args.report_dir, REPORT_FILENAME)
    generate_report(records, merge_tracking, total_rows, dup_rows,
                    report_path, args.dedup_field, filled_from_harmonised)
    print(f"  ✓ Stats report      → {report_path}")

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed subset-optimisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print("\n" + "=" * 60)
    print("COMPLETED SUCCESSFULLY")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()


"""
── Usage examples ──────────────────────────────────────────────────────────────

Default (full dataset, no dedup, no year filter):
    python 05_subset_optimisation/gen_subset_optm.py

Medieval actors only (roles_mapping must have been built with --year-to 1450):
    python 05_subset_optimisation/gen_subset_optm.py \\
        --year-to 1450 \\
        --roles-mapping 05_subset_optimisation/id_roles/actor_roles_links.csv

With deduplication on actor_name:
    python 05_subset_optimisation/gen_subset_optm.py \\
        --dedup-field actor_name

Full custom run – medieval, dedup on BnF_ID:
    python 05_subset_optimisation/gen_subset_optm.py \\
        --input-zip  data/bnf_agents_data_querying/actor_queries_results.zip \\
        --roles-mapping 05_subset_optimisation/id_roles/actor_roles_links.csv \\
        --output-dir 05_subset_optimisation/output \\
        --report-dir 05_subset_optimisation/report \\
        --year-from 1000 --year-to 1450 \\
        --dedup-field BnF_ID
"""
