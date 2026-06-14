#!/usr/bin/env python3
"""
02_map_wikidata.py  —  Module 06, Step 2
BnF Actor → Wikidata mapping and metadata enrichment.

Strategy
--------
Pass 1 (ID-based):
    Wikidata QIDs are already present in `actor_link_exact` / `actor_link_close`
    (e.g. http://wikidata.org/entity/Q12345) OR were harvested in the VIAF
    mapping step (column `wikidata_id` in viaf_mapping.csv).
    When a QID is found, the Wikidata Entity API is called to retrieve:
      - labels (preferred name in fr, en, la)
      - birth / death date (P569 / P570) for actors
      - publication date (P577) for editions (when --mode editions)
      - BnF ARK (P268), VIAF (P214), ISNI (P213), LC (P244)

Pass 2 (SPARQL label search, actors without QID):
    A SPARQL query is submitted to the Wikidata Query Service (WQDS)
    using the actor name as a rdfs:label filter, combined with birth year
    when available.  Top candidate accepted if similarity ≥ threshold.

Outputs
-------
output/wikidata_mapping.csv
    BnF_ID, qid, match_type, wikidata_label, birth_date, death_date,
    bnf_ark, viaf_id, isni, lc_id, confidence

report/wikidata_mapping_report.json

Usage
-----
# actors (default)
python 06_mapping/02_map_wikidata.py

# with VIAF mapping enrichment as additional QID source
python 06_mapping/02_map_wikidata.py \\
    --viaf-mapping 06_mapping/output/viaf_mapping.csv \\
    --threshold 0.82 \\
    --sleep 0.6
"""

import os, csv, sys, json, time, re, argparse, urllib.request, urllib.parse, urllib.error
from difflib import SequenceMatcher
from typing import Optional

INPUT_DEFAULT        = "05_subset_optimisation/output/bnf_actors_optimised.csv"
VIAF_MAPPING_DEFAULT = "06_mapping/output/viaf_mapping.csv"
OUTPUT_DEFAULT       = "06_mapping/output/wikidata_mapping.csv"
REPORT_DEFAULT       = "06_mapping/report/wikidata_mapping_report.json"
THRESHOLD_DEFAULT    = 0.85
SLEEP_DEFAULT        = 0.5

WD_ENTITY_API  = "https://www.wikidata.org/w/api.php"
WQDS_ENDPOINT  = "https://query.wikidata.org/sparql"

OUTPUT_FIELDS = [
    "BnF_ID", "qid", "match_type", "wikidata_label",
    "birth_date", "death_date",
    "bnf_ark", "viaf_id", "isni", "lc_id", "confidence",
]

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None: return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA","N/A","NULL","NONE",""} else s

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def extract_qid(uri: str) -> Optional[str]:
    m = re.search(r"wikidata\.org/(?:entity|wiki)/(Q\d+)", uri)
    return m.group(1) if m else None

def extract_year(s: str) -> str:
    m = re.search(r"(\d{4})", str(s))
    return m.group(1) if m else ""

def fetch_json(url: str, params: dict = None, headers: dict = None,
               retries: int = 3, sleep: float = 1.0) -> Optional[dict]:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    hdrs = {"Accept": "application/json", "User-Agent": "BnF-Mapping/1.0"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(sleep * (attempt + 1))
    return None


# ── Wikidata entity fetch ─────────────────────────────────────────────────────

def fetch_wikidata_entity(qid: str, sleep: float) -> dict:
    """Fetch entity data via the MediaWiki API wbgetentities action."""
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "format": "json",
        "languages": "fr|en|la",
        "props": "labels|claims",
    }
    data = fetch_json(WD_ENTITY_API, params=params)
    time.sleep(sleep)
    if not data:
        return {}

    entity = data.get("entities", {}).get(qid, {})
    if not entity or entity.get("missing") == "":
        return {}

    result = {"qid": qid}

    # Preferred label (fr > en > la > first available)
    labels = entity.get("labels", {})
    for lang in ("fr", "en", "la"):
        if lang in labels:
            result["wikidata_label"] = labels[lang]["value"]
            break
    if "wikidata_label" not in result and labels:
        result["wikidata_label"] = next(iter(labels.values()))["value"]

    claims = entity.get("claims", {})

    def first_claim_value(pid: str) -> str:
        vals = claims.get(pid, [])
        if vals:
            ms = vals[0].get("mainsnak", {})
            dv = ms.get("datavalue", {})
            v  = dv.get("value", "")
            if isinstance(v, dict):
                # dates
                return extract_year(v.get("time", ""))
            return str(v)
        return ""

    result["birth_date"]  = first_claim_value("P569")
    result["death_date"]  = first_claim_value("P570")
    result["bnf_ark"]     = first_claim_value("P268")
    result["viaf_id"]     = first_claim_value("P214")
    result["isni"]        = first_claim_value("P213")
    result["lc_id"]       = first_claim_value("P244")

    return result


# ── SPARQL name search ────────────────────────────────────────────────────────

def search_wikidata_by_name(name: str, birth_year: Optional[str],
                            sleep: float) -> list[dict]:
    """
    SPARQL query against WQDS.
    Returns up to 5 candidates {qid, wikidata_label, birth_date, death_date}.
    """
    birth_filter = ""
    if birth_year:
        birth_filter = f"""
        OPTIONAL {{ ?item wdt:P569 ?bd. }}
        FILTER(!BOUND(?bd) || (YEAR(?bd) >= {int(birth_year)-2}
                             && YEAR(?bd) <= {int(birth_year)+2}))"""

    sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?bd ?dd WHERE {{
  ?item rdfs:label "{name}"@fr .
  OPTIONAL {{ ?item wdt:P569 ?bd. }}
  OPTIONAL {{ ?item wdt:P570 ?dd. }}
  {birth_filter}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}} LIMIT 5
"""
    params = {"query": sparql, "format": "json"}
    data = fetch_json(WQDS_ENDPOINT, params=params,
                      headers={"User-Agent": "BnF-Mapping/1.0"})
    time.sleep(sleep)
    if not data:
        return []

    candidates = []
    for binding in data.get("results", {}).get("bindings", []):
        uri = binding.get("item", {}).get("value", "")
        qid = extract_qid(uri)
        if not qid:
            continue
        candidates.append({
            "qid": qid,
            "wikidata_label": binding.get("itemLabel", {}).get("value", ""),
            "birth_date": extract_year(binding.get("bd", {}).get("value", "")),
            "death_date": extract_year(binding.get("dd", {}).get("value", "")),
        })
    return candidates


# ── Load VIAF mapping (supplementary QID source) ──────────────────────────────

def load_viaf_qids(viaf_path: str) -> dict[str, str]:
    """Return {BnF_ID: wikidata_qid} from a previous VIAF mapping run."""
    mapping = {}
    if not viaf_path or not os.path.exists(viaf_path):
        return mapping
    with open(viaf_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            bnf = normalise(row.get("BnF_ID", ""))
            qid_raw = normalise(row.get("wikidata_id", ""))
            qid = extract_qid(qid_raw) or qid_raw
            if bnf and qid:
                mapping[bnf] = qid
    print(f"  Loaded {len(mapping):,} QIDs from VIAF mapping.")
    return mapping


# ── Main ─────────────────────────────────────────────────────────────────────

def run_mapping(input_path, viaf_mapping_path, output_path, report_path,
                threshold, sleep):

    actors = []
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        actors = list(csv.DictReader(f))
    print(f"Loaded {len(actors):,} actors.")

    viaf_qids = load_viaf_qids(viaf_mapping_path)

    results = []
    stats = {"total": len(actors), "pass1": 0, "pass2": 0, "unmatched": 0}

    for i, actor in enumerate(actors):
        if (i + 1) % 500 == 0:
            print(f"  … {i+1:,}/{len(actors):,}")

        bnf_id = normalise(actor.get("BnF_ID", ""))
        rec = {f: "" for f in OUTPUT_FIELDS}
        rec["BnF_ID"] = bnf_id

        # ── Pass 1: QID from links or VIAF mapping ───────────────────────────
        qid = None
        for link_field in ["actor_link_exact", "actor_link_close"]:
            for part in normalise(actor.get(link_field, "")).split(";"):
                q = extract_qid(part.strip())
                if q:
                    qid = q
                    break
            if qid:
                break
        if not qid:
            qid = viaf_qids.get(bnf_id)

        if qid:
            entity = fetch_wikidata_entity(qid, sleep)
            if entity:
                rec.update(entity)
                rec["match_type"] = "id"
                rec["confidence"] = "1.0"
                stats["pass1"] += 1
                results.append(rec)
                continue

        # ── Pass 2: name-based SPARQL ────────────────────────────────────────
        name = normalise(actor.get("actor_name", "")) or " ".join(filter(None, [
            normalise(actor.get("actor_first_name", "")),
            normalise(actor.get("actor_last_name", "")),
        ]))
        if not name:
            stats["unmatched"] += 1
            results.append(rec)
            continue

        birth_year = extract_year(normalise(actor.get("actor_birth", "")))
        candidates = search_wikidata_by_name(name, birth_year or None, sleep)

        best, best_score = None, 0.0
        for cand in candidates:
            score = similarity(name, cand.get("wikidata_label", ""))
            if score > best_score:
                best_score, best = score, cand

        if best and best_score >= threshold:
            entity = fetch_wikidata_entity(best["qid"], sleep)
            rec.update(best)
            if entity:
                rec.update(entity)
            rec["match_type"] = "name"
            rec["confidence"] = f"{best_score:.3f}"
            stats["pass2"] += 1
        else:
            rec["match_type"] = "unmatched"
            stats["unmatched"] += 1

        results.append(rec)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n✓ Mapping CSV → {output_path}")

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"✓ Report       → {report_path}")
    print(f"  Pass-1 (ID)   : {stats['pass1']:,}")
    print(f"  Pass-2 (name) : {stats['pass2']:,}")
    print(f"  Unmatched     : {stats['unmatched']:,}")


def main():
    parser = argparse.ArgumentParser(description="BnF → Wikidata mapping and enrichment")
    parser.add_argument("--input",        default=INPUT_DEFAULT)
    parser.add_argument("--viaf-mapping", default=VIAF_MAPPING_DEFAULT)
    parser.add_argument("--output",       default=OUTPUT_DEFAULT)
    parser.add_argument("--report",       default=REPORT_DEFAULT)
    parser.add_argument("--threshold",    type=float, default=THRESHOLD_DEFAULT)
    parser.add_argument("--sleep",        type=float, default=SLEEP_DEFAULT)
    args = parser.parse_args()
    run_mapping(args.input, args.viaf_mapping, args.output, args.report,
                args.threshold, args.sleep)

if __name__ == "__main__":
    main()
