#!/usr/bin/env python3
"""
01_map_viaf.py  —  Module 06, Step 1
BnF Actor → VIAF mapping and metadata enrichment.

Strategy (first pass that answers wins)
----------------------------------------
Pass 1, BnF source ID (lossless):
    VIAF clusters list the BnF authority record they include. Every BnF
    actor is looked up directly by its BnF record number
    (https://viaf.org/viaf/sourceID/BNF|<8 digits>): the ARK
    cb10017347j becomes BNF|10017347.
Pass 2, existing VIAF link (lossless):
    For actors VIAF does not list under their BnF number, the VIAF URI
    already present in actor_link_exact / actor_link_close is resolved
    (https://viaf.org/viaf/<id>).
Pass 3, name search (heuristic):
    A VIAF SRU search on the actor's name, plus birth year when known; the
    best candidate is accepted if its heading clears the similarity
    threshold (0.85 by default).

From the cluster JSON the script keeps the VIAF ID, the BnF heading (or
the first heading), birth/death years, and the Wikidata, LC, IdRef (SUDOC)
and ISNI identifiers VIAF links to the cluster.

VIAF retired the justlinks.json / viaf.json / search?httpAccept endpoints
this script used to call; they now answer 404, which the old version read
as "no match" for every actor. The endpoints above are the ones that work
as of 2026-09.

Resilience
----------
Results are appended to the output CSV as they are produced and fsync'ed
regularly (06_mapping/resumable.py). Re-running the same command resumes at
the first actor not yet in the file; --restart starts over. Only definitive
answers are written: a network error or an HTTP 5xx after retries leaves the
actor out, so the next run tries it again instead of recording a false
"unmatched". Monitoring: 00_monitor checkpoints every
MONITOR_CHECKPOINT_EVERY actors and at the last one (--no-monitor to
disable).

Outputs
-------
output/viaf_mapping.csv
    BnF_ID, viaf_id, match_type, viaf_name, birth_date, death_date,
    wikidata_id, lc_id, idref_id, isni, confidence
report/viaf_mapping_report.json
    counts per match_type, computed from the whole output file.

Usage
-----
python 06_mapping/01_map_viaf.py
python 06_mapping/01_map_viaf.py --input 06_mapping/output/bnf_actors_enriched.csv --sleep 0.4
"""

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resumable import ResumableCsvWriter, read_rows  # noqa: E402

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
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 100
THRESHOLD_DEFAULT = 0.85
SLEEP_DEFAULT     = 0.4   # seconds between API calls
RETRIES           = 4

VIAF_BASE = "https://viaf.org/viaf"

OUTPUT_FIELDS = [
    "BnF_ID", "viaf_id", "match_type",
    "viaf_name", "birth_date", "death_date",
    "wikidata_id", "lc_id", "idref_id", "isni", "confidence",
]
MATCH_TYPES = ["bnf_source_id", "viaf_link", "name", "unmatched"]
# VIAF source code -> output column
LINKED_SOURCES = {"WKP": "wikidata_id", "LC": "lc_id", "SUDOC": "idref_id", "ISNI": "isni"}

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


class TransientError(Exception):
    """The service did not give a definitive answer; retry on a later run."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def _name_tokens(name: str) -> str:
    """Sorted words without dates or punctuation: VIAF headings are
    'Family, Given (dates)' while BnF names are 'Given Family'."""
    words = re.findall(r"[^\W\d_]+", name.lower())
    return " ".join(sorted(words))


def similarity(a: str, b: str) -> float:
    plain = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    tokens = SequenceMatcher(None, _name_tokens(a), _name_tokens(b)).ratio()
    return max(plain, tokens)


def extract_viaf_id(uri: str) -> Optional[str]:
    """Extract numeric VIAF ID from a URI like http://viaf.org/viaf/12345/"""
    m = re.search(r"viaf\.org/viaf/(\d+)", uri)
    return m.group(1) if m else None


def bnf_source_id(bnf_id: str) -> Optional[str]:
    """<http://data.bnf.fr/ark:/12148/cb10017347j#about> -> '10017347'."""
    m = re.search(r"/cb(\d{8})[0-9bcdfghjkmnpqrstvwxz]?(?:#|>|$)", bnf_id)
    return m.group(1) if m else None


def extract_year(date_str: str) -> Optional[str]:
    m = re.search(r"\b(\d{4})\b", date_str)
    return m.group(1) if m else None


def strip_ns(obj):
    """Drop the XML namespace prefixes VIAF's JSON keeps ('ns1:viafID' -> 'viafID')."""
    if isinstance(obj, dict):
        return {k.split(":", 1)[-1]: strip_ns(v) for k, v in obj.items() if not k.startswith("xmlns")}
    if isinstance(obj, list):
        return [strip_ns(v) for v in obj]
    return obj


def as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def fetch_json(url: str, sleep: float) -> Optional[dict]:
    """JSON body, None on 404 (a definitive "not in VIAF"), TransientError
    when the service keeps failing."""
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "BnF-harmonisation/1.0 (research)"})
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
            time.sleep(sleep)
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(sleep)
                return None
            last = f"HTTP {e.code}"
        except Exception as e:  # timeout, connection reset, bad JSON
            last = str(e)
        time.sleep(sleep * 5 * (attempt + 1))
    raise TransientError(f"{url}: {last}")


# ── VIAF cluster parsing ──────────────────────────────────────────────────────

def parse_cluster(raw: dict) -> dict:
    """Output fields from a VIAF cluster record (any namespace prefix)."""
    data = strip_ns(raw)
    cluster = data.get("VIAFCluster", data)
    result = {"viaf_id": str(cluster.get("viafID", ""))}

    headings = as_list((cluster.get("mainHeadings") or {}).get("data"))
    chosen = None
    for h in headings:
        sources = as_list((h.get("sources") or {}).get("s"))
        if "BNF" in sources:
            chosen = h
            break
    chosen = chosen or (headings[0] if headings else None)
    if chosen:
        result["viaf_name"] = str(chosen.get("text", ""))

    for field, key in (("birth_date", "birthDate"), ("death_date", "deathDate")):
        year = extract_year(str(cluster.get(key, "")))
        result[field] = year or ""

    for source in as_list((cluster.get("sources") or {}).get("source")):
        content = str(source.get("content", "")) if isinstance(source, dict) else str(source)
        code, _, value = content.partition("|")
        field = LINKED_SOURCES.get(code)
        if field and not result.get(field):
            nsid = source.get("nsid") if isinstance(source, dict) else None
            result[field] = str(nsid if code in ("LC", "WKP") and nsid else value).replace(" ", "")
    return result


def fetch_cluster_by_bnf(source_id: str, sleep: float) -> dict:
    url = f"{VIAF_BASE}/sourceID/{urllib.parse.quote('BNF|' + source_id)}"
    data = fetch_json(url, sleep)
    return parse_cluster(data) if data else {}


def fetch_cluster(viaf_id: str, sleep: float) -> dict:
    data = fetch_json(f"{VIAF_BASE}/{viaf_id}", sleep)
    return parse_cluster(data) if data else {}


def search_viaf_by_name(name: str, birth_year: Optional[str], sleep: float) -> list[dict]:
    """VIAF SRU search; candidates with viaf_id, viaf_name, birth/death years."""
    query = f'local.personalNames all "{name}"'
    if birth_year:
        query += f' and local.birthDate = "{birth_year}"'
    # The SRU endpoint needs "+" for spaces and no httpAccept parameter.
    params = urllib.parse.urlencode({"query": query, "maximumRecords": "5", "startRecord": "1"})
    data = fetch_json(f"{VIAF_BASE}/search?{params}", sleep)
    if not data:
        return []
    response = strip_ns(data).get("searchRetrieveResponse", {})
    records = as_list((response.get("records") or {}).get("record"))
    candidates = []
    for rec in records:
        cluster = parse_cluster((rec.get("recordData") or {}))
        if cluster.get("viaf_id"):
            candidates.append(cluster)
    return candidates


# ── Monitor ───────────────────────────────────────────────────────────────────

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("monitor_map_viaf", project_root / monitor_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def map_actor(actor: dict, threshold: float, sleep: float) -> dict:
    """One output row for one actor; raises TransientError to defer it."""
    bnf_id = normalise(actor.get("BnF_ID", ""))
    rec = {f: "" for f in OUTPUT_FIELDS}
    rec["BnF_ID"] = bnf_id

    # Pass 1: BnF source ID
    source_id = bnf_source_id(bnf_id)
    if source_id:
        cluster = fetch_cluster_by_bnf(source_id, sleep)
        if cluster.get("viaf_id"):
            rec.update(cluster, match_type="bnf_source_id", confidence="1.0")
            return rec

    # Pass 2: VIAF link already on the actor
    for link_field in ("actor_link_exact", "actor_link_close"):
        for part in normalise(actor.get(link_field, "")).split(";"):
            vid = extract_viaf_id(part.strip())
            if vid:
                cluster = fetch_cluster(vid, sleep)
                if cluster.get("viaf_id"):
                    rec.update(cluster, match_type="viaf_link", confidence="1.0")
                    return rec

    # Pass 3: name search
    name = normalise(actor.get("actor_name", "")) or " ".join(filter(None, [
        normalise(actor.get("actor_first_name", "")),
        normalise(actor.get("actor_last_name", "")),
    ]))
    if name:
        best, best_score = None, 0.0
        for cand in search_viaf_by_name(name, extract_year(normalise(actor.get("actor_birth", ""))), sleep):
            score = similarity(name, cand.get("viaf_name", ""))
            if score > best_score:
                best, best_score = cand, score
        if best and best_score >= threshold:
            rec.update(best, match_type="name", confidence=f"{best_score:.3f}")
            return rec

    rec["match_type"] = "unmatched"
    return rec


def run_mapping(input_path: str, output_path: str, report_path: str,
                threshold: float, sleep: float, use_monitor: bool = False,
                restart: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> dict:
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        actors = list(csv.DictReader(f))
    total = len(actors)
    print(f"Loaded {total:,} actors from {input_path}")

    monitor_module = monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during 01_map_viaf.py execution",
            print_start_message=True)

    deferred = 0
    with ResumableCsvWriter(output_path, OUTPUT_FIELDS, "BnF_ID", restart=restart) as out:
        for i, actor in enumerate(actors, start=1):
            bnf_id = normalise(actor.get("BnF_ID", ""))
            if bnf_id and bnf_id not in out.done_keys:
                try:
                    rec = map_actor(actor, threshold, sleep)
                    out.write(rec)
                except TransientError as exc:
                    deferred += 1
                    rec = {"match_type": f"deferred ({exc})"}
                    print(f"  [deferred] {bnf_id}: {exc}")
            else:
                rec = None
            if monitor_module and (i % MONITOR_CHECKPOINT_EVERY == 0 or i == total):
                last = f" - {bnf_id} match_type={rec['match_type']}" if rec else " (already done)"
                monitor_state = monitor_module.update_monitor_state(
                    state=monitor_state, context=f"Processed actor {i}/{total}{last}", print_console=True)

    rows = read_rows(output_path)
    stats = {"total": total, "written": len(rows), "deferred_this_run": deferred}
    for mt in MATCH_TYPES:
        stats[mt] = sum(r["match_type"] == mt for r in rows)
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(f"\n✓ Mapping CSV → {output_path} ({len(rows):,} of {total:,} actors)")
    print(f"✓ Report       → {report_path}")
    for mt in MATCH_TYPES:
        print(f"  {mt:<14} {stats[mt]:,}")
    if deferred:
        print(f"  {deferred:,} actors deferred after network errors: re-run the same command to retry them.")

    if monitor_module:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state, context="Completed VIAF mapping run", print_console=True)
        monitor_module.stop_monitor_state(state=monitor_state, print_stop_message=True)
    return stats


def main():
    parser = argparse.ArgumentParser(description="BnF → VIAF mapping and enrichment")
    parser.add_argument("--input",     default=INPUT_DEFAULT)
    parser.add_argument("--output",    default=OUTPUT_DEFAULT)
    parser.add_argument("--report",    default=REPORT_DEFAULT)
    parser.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT,
                        help="Minimum name-similarity score for pass-3 matches (default 0.85)")
    parser.add_argument("--sleep",     type=float, default=SLEEP_DEFAULT,
                        help="Seconds to wait between API calls (default 0.4)")
    parser.add_argument("--restart",   action="store_true",
                        help="Discard the existing output and start from the first actor")
    parser.add_argument("--no-monitor", action="store_true")
    args = parser.parse_args()
    run_mapping(args.input, args.output, args.report, args.threshold, args.sleep,
                use_monitor=not args.no_monitor, restart=args.restart)


if __name__ == "__main__":
    main()
