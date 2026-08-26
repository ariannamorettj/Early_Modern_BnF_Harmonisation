#!/usr/bin/env python3
"""
01_map_viaf.py  —  Module 06, Step 1
BnF Actor → VIAF mapping and metadata enrichment.

Strategy
--------
Pass 1 (ID-based, lossless):
    Each actor in the BnF optimised dataset already carries zero or more
    VIAF URIs in `actor_link_exact` / `actor_link_close`.  These are
    extracted and used to directly fetch the VIAF cluster via the public
    REST API (https://viaf.org/viaf/{id}/justlinks.json).
    From the cluster we harvest:
      - canonical preferred name (mainHeadings)
      - birth / death dates (birthDate / deathDate)
      - co-referent authority IDs (Wikipedia, LC, IdRef, Wikidata, …)

Pass 2 (name-based, heuristic, actors without a VIAF URI):
    A SRU search is issued against the VIAF API using the actor's canonical
    name and, when available, birth year.  The top candidate is accepted if
    it clears a similarity threshold (Levenshtein ratio ≥ 0.85 by default).

Outputs
-------
output/viaf_mapping.csv
    BnF_ID, viaf_id, match_type, viaf_name, birth_date, death_date,
    wikidata_id, lc_id, idref_id, confidence

report/viaf_mapping_report.json
    summary statistics (total actors, matched, pass-1, pass-2, unmatched)

Usage
-----
python 06_mapping/01_map_viaf.py

python 06_mapping/01_map_viaf.py \\
    --input  05_subset_optimisation/output/bnf_actors_optimised.csv \\
    --output 06_mapping/output/viaf_mapping.csv \\
    --report 06_mapping/report/viaf_mapping_report.json \\
    --threshold 0.85 \\
    --sleep 0.5
"""

import os
import csv
import sys
import json
import time
import re
import argparse
import urllib.request
import urllib.parse
import urllib.error
from difflib import SequenceMatcher
from typing import Optional

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or U+2192 (→) used below,
# raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Defaults ──────────────────────────────────────────────────────────────────
INPUT_DEFAULT  = "05_subset_optimisation/output/bnf_actors_optimised.csv"
OUTPUT_DEFAULT = "06_mapping/output/viaf_mapping.csv"
REPORT_DEFAULT = "06_mapping/report/viaf_mapping_report.json"
THRESHOLD_DEFAULT = 0.85
SLEEP_DEFAULT     = 0.4   # seconds between API calls

VIAF_BASE      = "https://viaf.org/viaf"
VIAF_SRU_BASE  = "https://viaf.org/search"

OUTPUT_FIELDS  = [
    "BnF_ID", "viaf_id", "match_type",
    "viaf_name", "birth_date", "death_date",
    "wikidata_id", "lc_id", "idref_id", "confidence",
]

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


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extract_viaf_id(uri: str) -> Optional[str]:
    """Extract numeric VIAF ID from a URI like http://viaf.org/viaf/12345/"""
    m = re.search(r"viaf\.org/viaf/(\d+)", uri)
    return m.group(1) if m else None


def extract_year(date_str: str) -> Optional[str]:
    m = re.search(r"\b(\d{4})\b", date_str)
    return m.group(1) if m else None


def fetch_json(url: str, retries: int = 3, sleep: float = 1.0) -> Optional[dict]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(sleep * (attempt + 1))
        except Exception:
            time.sleep(sleep * (attempt + 1))
    return None


# ── VIAF cluster fetch ────────────────────────────────────────────────────────

def fetch_viaf_cluster(viaf_id: str, sleep: float) -> dict:
    """Fetch justlinks.json and mainHeadings for a VIAF numeric ID."""
    url = f"{VIAF_BASE}/{viaf_id}/justlinks.json"
    data = fetch_json(url)
    time.sleep(sleep)
    if not data:
        return {}

    result = {"viaf_id": viaf_id}

    # Co-referent IDs
    for key, field in [("WKP", "wikidata_id"), ("LC", "lc_id"), ("IDREF", "idref_id")]:
        val = data.get(key)
        if isinstance(val, list) and val:
            result[field] = val[0]
        elif isinstance(val, str):
            result[field] = val

    # Preferred name + dates via /viaf/{id}/viaf.json
    detail_url = f"{VIAF_BASE}/{viaf_id}/viaf.json"
    detail = fetch_json(detail_url)
    time.sleep(sleep)
    if detail:
        # Preferred name
        mh = detail.get("mainHeadings", {})
        if isinstance(mh, dict):
            data200 = mh.get("data", [])
            if isinstance(data200, list) and data200:
                text = data200[0].get("text", "")
                result["viaf_name"] = text
            elif isinstance(data200, dict):
                result["viaf_name"] = data200.get("text", "")

        result["birth_date"] = extract_year(str(detail.get("birthDate", ""))) or ""
        result["death_date"] = extract_year(str(detail.get("deathDate", ""))) or ""

    return result


# ── SRU name search ───────────────────────────────────────────────────────────

def search_viaf_by_name(name: str, birth_year: Optional[str], sleep: float) -> list[dict]:
    """
    Issue a VIAF SRU search query.
    Returns a list of candidate dicts with keys: viaf_id, viaf_name, birth_date, death_date.
    """
    query = f'local.personalNames all "{name}"'
    if birth_year:
        query += f' and local.birthDate = "{birth_year}"'

    params = urllib.parse.urlencode({
        "query": query,
        "maximumRecords": "5",
        "startRecord": "1",
        "httpAccept": "application/json",
    })
    url = f"{VIAF_SRU_BASE}?{params}"
    data = fetch_json(url)
    time.sleep(sleep)

    if not data:
        return []

    records = data.get("searchRetrieveResponse", {}).get("records", {})
    if not records:
        return []

    record_list = records.get("record", [])
    if isinstance(record_list, dict):
        record_list = [record_list]

    candidates = []
    for rec in record_list:
        cluster = rec.get("recordData", {}).get("ns0:VIAFCluster", {})
        if not cluster:
            cluster = rec.get("recordData", {}).get("VIAFCluster", {})

        vid = cluster.get("viafID", "")
        mh = cluster.get("mainHeadings", {})
        name_text = ""
        if isinstance(mh, dict):
            d = mh.get("data", {})
            if isinstance(d, list) and d:
                name_text = d[0].get("text", "")
            elif isinstance(d, dict):
                name_text = d.get("text", "")

        bd = extract_year(str(cluster.get("birthDate", ""))) or ""
        dd = extract_year(str(cluster.get("deathDate", ""))) or ""

        if vid:
            candidates.append({
                "viaf_id": vid,
                "viaf_name": name_text,
                "birth_date": bd,
                "death_date": dd,
            })
    return candidates


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_mapping(input_path: str, output_path: str, report_path: str,
                threshold: float, sleep: float):

    # Read input
    actors = []
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            actors.append(row)
    print(f"Loaded {len(actors):,} actors from {input_path}")

    results = []
    stats = {"total": len(actors), "pass1": 0, "pass2": 0, "unmatched": 0}

    for i, actor in enumerate(actors):
        if (i + 1) % 500 == 0:
            print(f"  … {i+1:,}/{len(actors):,}")

        bnf_id = normalise(actor.get("BnF_ID", ""))
        rec = {f: "" for f in OUTPUT_FIELDS}
        rec["BnF_ID"] = bnf_id

        # ── Pass 1: ID-based ─────────────────────────────────────────────────
        viaf_ids = []
        for link_field in ["actor_link_exact", "actor_link_close"]:
            raw = normalise(actor.get(link_field, ""))
            for part in raw.split(";"):
                vid = extract_viaf_id(part.strip())
                if vid and vid not in viaf_ids:
                    viaf_ids.append(vid)

        if viaf_ids:
            cluster = fetch_viaf_cluster(viaf_ids[0], sleep)
            if cluster:
                rec.update(cluster)
                rec["match_type"] = "id"
                rec["confidence"] = "1.0"
                stats["pass1"] += 1
                results.append(rec)
                continue

        # ── Pass 2: name-based ───────────────────────────────────────────────
        name = normalise(actor.get("actor_name", "")) or \
               " ".join(filter(None, [
                   normalise(actor.get("actor_first_name", "")),
                   normalise(actor.get("actor_last_name", "")),
               ]))
        if not name:
            stats["unmatched"] += 1
            results.append(rec)
            continue

        birth_raw = normalise(actor.get("actor_birth", ""))
        birth_year = extract_year(birth_raw)

        candidates = search_viaf_by_name(name, birth_year, sleep)
        best = None
        best_score = 0.0
        for cand in candidates:
            score = similarity(name, cand.get("viaf_name", ""))
            if score > best_score:
                best_score = score
                best = cand

        if best and best_score >= threshold:
            rec.update(best)
            rec["match_type"] = "name"
            rec["confidence"] = f"{best_score:.3f}"

            # Enrich with co-referent IDs from justlinks
            extra = fetch_viaf_cluster(best["viaf_id"], sleep)
            for k in ["wikidata_id", "lc_id", "idref_id"]:
                if extra.get(k):
                    rec[k] = extra[k]

            stats["pass2"] += 1
        else:
            rec["match_type"] = "unmatched"
            stats["unmatched"] += 1

        results.append(rec)

    # Write CSV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n✓ Mapping CSV → {output_path}")

    # Write report
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"✓ Report       → {report_path}")
    print(f"\n  Pass-1 (ID)    : {stats['pass1']:,}")
    print(f"  Pass-2 (name)  : {stats['pass2']:,}")
    print(f"  Unmatched      : {stats['unmatched']:,}")


def main():
    parser = argparse.ArgumentParser(description="BnF → VIAF mapping and enrichment")
    parser.add_argument("--input",     default=INPUT_DEFAULT)
    parser.add_argument("--output",    default=OUTPUT_DEFAULT)
    parser.add_argument("--report",    default=REPORT_DEFAULT)
    parser.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT,
                        help="Minimum name-similarity score for pass-2 matches (default 0.85)")
    parser.add_argument("--sleep",     type=float, default=SLEEP_DEFAULT,
                        help="Seconds to wait between API calls (default 0.4)")
    args = parser.parse_args()
    run_mapping(args.input, args.output, args.report, args.threshold, args.sleep)


if __name__ == "__main__":
    main()
