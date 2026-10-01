#!/usr/bin/env python3
"""Check the curated place -> TGN table against the Getty TGN itself.

bnf_place_name_harmonisation_table_final.csv maps every place string to one
TGN id. Several TGN places often share a name, and a wrong homonym gives the
right name with the wrong coordinates: "Bordeaux" was mapped to tgn:7659881,
a hamlet in Centre-Val de Loire (48.68, 1.10), instead of the city,
tgn:7008161 (44.84, -0.58), for 1,153 editions.

For every distinct (publication_place, publication_country, tgn_id) in the
table this script asks the Getty SPARQL endpoint for:
  - the chosen record: preferred label, place type, parent string, lat/long;
  - every TGN place whose preferred label is exactly publication_place.
It then flags:
  country_mismatch   the chosen record is not in publication_country;
  coords_mismatch    the table's lat/long differ from TGN's for that id;
  label_mismatch     the chosen record's preferred label is another name;
  query_failed       Getty did not answer (not cached: re-run to retry);
  core_homonym       a same-country homonym belongs to TGN's core range
                     (ids 7000000-7029999, the major historical places)
                     while the chosen id does not: the Bordeaux pattern.
                     Only settlements (inhabited places, cities, ...) count
                     as candidates, and a proposal is made only when exactly
                     one core settlement has the name.
  core_homonym_ambiguous  several core settlements share the name: no
                     proposal; the choice goes to tgn_manual_overrides.csv.
                     The core homonym is proposed as the replacement.

Resilience: every Getty answer is cached in --cache (JSON, rewritten after
each query), so an interrupted run resumes where it stopped and a re-run
queries nothing new. Monitoring: 00_monitor checkpoints every
MONITOR_CHECKPOINT_EVERY places plus a final one (--no-monitor to disable).

Output
------
report/tgn_table_verification.csv   one row per table entry: flags, the
                                    chosen record, the proposed id if any,
                                    and the same-country homonyms.

Usage
-----
python 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/verify_tgn_table.py
"""

from __future__ import annotations

import argparse
import csv
import re
import importlib.util
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_DEFAULT = HERE / "data" / "data_work" / "bnf_place_name_harmonisation_table_final.csv"
CACHE_DEFAULT = HERE / "data" / "data_work" / "tgn_verification_cache.json"
OUTPUT_DEFAULT = HERE / "report" / "tgn_table_verification.csv"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 25
ENDPOINT = "https://vocab.getty.edu/sparql.json"
TGN = "http://vocab.getty.edu/tgn/"
CORE_RANGE = range(7000000, 7030000)
# publication_country values that TGN names differently in parentString.
COUNTRY_ALIASES = {"Great Britain": ["United Kingdom"], "Czechia": ["Czech Republic"],
                   "Russia": ["Russia", "Russian Federation"]}
COORD_TOLERANCE = 0.01
# Only settlements can replace a settlement: TGN's core range also holds
# districts and rivers with the same name (Halle has a "national districts"
# record in it, with coordinates 150 km away).
SETTLEMENT_TYPES = ("inhabited place", "cities", "capitals", "towns", "villages", "municipalit")

PREFIXES = """
PREFIX gvp: <http://vocab.getty.edu/ontology#>
PREFIX xl: <http://www.w3.org/2008/05/skos-xl#>
PREFIX wgs: <http://www.w3.org/2003/01/geo/wgs84_pos#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX luc: <http://www.ontotext.com/owlim/lucene#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""
RECORD_QUERY = PREFIXES + """
SELECT ?label ?type ?parent ?lat ?long WHERE {
  BIND(<%s> AS ?p)
  ?p gvp:prefLabelGVP/xl:literalForm ?label ;
     gvp:placeTypePreferred/gvp:prefLabelGVP/xl:literalForm ?type ;
     gvp:parentString ?parent .
  OPTIONAL { ?p foaf:focus ?f . ?f wgs:lat ?lat ; wgs:long ?long }
} LIMIT 1"""
HOMONYM_QUERY = PREFIXES + """
SELECT ?p ?type ?parent ?lat ?long WHERE {
  ?p luc:term "%s" ; skos:inScheme <http://vocab.getty.edu/tgn/> ;
     gvp:prefLabelGVP/xl:literalForm ?label ;
     gvp:placeTypePreferred/gvp:prefLabelGVP/xl:literalForm ?type ;
     gvp:parentString ?parent .
  FILTER(STR(?label) = "%s")
  OPTIONAL { ?p foaf:focus ?f . ?f wgs:lat ?lat ; wgs:long ?long }
} LIMIT 100"""

FIELDS = ["publication_place", "publication_country", "tgn_id", "flags",
          "tgn_label", "tgn_type", "tgn_parent", "tgn_lat", "tgn_long",
          "table_lat", "table_long", "proposed_tgn_id", "proposed_parent",
          "proposed_lat", "proposed_long", "same_country_homonyms", "place_strings"]


def sparql(query: str, sleep: float) -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query}, quote_via=urllib.parse.quote)
    # Without an explicit Accept header Getty's endpoint answers HTTP 400.
    request = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as resp:
                data = json.load(resp)
            time.sleep(sleep)
            return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]
        except Exception as exc:  # network hiccup: back off, then retry
            if attempt == 3:
                raise
            print(f"  [retry {attempt + 1}] {exc}")
            time.sleep(5 * (attempt + 1))
    return []


def lucene_term(label: str) -> str:
    """Longest word of the label: Lucene syntax chokes on quotes, hyphens and
    apostrophes (HTTP 500), and the exact-label FILTER does the real match."""
    words = re.findall(r"\w+", label)
    return max(words, key=len) if words else label


def tgn_number(iri: str) -> int:
    try:
        return int(iri.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        return -1


def in_country(parent: str, country: str) -> bool:
    names = [country] + COUNTRY_ALIASES.get(country, [])
    return any(f", {n}," in f", {parent}," for n in names)


def load_cache(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"records": {}, "homonyms": {}}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write never corrupts the cache


def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = HERE.parents[3]
    spec = importlib.util.spec_from_file_location("monitor_verify_tgn", project_root / monitor_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assess(entry: dict, record: dict, homonyms: list[dict]) -> dict:
    """Flags and proposal for one table entry, from cached Getty answers."""
    flags = []
    country = entry["publication_country"]
    chosen = entry["tgn_id"]
    if record:
        if not in_country(record.get("parent", ""), country):
            flags.append("country_mismatch")
        if record.get("label", "") != entry["publication_place"]:
            flags.append("label_mismatch")
        try:
            if (abs(float(record["lat"]) - float(entry["latitude"])) > COORD_TOLERANCE
                    or abs(float(record["long"]) - float(entry["longitude"])) > COORD_TOLERANCE):
                flags.append("coords_mismatch")
        except (KeyError, ValueError):
            pass
    else:
        flags.append("tgn_record_not_found")

    same_country = [h for h in homonyms if in_country(h.get("parent", ""), country)]
    proposal = {}
    if tgn_number(chosen) not in CORE_RANGE:
        core = sorted((h for h in same_country
                       if tgn_number(h["p"]) in CORE_RANGE and h["p"] != chosen
                       and any(t in h.get("type", "") for t in SETTLEMENT_TYPES)),
                      key=lambda h: tgn_number(h["p"]))
        if len(core) == 1:
            flags.append("core_homonym")
            proposal = core[0]
        elif core:
            # Several core settlements share the name (Beauvais: one in
            # Hauts-de-France, one in Essonne): no automatic choice; decide
            # in data_work/tgn_manual_overrides.csv.
            flags.append("core_homonym_ambiguous")
    return {
        "flags": ";".join(flags),
        "tgn_label": record.get("label", ""), "tgn_type": record.get("type", ""),
        "tgn_parent": record.get("parent", ""), "tgn_lat": record.get("lat", ""),
        "tgn_long": record.get("long", ""),
        "proposed_tgn_id": proposal.get("p", ""), "proposed_parent": proposal.get("parent", ""),
        "proposed_lat": proposal.get("lat", ""), "proposed_long": proposal.get("long", ""),
        "same_country_homonyms": " | ".join(f"{h['p'].rsplit('/', 1)[-1]} ({h.get('type', '')}; {h.get('parent', '')})"
                                            for h in sorted(same_country, key=lambda h: tgn_number(h["p"]))),
    }


def run(table_path: Path, cache_path: Path, output_path: Path, sleep: float,
        use_monitor: bool = False) -> Path:
    with open(table_path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    entries: dict[tuple, dict] = {}
    for r in rows:
        tgn = r["tgn_id"].strip("<>")
        key = (r["publication_place"], r["publication_country"], tgn)
        e = entries.setdefault(key, {"publication_place": r["publication_place"],
                                     "publication_country": r["publication_country"],
                                     "tgn_id": tgn, "latitude": r["latitude"],
                                     "longitude": r["longitude"], "place_strings": []})
        e["place_strings"].append(r["city_harmonised"])

    cache = load_cache(cache_path)
    monitor = state = None
    if use_monitor:
        monitor = load_monitor_module()
        state = monitor.start_monitor_state(
            sampling_mode="checkpoint-based updates during verify_tgn_table.py execution",
            print_start_message=True)

    total = len(entries)
    out_rows = []
    for i, entry in enumerate(entries.values(), start=1):
        tgn, label = entry["tgn_id"], entry["publication_place"]
        failed = False
        try:
            if tgn and tgn not in cache["records"]:
                found = sparql(RECORD_QUERY % tgn, sleep)
                cache["records"][tgn] = found[0] if found else {}
                save_cache(cache_path, cache)
            if label not in cache["homonyms"]:
                exact = label.replace("\\", "\\\\").replace('"', '\\"')
                cache["homonyms"][label] = sparql(HOMONYM_QUERY % (lucene_term(label), exact), sleep)
                save_cache(cache_path, cache)
        except Exception as exc:
            # Not cached, so the next run retries this entry.
            print(f"  [query failed] {label}: {exc}")
            failed = True
        result = assess(entry, cache["records"].get(tgn, {}), cache["homonyms"].get(label, []))
        if failed:
            result["flags"] = ";".join(filter(None, ["query_failed", result["flags"]]))
        out_rows.append({**{k: entry[k] for k in ("publication_place", "publication_country", "tgn_id")},
                         **result, "table_lat": entry["latitude"], "table_long": entry["longitude"],
                         "place_strings": "; ".join(sorted(set(entry["place_strings"])))})
        if monitor and (i % MONITOR_CHECKPOINT_EVERY == 0 or i == total):
            state = monitor.update_monitor_state(
                state=state, context=f"Verified place {i}/{total} ({label})", print_console=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(out_rows, key=lambda r: (r["flags"] == "", r["publication_place"])))

    flagged = [r for r in out_rows if r["flags"]]
    print(f"Verified {total} table entries: {len(flagged)} flagged -> {output_path}")
    for flag in ("country_mismatch", "coords_mismatch", "label_mismatch", "core_homonym",
                 "core_homonym_ambiguous", "tgn_record_not_found", "query_failed"):
        n = sum(flag in r["flags"].split(";") for r in out_rows)
        print(f"  {flag:<22} {n}")
    if monitor:
        state = monitor.update_monitor_state(state=state, context="Completed TGN table verification",
                                             print_console=True)
        monitor.stop_monitor_state(state=state, print_stop_message=True)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", type=Path, default=TABLE_DEFAULT)
    parser.add_argument("--cache", type=Path, default=CACHE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--sleep", type=float, default=0.5, help="seconds between Getty queries")
    parser.add_argument("--no-monitor", action="store_true")
    args = parser.parse_args()
    run(args.table, args.cache, args.output, args.sleep, use_monitor=not args.no_monitor)


if __name__ == "__main__":
    main()
