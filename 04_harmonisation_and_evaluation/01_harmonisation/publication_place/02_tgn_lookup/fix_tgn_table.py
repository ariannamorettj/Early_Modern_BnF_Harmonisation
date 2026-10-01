#!/usr/bin/env python3
"""Apply the corrections found by verify_tgn_table.py to the place table.

Two kinds of error are corrected, both confirmed against the Getty TGN:

core_homonym     the table points at a minor homonym (a hamlet called
                 "Bordeaux" in Centre-Val de Loire) while a settlement with
                 the same name in the same country belongs to TGN's core
                 range (the city): the tgn_id, longitude and latitude of
                 every row of that place are replaced with the core record's.
coords_mismatch  the table's coordinates are TGN's with latitude and
                 longitude swapped (Philadelphia): they are swapped back.
                 Any other coordinate difference is reported, not changed.

manual_override  data_work/tgn_manual_overrides.csv fixes the TGN record of a
                 place outright, with the reason. It is for cases the
                 verification cannot settle on its own (several core
                 settlements share the name: Beauvais) and wins over the
                 automatic corrections.

Label-only differences (Liége / Liège) and rows without a TGN id are left
alone. Every change is appended to report/tgn_table_corrections.csv
(before/after). Only the corrected lines of the table are rewritten; every
other line is kept byte for byte, so re-running is a no-op once the table
is fixed and the diff shows exactly the corrections.

Usage
-----
python 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/verify_tgn_table.py
python 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/fix_tgn_table.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_DEFAULT = HERE / "data" / "data_work" / "bnf_place_name_harmonisation_table_final.csv"
VERIFICATION_DEFAULT = HERE / "report" / "tgn_table_verification.csv"
LOG_DEFAULT = HERE / "report" / "tgn_table_corrections.csv"
OVERRIDES_DEFAULT = HERE / "data" / "data_work" / "tgn_manual_overrides.csv"
COORD_TOLERANCE = 0.01
LOG_FIELDS = ["city_harmonised", "publication_place", "publication_country", "correction",
              "tgn_id_before", "tgn_id_after", "longitude_before", "longitude_after",
              "latitude_before", "latitude_after"]
CRLF = chr(13) + chr(10)
LF = chr(10)


def close(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) <= COORD_TOLERANCE
    except ValueError:
        return False


def plan_corrections(verification_rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    """(place, country, tgn iri) -> {correction, tgn_id, longitude, latitude}."""
    plan = {}
    for v in verification_rows:
        flags = v["flags"].split(";") if v["flags"] else []
        key = (v["publication_place"], v["publication_country"], v["tgn_id"])
        if "core_homonym" in flags and v["proposed_tgn_id"] and v["proposed_lat"]:
            plan[key] = {"correction": "core_homonym", "tgn_id": v["proposed_tgn_id"],
                         "longitude": v["proposed_long"], "latitude": v["proposed_lat"]}
        elif ("coords_mismatch" in flags and close(v["table_lat"], v["tgn_long"])
              and close(v["table_long"], v["tgn_lat"])):
            plan[key] = {"correction": "swapped_coordinates", "tgn_id": v["tgn_id"],
                         "longitude": v["tgn_long"], "latitude": v["tgn_lat"]}
        if key in plan:
            # The report describes the table as it was when verified: apply a
            # fix only to rows still in that state, so a second run (with the
            # same, now stale, report) changes nothing.
            plan[key]["expected"] = (v["table_long"], v["table_lat"])
    return plan


def load_overrides(path: Path) -> dict[tuple[str, str], dict]:
    """(publication_place, publication_country) -> {tgn_id, longitude, latitude}."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {(r["publication_place"], r["publication_country"]):
                {"correction": "manual_override", "tgn_id": r["tgn_id"],
                 "longitude": r["longitude"], "latitude": r["latitude"]}
                for r in csv.DictReader(fh)}


def run(table_path: Path, verification_path: Path, log_path: Path,
        overrides_path: Path = OVERRIDES_DEFAULT) -> list[dict]:
    with open(verification_path, encoding="utf-8", newline="") as fh:
        plan = plan_corrections(list(csv.DictReader(fh)))
    overrides = load_overrides(overrides_path)
    # newline="" keeps each line's own ending, so untouched lines are
    # written back byte for byte.
    with open(table_path, encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    fieldnames = next(csv.reader([lines[0]]))
    log = []
    out_lines = [lines[0]]
    for line in lines[1:]:
        row = dict(zip(fieldnames, next(csv.reader([line]))))
        key = (row["publication_place"], row["publication_country"], row["tgn_id"].strip("<>"))
        override = overrides.get(key[:2])
        if override:
            fix = override if override["tgn_id"] != key[2] else None
        else:
            fix = plan.get(key)
            if fix and not (close(row["longitude"], fix["expected"][0])
                            and close(row["latitude"], fix["expected"][1])):
                fix = None
        if not fix:
            out_lines.append(line)
            continue
        after = {"tgn_id": f"<{fix['tgn_id']}>", "longitude": fix["longitude"], "latitude": fix["latitude"]}
        log.append({"city_harmonised": row["city_harmonised"],
                    "publication_place": row["publication_place"],
                    "publication_country": row["publication_country"],
                    "correction": fix["correction"],
                    "tgn_id_before": row["tgn_id"], "tgn_id_after": after["tgn_id"],
                    "longitude_before": row["longitude"], "longitude_after": after["longitude"],
                    "latitude_before": row["latitude"], "latitude_after": after["latitude"]})
        row.update(after)
        # Same layout as the table: quoted text, unquoted coordinates.
        cells = [f'"{row[f]}"' if f not in ("longitude", "latitude") else row[f] for f in fieldnames]
        out_lines.append(",".join(cells) + (CRLF if line.endswith(CRLF) else LF))

    with open(table_path, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(out_lines)

    if not log:
        # Keep the log of the run that made the corrections.
        print(f"Nothing to correct: {table_path.name} already matches the verification.")
        return log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_log = not log_path.exists()
    with open(log_path, "a", encoding="utf-8", newline="") as fh:  # cumulative history
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new_log:
            writer.writeheader()
        writer.writerows(log)
    places = sorted({(r["publication_place"], r["correction"]) for r in log})
    print(f"Corrected {len(log)} table rows ({len(places)} places) -> {table_path}")
    for place, correction in places:
        print(f"  {place:<20} {correction}")
    print(f"Log -> {log_path}")
    return log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", type=Path, default=TABLE_DEFAULT)
    parser.add_argument("--verification", type=Path, default=VERIFICATION_DEFAULT)
    parser.add_argument("--log", type=Path, default=LOG_DEFAULT)
    args = parser.parse_args()
    run(args.table, args.verification, args.log)


if __name__ == "__main__":
    main()
