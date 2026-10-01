#!/usr/bin/env python3
"""
02_map_wikidata.py  —  Module 06, Step 2
BnF Actor → Wikidata mapping and metadata enrichment.

Strategy
--------
Pass 0 (BnF ARK, batched, lossless):
    Wikidata records the BnF authority identifier of people and
    organisations (P268). The ARKs of all actors still to process are sent
    to the Wikidata Query Service 150 at a time; one query returns the QID,
    label, dates and VIAF/ISNI/LC identifiers of every actor Wikidata
    knows, so most actors need no call of their own.

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
    using the actor name as a rdfs:label filter, combined with birth and/or
    death year when available.  Top candidate accepted if similarity ≥ threshold.

Outputs
-------
output/wikidata_mapping.csv
    BnF_ID, qid, match_type, wikidata_label, birth_date, death_date,
    bnf_ark, viaf_id, isni, lc_id, confidence

report/wikidata_mapping_report.json

Resilience
----------
Results are appended to the output CSV as they are produced
(06_mapping/resumable.py): re-running the same command resumes at the
first actor not yet written, --restart starts over. The Pass 0 batch
answers go to output/wikidata_mapping_p268_cache.jsonl as they arrive, so
an interrupted run does not repeat that lookup either. A request that keeps
failing (timeout, HTTP 429/5xx) raises TransientError: the actor is left
out of the file and retried on the next run, instead of being written as a
false "unmatched".

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API (same mechanism
used by module 1's query_agents.R / query_editions.R): one checkpoint every
MONITOR_CHECKPOINT_EVERY (100) actors and at the last one, plus a final
checkpoint on completion. Reports land in
00_monitor/report/02_map_wikidata_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
# actors (default)
python 06_mapping/02_map_wikidata.py

# with VIAF mapping enrichment as additional QID source
python 06_mapping/02_map_wikidata.py \\
    --viaf-mapping 06_mapping/output/viaf_mapping.csv \\
    --threshold 0.82 \\
    --sleep 0.6

# disable the monitor report
python 06_mapping/02_map_wikidata.py --no-monitor
"""

import os, csv, sys, json, time, re, argparse, importlib.util
import urllib.request, urllib.parse, urllib.error
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

MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per record cost ~55 ms each (mostly the nvidia-smi GPU read);
# checkpoint every N records plus the last one instead, like
# 06_mapping/05_map_estc_actors.py. N is lower than in the local scripts
# because each record here waits on a network call.
MONITOR_CHECKPOINT_EVERY = 100

INPUT_DEFAULT        = "05_subset_optimisation/output/bnf_actors_optimised.csv"
VIAF_MAPPING_DEFAULT = "06_mapping/output/viaf_mapping.csv"
OUTPUT_DEFAULT       = "06_mapping/output/wikidata_mapping.csv"
REPORT_DEFAULT       = "06_mapping/report/wikidata_mapping_report.json"
THRESHOLD_DEFAULT    = 0.85
SLEEP_DEFAULT        = 0.5

WD_ENTITY_API  = "https://www.wikidata.org/w/api.php"
WQDS_ENDPOINT  = "https://query.wikidata.org/sparql"
# Wikimedia asks automated clients for a descriptive User-Agent with a contact.
USER_AGENT = "BnF-harmonisation/1.0 (https://github.com/ariannamorettj/Early_Modern_BnF_Harmonisation)"
BNF_BATCH_SIZE = 150
MATCH_TYPES = ["bnf_ark", "id", "name", "unmatched"]

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

class TransientError(Exception):
    """The service did not give a definitive answer; retry on a later run."""


def fetch_json(url: str, params: dict = None, headers: dict = None,
               retries: int = 4, sleep: float = 2.0) -> Optional[dict]:
    """JSON body; None on HTTP 404; TransientError when the service keeps
    failing (the old version returned None here too, which turned every
    outage into a silent "unmatched")."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = f"HTTP {e.code}"
            # 429: respect Retry-After when the query service sends it.
            wait = int(e.headers.get("Retry-After", "0") or 0) if e.code == 429 else 0
            time.sleep(max(wait, sleep * 5 * (attempt + 1)))
        except Exception as e:
            last = str(e)
            time.sleep(sleep * 5 * (attempt + 1))
    raise TransientError(f"{url[:120]}: {last}")


def bnf_ark(bnf_id: str) -> Optional[str]:
    """<http://data.bnf.fr/ark:/12148/cb10017347j#about> -> '10017347j' (P268 form)."""
    m = re.search(r"/cb(\d{8}[0-9bcdfghjkmnpqrstvwxz])(?:#|>|$)", bnf_id)
    return m.group(1) if m else None


def _load_p268_cache(cache_path: Optional[str]) -> tuple[set, dict]:
    """(ARKs already queried, their results) from the batch cache. A last
    line cut short by a crash is ignored: that batch is queried again."""
    queried, found = set(), {}
    if not cache_path or not os.path.exists(cache_path):
        return queried, found
    with open(cache_path, "rb+") as f:
        data = f.read()
        if data and not data.endswith(b"\n"):
            # Drop the partial line, so the next batch starts on a line of its own.
            f.truncate(data.rfind(b"\n") + 1)
    with open(cache_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            queried.update(entry["arks"])
            found.update(entry["found"])
    return queried, found


def prefetch_by_bnf(arks: list, sleep: float, cache_path: Optional[str] = None) -> dict:
    """{ark: output fields} for the ARKs Wikidata lists under P268, in batches.

    With cache_path, each batch's answer is appended to that JSON-lines file
    as soon as it arrives, and ARKs already in it are not queried again: an
    interrupted run resumes the lookup instead of starting it over."""
    queried, cached = _load_p268_cache(cache_path)
    found = {ark: row for ark, row in cached.items() if ark in set(arks)}
    remaining = [a for a in arks if a not in queried]
    if queried:
        print(f"  P268 cache: {len(arks) - len(remaining):,} ARKs already looked up "
              f"({len(found):,} found), {len(remaining):,} to go")
    cache = open(cache_path, "a", encoding="utf-8") if cache_path else None
    try:
        for start in range(0, len(remaining), BNF_BATCH_SIZE):
            batch = remaining[start:start + BNF_BATCH_SIZE]
            batch_found = _query_bnf_batch(batch, sleep)
            found.update(batch_found)
            if cache:
                cache.write(json.dumps({"arks": batch, "found": batch_found}, ensure_ascii=False) + "\n")
                cache.flush()
                os.fsync(cache.fileno())
            print(f"  … P268 lookup {min(start + BNF_BATCH_SIZE, len(remaining)):,}/{len(remaining):,} "
                  f"({len(found):,} found)")
    finally:
        if cache:
            cache.close()
    return found


def _query_bnf_batch(batch: list, sleep: float) -> dict:
    """One Wikidata query for up to BNF_BATCH_SIZE ARKs."""
    found = {}
    values = " ".join(f'"{a}"' for a in batch)
    sparql = f"""
SELECT ?bnf ?item ?label ?bd ?dd ?viaf ?isni ?lc WHERE {{
  VALUES ?bnf {{ {values} }}
  ?item wdt:P268 ?bnf .
  OPTIONAL {{ ?item rdfs:label ?labelFr . FILTER(LANG(?labelFr) = "fr") }}
  OPTIONAL {{ ?item rdfs:label ?labelMul . FILTER(LANG(?labelMul) = "mul") }}
  OPTIONAL {{ ?item rdfs:label ?labelEn . FILTER(LANG(?labelEn) = "en") }}
  BIND(COALESCE(?labelFr, ?labelMul, ?labelEn) AS ?label)
  OPTIONAL {{ ?item wdt:P569 ?bd . }}
  OPTIONAL {{ ?item wdt:P570 ?dd . }}
  OPTIONAL {{ ?item wdt:P214 ?viaf . }}
  OPTIONAL {{ ?item wdt:P213 ?isni . }}
  OPTIONAL {{ ?item wdt:P244 ?lc . }}
}}"""
    data = fetch_json(WQDS_ENDPOINT, params={"query": sparql, "format": "json"},
                      headers={"Accept": "application/sparql-results+json"})
    time.sleep(sleep)
    for b in (data or {}).get("results", {}).get("bindings", []):
        ark = b["bnf"]["value"]
        row = {
            "qid": extract_qid(b["item"]["value"]) or "",
            "wikidata_label": b.get("label", {}).get("value", ""),
            "birth_date": extract_year(b.get("bd", {}).get("value", "")),
            "death_date": extract_year(b.get("dd", {}).get("value", "")),
            "bnf_ark": ark,
            "viaf_id": b.get("viaf", {}).get("value", ""),
            "isni": b.get("isni", {}).get("value", ""),
            "lc_id": b.get("lc", {}).get("value", ""),
        }
        # One row per combination of optional values: keep the first
        # value of each field, filling the gaps from later rows.
        kept = found.setdefault(ark, row)
        for k, v in row.items():
            if not kept.get(k) and v:
                kept[k] = v
    return found


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
                            death_year: Optional[str],
                            sleep: float) -> list[dict]:
    """
    SPARQL query against WQDS.
    Returns up to 5 candidates {qid, wikidata_label, birth_date, death_date}.
    Filters on birth and/or death year (whichever is available, ±2 years);
    candidates with no bound date for a given predicate are still admitted.
    """
    conditions = []
    if birth_year:
        conditions.append(f"""(!BOUND(?bd) || (YEAR(?bd) >= {int(birth_year)-2}
                             && YEAR(?bd) <= {int(birth_year)+2}))""")
    if death_year:
        conditions.append(f"""(!BOUND(?dd) || (YEAR(?dd) >= {int(death_year)-2}
                             && YEAR(?dd) <= {int(death_year)+2}))""")
    date_filter = f"FILTER({' && '.join(conditions)})" if conditions else ""

    sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?bd ?dd WHERE {{
  ?item rdfs:label "{name}"@fr .
  OPTIONAL {{ ?item wdt:P569 ?bd. }}
  OPTIONAL {{ ?item wdt:P570 ?dd. }}
  {date_filter}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}} LIMIT 5
"""
    params = {"query": sparql, "format": "json"}
    data = fetch_json(WQDS_ENDPOINT, params=params,
                      headers={"Accept": "application/sparql-results+json"})
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


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1)."""
    project_root = Path(__file__).resolve().parents[1]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_wikidata", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, rec):
    if monitor_module is None:
        return monitor_state
    if index % MONITOR_CHECKPOINT_EVERY and index != total:
        return monitor_state
    context = (f"Processed actor {rec['BnF_ID']} (index {index}/{total}) "
              f"- match_type={rec['match_type'] or 'unmatched'}")
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def map_actor(actor: dict, viaf_qids: dict, by_bnf: dict, threshold: float, sleep: float) -> dict:
    """One output row for one actor; raises TransientError to defer it."""
    bnf_id = normalise(actor.get("BnF_ID", ""))
    rec = {f: "" for f in OUTPUT_FIELDS}
    rec["BnF_ID"] = bnf_id

    # ── Pass 0: BnF ARK (prefetched in batches) ──────────────────────────────
    ark = bnf_ark(bnf_id)
    if ark and ark in by_bnf:
        rec.update(by_bnf[ark], match_type="bnf_ark", confidence="1.0")
        return rec

    # ── Pass 1: QID from links or VIAF mapping ───────────────────────────────
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
            rec.update(entity, match_type="id", confidence="1.0")
            return rec

    # ── Pass 2: name-based SPARQL ────────────────────────────────────────────
    name = normalise(actor.get("actor_name", "")) or " ".join(filter(None, [
        normalise(actor.get("actor_first_name", "")),
        normalise(actor.get("actor_last_name", "")),
    ]))
    if name:
        birth_year = extract_year(normalise(actor.get("actor_birth", "")))
        death_year = extract_year(normalise(actor.get("actor_death", "")))
        candidates = search_wikidata_by_name(name, birth_year or None, death_year or None, sleep)
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
            return rec

    rec["match_type"] = "unmatched"
    return rec


def run_mapping(input_path, viaf_mapping_path, output_path, report_path,
                threshold, sleep, use_monitor=False,
                monitor_script=MONITOR_SCRIPT_DEFAULT, restart=False):

    with open(input_path, "r", encoding="utf-8", newline="") as f:
        actors = list(csv.DictReader(f))
    total = len(actors)
    print(f"Loaded {total:,} actors.")

    viaf_qids = load_viaf_qids(viaf_mapping_path)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during 02_map_wikidata.py execution",
            print_start_message=True,
        )

    # The P268 batch answers, kept next to the output so an interrupted run
    # does not repeat the lookup (about two hours for the full actor set).
    cache_path = os.path.splitext(output_path)[0] + "_p268_cache.jsonl"
    if restart and os.path.exists(cache_path):
        os.remove(cache_path)

    deferred = 0
    with ResumableCsvWriter(output_path, OUTPUT_FIELDS, "BnF_ID", restart=restart) as out:
        todo_arks = sorted({ark for ark in (bnf_ark(normalise(a.get("BnF_ID", ""))) for a in actors
                                            if normalise(a.get("BnF_ID", "")) not in out.done_keys)
                            if ark})
        try:
            by_bnf = prefetch_by_bnf(todo_arks, sleep, cache_path) if todo_arks else {}
        except TransientError as exc:
            print(f"  [warn] P268 batch lookup failed ({exc}); falling back to per-actor passes")
            by_bnf = {}

        for i, actor in enumerate(actors, start=1):
            bnf_id = normalise(actor.get("BnF_ID", ""))
            rec = None
            if bnf_id not in out.done_keys:
                try:
                    rec = map_actor(actor, viaf_qids, by_bnf, threshold, sleep)
                    out.write(rec)
                except TransientError as exc:
                    deferred += 1
                    print(f"  [deferred] {bnf_id}: {exc}")
            if rec is not None:
                monitor_state = _monitor_checkpoint(monitor_module, monitor_state, i, total, rec)
            elif monitor_module and (i % MONITOR_CHECKPOINT_EVERY == 0 or i == total):
                monitor_state = monitor_module.update_monitor_state(
                    state=monitor_state,
                    context=f"Actor {i}/{total} ({bnf_id}): already done or deferred",
                    print_console=True)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed Wikidata mapping run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

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
        print(f"  {mt:<10} {stats[mt]:,}")
    if deferred:
        print(f"  {deferred:,} actors deferred after network errors: re-run the same command to retry them.")
    return stats


def main():
    parser = argparse.ArgumentParser(description="BnF → Wikidata mapping and enrichment")
    parser.add_argument("--input",        default=INPUT_DEFAULT)
    parser.add_argument("--viaf-mapping", default=VIAF_MAPPING_DEFAULT)
    parser.add_argument("--output",       default=OUTPUT_DEFAULT)
    parser.add_argument("--report",       default=REPORT_DEFAULT)
    parser.add_argument("--threshold",    type=float, default=THRESHOLD_DEFAULT)
    parser.add_argument("--sleep",        type=float, default=SLEEP_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",   action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    parser.add_argument("--restart",      action="store_true",
                        help="Discard the existing output and start from the first actor")
    args = parser.parse_args()
    run_mapping(args.input, args.viaf_mapping, args.output, args.report,
                args.threshold, args.sleep,
                use_monitor=not args.no_monitor,
                monitor_script=args.monitor_script, restart=args.restart)

if __name__ == "__main__":
    main()
