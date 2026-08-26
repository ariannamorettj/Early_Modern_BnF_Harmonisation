#!/usr/bin/env python3
"""
roles_enricher.py  –  Step 1 of the BnF subset-optimisation pipeline.

Scans the edition dataset and builds a mapping:
    actor_id -> { role -> [edition_id, ...] }

Optionally filters editions by a year range (--year-from / --year-to).

Outputs
-------
1. id_roles/actor_roles_links.csv
       actor, role_edition_map, roles
       where role_edition_map encodes  "author:id1,id2;editor:id3"

2. report/multi_role_actors.json
       { actor_id: { role1: [ed1, ed2], role2: [...] }, ... }
       Only actors that appeared under more than one role are included.
"""

import os
import csv
import sys
import json
import zipfile
import argparse
from collections import defaultdict
from typing import Dict, Set, List, Tuple

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or U+2192 (→) used below,
# raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Default paths ─────────────────────────────────────────────────────────────
ACTORS_ZIP_DEFAULT  = "data/bnf_agents_data_querying/actor_queries_results.zip"
EDITIONS_ZIP_DEFAULT = "data/bnf_edition_data/bnf_edition_data_raw.zip"
OUTPUT_DIR_DEFAULT  = "id_roles"
REPORT_DIR_DEFAULT  = "report"
OUTPUT_FILENAME_DEFAULT = "actor_roles_links.csv"
MULTI_ROLE_FILENAME = "multi_role_actors.json"

# Role columns present in the editions dataset
ROLE_FIELDS = ["author", "editor", "translator", "publisher_2", "illustrator"]

# Year columns to inspect when filtering
YEAR_FIELDS = ["year_first", "year_range"]

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def iter_csv_in_zip(zip_path: str):
    """Yield (filename, row_dict) for every CSV row inside a ZIP."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name, "r") as f:
                lines = (line.decode("utf-8", errors="replace") for line in f)
                reader = csv.DictReader(lines)
                for row in reader:
                    yield name, row


def extract_year(row: dict) -> int | None:
    """
    Try to extract a 4-digit publication year from year_first or year_range.
    Returns None if no valid year is found.
    """
    for field in YEAR_FIELDS:
        raw = normalise(row.get(field, ""))
        if not raw:
            continue
        # year_range can be "1747" or "1747/1748" – take first token
        token = raw.split("/")[0].strip()
        if token.isdigit() and len(token) == 4:
            return int(token)
    return None


def year_in_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    """Return True if year passes the optional range filter."""
    if year is None:
        # If we cannot determine the year and a filter is active, exclude.
        return (year_from is None) and (year_to is None)
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


# ── Core logic ────────────────────────────────────────────────────────────────

def collect_actor_ids(actors_zip_path: str) -> Set[str]:
    ids: Set[str] = set()
    for _, row in iter_csv_in_zip(actors_zip_path):
        aid = normalise(row.get("actor"))
        if aid:
            ids.add(aid)
    return ids


def build_actor_role_edition_map(
    actors_zip_path: str,
    editions_zip_path: str,
    year_from: int | None,
    year_to: int | None,
) -> Dict[str, Dict[str, List[str]]]:
    """
    Returns  { actor_id: { role: [edition_id, ...] } }
    """
    actor_ids = collect_actor_ids(actors_zip_path)
    print(f"  Known actor IDs: {len(actor_ids):,}")

    # actor -> role -> set of edition ids
    mapping: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    filtered_out = 0
    matched = 0

    for _, row in iter_csv_in_zip(editions_zip_path):
        year = extract_year(row)
        if not year_in_range(year, year_from, year_to):
            filtered_out += 1
            continue

        edition_id = normalise(row.get("bnf_id")) or normalise(row.get("edition"))
        if not edition_id:
            continue

        for role in ROLE_FIELDS:
            actor_id = normalise(row.get(role, ""))
            if actor_id and actor_id in actor_ids:
                mapping[actor_id][role].add(edition_id)
                matched += 1

    print(f"  Editions filtered out by year range: {filtered_out:,}")
    print(f"  Actor-edition-role matches: {matched:,}")

    # Convert sets to sorted lists
    return {
        actor: {role: sorted(eds) for role, eds in roles.items()}
        for actor, roles in mapping.items()
    }


def encode_role_edition_map(role_map: Dict[str, List[str]]) -> str:
    """
    Encode  { "author": ["id1","id2"], "editor": ["id3"] }
    as      "author:id1,id2;editor:id3"
    """
    parts = []
    for role in sorted(role_map.keys()):
        ids = ",".join(role_map[role])
        parts.append(f"{role}:{ids}")
    return ";".join(parts)


# ── Output writers ────────────────────────────────────────────────────────────

def write_roles_csv(
    actor_role_map: Dict[str, Dict[str, List[str]]],
    output_dir: str,
    output_filename: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, output_filename)

    fieldnames = ["actor", "role_edition_map", "roles"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for actor_id in sorted(actor_role_map.keys()):
            role_map = actor_role_map[actor_id]
            writer.writerow({
                "actor": actor_id,
                "role_edition_map": encode_role_edition_map(role_map),
                "roles": ";".join(sorted(role_map.keys())),
            })
    return out_path


def write_multi_role_report(
    actor_role_map: Dict[str, Dict[str, List[str]]],
    report_dir: str,
) -> str:
    os.makedirs(report_dir, exist_ok=True)
    out_path = os.path.join(report_dir, MULTI_ROLE_FILENAME)

    multi = {
        actor: roles
        for actor, roles in actor_role_map.items()
        if len(roles) > 1
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(multi, f, ensure_ascii=False, indent=2)

    print(f"  Actors with multiple roles: {len(multi):,}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build actor→role→editions links from BnF actor and edition datasets."
    )
    parser.add_argument("--actors-zip",    default=ACTORS_ZIP_DEFAULT)
    parser.add_argument("--editions-zip",  default=EDITIONS_ZIP_DEFAULT)
    parser.add_argument("--output-dir",    default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--report-dir",    default=REPORT_DIR_DEFAULT)
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--year-from",     type=int, default=None,
                        help="Include only editions published from this year (inclusive).")
    parser.add_argument("--year-to",       type=int, default=None,
                        help="Include only editions published up to this year (inclusive).")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("STEP 1 – roles_enricher.py")
    if args.year_from or args.year_to:
        print(f"  Year filter: {args.year_from or '?'} – {args.year_to or '?'}")
    print("=" * 60)

    actor_role_map = build_actor_role_edition_map(
        actors_zip_path=args.actors_zip,
        editions_zip_path=args.editions_zip,
        year_from=args.year_from,
        year_to=args.year_to,
    )

    csv_path  = write_roles_csv(actor_role_map, args.output_dir, args.output_filename)
    json_path = write_multi_role_report(actor_role_map, args.report_dir)

    print(f"\n  ✓ Roles CSV  → {csv_path}")
    print(f"  ✓ Multi-role report → {json_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()


"""
── Usage examples ──────────────────────────────────────────────────────────────

Default (full dataset):
    python 05_subset_optimisation/roles_enricher.py

Medieval period only (up to 1450):
    python 05_subset_optimisation/roles_enricher.py --year-to 1450

Custom year range:
    python 05_subset_optimisation/roles_enricher.py --year-from 1500 --year-to 1600

Custom paths:
    python 05_subset_optimisation/roles_enricher.py \\
        --actors-zip  data/bnf_agents_data_querying/actor_queries_results.zip \\
        --editions-zip data/bnf_edition_data/bnf_edition_data_raw.zip \\
        --output-dir  05_subset_optimisation/id_roles \\
        --report-dir  05_subset_optimisation/report \\
        --year-from 1000 --year-to 1450
"""
