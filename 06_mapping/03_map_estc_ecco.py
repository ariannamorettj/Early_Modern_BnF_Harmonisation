#!/usr/bin/env python3
"""
03_map_estc_ecco.py  —  Module 06, Step 3
BnF editions → ESTC / ECCO matching.

Background
----------
ECCO (Eighteenth Century Collections Online) is based on the ESTC (English
Short Title Catalogue), harmonised and published as CSV by the Computational
History Group (COMHIS) at the University of Helsinki.  The COMHIS ESTC CSV
(estc_raw_sane.csv or a field-picked derivative) typically contains:

    estc_id, title, author, publication_place, year, language, ...

The BnF edition dataset covers the French Early Modern book trade (1450–1800),
with overlapping authors and titles (translations, bilingual editions, works
that circulated across the Channel).

Matching strategy
-----------------
Pass 1 — Identifier bridge (lossless):
    BnF actors in the optimised dataset carry VIAF IDs.  ESTC author records
    may carry VIAF IDs too (via the COMHIS harmonised author table).  A direct
    join on VIAF ID + publication year provides high-confidence edition links.

Pass 2 — Heuristic field matching, "same edition in both catalogues"
(editions without a shared ID):
    For each BnF edition:
      (a) Year filter  — only ESTC editions within ±2 years are candidates.
      (b) Author match — Levenshtein ratio on normalised author names ≥ 0.80.
      (c) Title match  — Levenshtein ratio on normalised, lowercased, stripped
                         titles ≥ 0.75.
    If (b) and (c) both pass → ACCEPTED, match_type = "heuristic"
    (confidence = mean of the two scores). The year filter is appropriate
    here because it targets the *same* print run appearing in both
    catalogues, which is necessarily close in time.

Pass 3 — LLM translation disambiguation (optional, requires API key):
    A translation can be published decades after the original work, so this
    pass does NOT use the year-windowed candidate pool from Pass 2. Instead
    it searches two candidate pools for the same BnF edition:
      - the Pass-2 year-windowed candidates whose title failed the Pass-2
        check (kept, for translations that do happen to fall in the window);
      - a year-unconstrained pool retrieved via an author-only index
        (`author_index`, blocked on the first token of the normalised author
        name — the library-authority "Surname, Firstname" convention), so a
        translation published at any distance in time from the BnF edition
        can still be found, as long as the author name matches
        (Levenshtein ratio ≥ author_threshold).
    For every candidate in either pool whose author matches but whose title
    does not, and whose language differs from the BnF edition's, a single
    call to the Anthropic Claude API asks:
        "Is '<title_bnf>' a translation of '<title_estc>'?
         Answer with JSON: {\"match\": true/false, \"confidence\": 0.0-1.0}"
    Candidates where match=true and confidence ≥ llm_threshold are collected
    as "accepted". If exactly one candidate is accepted → ACCEPTED with
    match_type = "llm". If MORE THAN ONE candidate is accepted for the same
    BnF edition, the match is not auto-resolved: this is common for prolific
    / classical authors with several independent translations (e.g. a French
    and an English translation of a Latin original are not translations of
    *each other*, even though both pass the author + language-mismatch
    check). In that case match_type = "ambiguous_translation" — the
    highest-confidence candidate is still recorded in the output row, but
    the `notes` field lists the alternates and the case is meant for manual
    review rather than being treated as a confident link.

    The API key is read from the environment variable ANTHROPIC_API_KEY.
    If the key is absent, Pass 3 is silently skipped.

Outputs
-------
output/estc_mapping.csv
    BnF_edition_id, estc_id, match_type, confidence,
    estc_title, estc_author, estc_year, estc_language,
    bnf_title, bnf_year, bnf_language, notes

report/estc_mapping_report.json
    summary statistics

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API (same mechanism
used by module 1's query_agents.R / query_editions.R, and by
02_map_wikidata.py): one checkpoint per processed BnF edition, plus a final
checkpoint on completion. Reports land in
00_monitor/report/03_map_estc_ecco_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python 06_mapping/03_map_estc_ecco.py \\
    --bnf-editions  data/bnf_edition_data/bnf_editions_ready.csv \\
    --estc-csv      data/estc/estc_raw_sane.csv \\
    --output        06_mapping/output/estc_mapping.csv \\
    --report        06_mapping/report/estc_mapping_report.json \\
    --author-threshold 0.80 \\
    --title-threshold  0.75 \\
    --llm-threshold    0.80 \\
    --year-window   2 \\
    --sleep         0.3

# disable the monitor report
python 06_mapping/03_map_estc_ecco.py --no-monitor
"""

import os, csv, sys, json, re, time, argparse, unicodedata, importlib.util
from difflib import SequenceMatcher
from collections import defaultdict
from pathlib import Path
from typing import Optional
import urllib.request, urllib.parse, urllib.error

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
BNF_EDITIONS_DEFAULT  = "data/bnf_edition_data/bnf_editions_ready.csv"
ESTC_CSV_DEFAULT      = "data/estc/estc_raw_sane.csv"
OUTPUT_DEFAULT        = "06_mapping/output/estc_mapping.csv"
REPORT_DEFAULT        = "06_mapping/report/estc_mapping_report.json"
AUTHOR_THRESHOLD      = 0.80
TITLE_THRESHOLD       = 0.75
LLM_THRESHOLD         = 0.80
YEAR_WINDOW           = 2
SLEEP_DEFAULT         = 0.3
MAX_AUTHOR_CANDIDATES_DEFAULT = 2000
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"

OUTPUT_FIELDS = [
    "BnF_edition_id", "estc_id", "match_type", "confidence",
    "estc_title", "estc_author", "estc_year", "estc_language",
    "bnf_title", "bnf_year", "bnf_language", "notes",
]

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


# ── Text normalisation ────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None: return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA","N/A","NULL","NONE",""} else s

def normalise_text(s: str) -> str:
    """Lowercase, strip accents, remove punctuation, collapse spaces."""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def similarity(a: str, b: str) -> float:
    na, nb = normalise_text(a), normalise_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()

def extract_year(s: str) -> Optional[int]:
    m = re.search(r"\b(1[0-9]{3}|[0-9]{3})\b", str(s))
    return int(m.group(1)) if m else None

def author_block_key(author: str) -> str:
    """Coarse blocking key for author-based (year-unconstrained) candidate
    retrieval: the first token of the normalised author string. Assumes the
    common library authority convention "Surname, Firstname" (VIAF/BnF/ESTC
    author fields), so the first token is usually the surname/main entry."""
    tokens = normalise_text(author).split()
    return tokens[0] if tokens else ""


# ── ESTC index builder ────────────────────────────────────────────────────────

def load_estc(path: str) -> tuple[list[dict], dict[int, list[int]]]:
    """
    Returns (records, year_index).
    year_index maps publication_year -> list of row indices.
    Accepts TSV (COMHIS format) or CSV.
    """
    print(f"Loading ESTC from {path} …")
    records = []
    sep = "\t" if path.endswith(".tsv") else ","
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=sep)
        for row in reader:
            records.append(row)
    print(f"  {len(records):,} ESTC records loaded.")

    # Build year index
    year_index: dict[int, list[int]] = defaultdict(list)
    year_cols = ["year", "publication_year", "year_first", "pub_year"]
    for i, rec in enumerate(records):
        y = None
        for col in year_cols:
            y = extract_year(normalise(rec.get(col, "")))
            if y:
                break
        if y:
            year_index[y].append(i)

    return records, year_index


# ── LLM translation check ─────────────────────────────────────────────────────

def llm_translation_check(title_a: str, title_b: str,
                           lang_a: str, lang_b: str,
                           sleep: float) -> tuple[bool, float]:
    """
    Ask Claude whether title_a (in lang_a) is a translation of title_b (in lang_b).
    Returns (is_match, confidence).  Falls back to (False, 0.0) on any error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return False, 0.0

    prompt = (
        f'Is the title "{title_a}" (language: {lang_a}) '
        f'a translation or equivalent of "{title_b}" (language: {lang_b})?\n'
        f'Answer ONLY with valid JSON on a single line: '
        f'{{"match": true or false, "confidence": 0.0 to 1.0}}'
    )
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 100,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    try:
        req = urllib.request.Request(CLAUDE_API_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["content"][0]["text"].strip()
        # Strip possible markdown fences
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)
        time.sleep(sleep)
        return bool(result.get("match", False)), float(result.get("confidence", 0.0))
    except Exception as e:
        print(f"    [LLM error] {e}")
        time.sleep(sleep)
        return False, 0.0


# ── Candidate retrieval ───────────────────────────────────────────────────────

def get_estc_candidates(bnf_year: Optional[int],
                        estc_records: list[dict],
                        year_index: dict[int, list[int]],
                        year_window: int) -> list[int]:
    """Return row indices of ESTC records within ±year_window of bnf_year."""
    if bnf_year is None:
        return list(range(min(5000, len(estc_records))))  # no year: take first 5k
    indices = set()
    for y in range(bnf_year - year_window, bnf_year + year_window + 1):
        indices.update(year_index.get(y, []))
    return list(indices)


# ── Author index (year-unconstrained candidate pool for translation search) ───
#
# A translation can be published decades (or centuries) after the original
# work, so the year-windowed candidate pool above is not appropriate for
# translation detection (Pass 3). This index instead blocks candidates by
# author only, so Pass 3 can search across the full ESTC time range.

def build_author_index(estc_records: list[dict], author_col: str) -> dict[str, list[int]]:
    index: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(estc_records):
        author = normalise(rec.get(author_col, ""))
        if not author:
            continue
        key = author_block_key(author)
        if key:
            index[key].append(i)
    return index


def get_estc_author_candidates(bnf_author: str,
                               author_index: dict[str, list[int]],
                               max_candidates: int) -> list[int]:
    """Return row indices of ESTC records sharing an author block key with
    bnf_author, capped at max_candidates (mirrors the existing "first 5k"
    cap used by get_estc_candidates for year-less BnF editions)."""
    if not bnf_author:
        return []
    key = author_block_key(bnf_author)
    if not key:
        return []
    return author_index.get(key, [])[:max_candidates]


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and 02_map_wikidata.py."""
    project_root = Path(__file__).resolve().parents[1]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_estc_ecco", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, rec):
    if monitor_module is None:
        return monitor_state
    context = (f"Processed edition {rec['BnF_edition_id']} (index {index}/{total}) "
              f"- match_type={rec['match_type'] or 'unmatched'}")
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_mapping(bnf_path, estc_path, output_path, report_path,
                author_thr, title_thr, llm_thr, year_window, sleep,
                max_author_candidates=MAX_AUTHOR_CANDIDATES_DEFAULT,
                use_monitor=False, monitor_script=MONITOR_SCRIPT_DEFAULT):

    # Load BnF editions
    bnf_editions = []
    with open(bnf_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        bnf_editions = list(csv.DictReader(f))
    print(f"Loaded {len(bnf_editions):,} BnF editions.")

    # Load ESTC
    estc_records, year_index = load_estc(estc_path)

    # Detect ESTC column names (flexible)
    sample = estc_records[0] if estc_records else {}
    estc_title_col  = next((c for c in sample if "title" in c.lower()), "title")
    estc_author_col = next((c for c in sample if "author" in c.lower()), "author")
    estc_year_col   = next((c for c in ["year","publication_year","year_first","pub_year"]
                            if c in sample), "year")
    estc_lang_col   = next((c for c in sample if "lang" in c.lower()), "language")
    estc_id_col     = next((c for c in ["estc_id","record_id","id"] if c in sample), "estc_id")

    author_index = build_author_index(estc_records, estc_author_col)

    results = []
    stats = {
        "total": len(bnf_editions),
        "pass1_id": 0,
        "pass2_heuristic": 0,
        "pass3_llm": 0,
        "pass3_llm_ambiguous": 0,
        "unmatched": 0,
    }

    api_key_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key_available:
        print("  [info] ANTHROPIC_API_KEY not set — LLM pass disabled.")

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during 03_map_estc_ecco.py execution",
            print_start_message=True,
        )

    for i, bnf in enumerate(bnf_editions):
        if (i + 1) % 1000 == 0:
            print(f"  … {i+1:,}/{len(bnf_editions):,}")

        bnf_id    = normalise(bnf.get("bnf_id") or bnf.get("edition", ""))
        bnf_title = normalise(bnf.get("title", ""))
        bnf_year  = extract_year(normalise(bnf.get("year_first", "")))
        bnf_lang  = normalise(bnf.get("language", "")).lower()
        # Author URI in BnF → we compare with name-based author in ESTC
        bnf_author = normalise(bnf.get("author_name", "")
                               or bnf.get("author", ""))

        rec = {f: "" for f in OUTPUT_FIELDS}
        rec["BnF_edition_id"] = bnf_id
        rec["bnf_title"]      = bnf_title
        rec["bnf_year"]       = str(bnf_year) if bnf_year else ""
        rec["bnf_language"]   = bnf_lang

        # ── Pass 1: shared VIAF author ID (not yet in CSV → placeholder) ─────
        # When the BnF actor mapping and ESTC author table both expose VIAF IDs
        # a pre-join can be performed upstream to populate bnf.viaf_author_id.
        viaf_match = normalise(bnf.get("viaf_author_id", ""))
        # (VIAF-based join logic to be extended when ESTC author table available)

        # ── Pass 2: heuristic (same-edition match, year-windowed) ────────────
        year_candidates = get_estc_candidates(bnf_year, estc_records, year_index, year_window)
        year_candidates_set = set(year_candidates)
        best_rec, best_conf = None, 0.0

        # Pass-3 candidates that passed the LLM translation check, collected
        # across BOTH pools (year-windowed + author-indexed) so that multiple
        # plausible independent translations (e.g. of a classical author) can
        # be recognised as ambiguous rather than one being silently picked.
        llm_accepted = []  # list of (estc_record, confidence)
        llm_checked_idx = set()

        def try_llm_translation_check(idx, estc, auth_score):
            estc_lang = normalise(estc.get(estc_lang_col, "")).lower()
            estc_title = normalise(estc.get(estc_title_col, ""))
            if not (bnf_lang and estc_lang and bnf_lang != estc_lang
                   and bnf_title and estc_title):
                return
            is_match, llm_conf = llm_translation_check(
                bnf_title, estc_title, bnf_lang, estc_lang, sleep
            )
            if is_match and llm_conf >= llm_thr:
                conf = (auth_score + llm_conf) / 2
                llm_accepted.append((estc, conf))

        for idx in year_candidates:
            estc = estc_records[idx]
            estc_author = normalise(estc.get(estc_author_col, ""))
            estc_title  = normalise(estc.get(estc_title_col, ""))

            # Author check
            if bnf_author and estc_author:
                auth_score = similarity(bnf_author, estc_author)
            else:
                auth_score = 0.5  # unknown author: neutral

            if auth_score < author_thr:
                continue

            # Title check
            if bnf_title and estc_title:
                title_score = similarity(bnf_title, estc_title)
            else:
                title_score = 0.0

            if title_score >= title_thr:
                conf = (auth_score + title_score) / 2
                if conf > best_conf:
                    best_conf = conf
                    best_rec  = estc
                continue

            # ── Pass 3: LLM translation check (in-window candidates) ────────
            if api_key_available:
                llm_checked_idx.add(idx)
                try_llm_translation_check(idx, estc, auth_score)

        # ── Pass 3 continued: author-indexed candidates, no year constraint ──
        # Translations can be published long after the original, so this
        # second pool is not restricted to year_candidates.
        if api_key_available and bnf_author:
            author_candidates = get_estc_author_candidates(
                bnf_author, author_index, max_author_candidates)
            for idx in author_candidates:
                if idx in year_candidates_set or idx in llm_checked_idx:
                    continue  # already checked above
                estc = estc_records[idx]
                estc_author = normalise(estc.get(estc_author_col, ""))
                if not estc_author:
                    continue
                auth_score = similarity(bnf_author, estc_author)
                if auth_score < author_thr:
                    continue
                try_llm_translation_check(idx, estc, auth_score)

        if best_rec:
            # A Pass-2 heuristic match (title similarity, not just author +
            # LLM judgement) is stronger evidence than a Pass-3 translation
            # guess, so it always takes priority when one exists.
            rec["estc_id"]       = normalise(best_rec.get(estc_id_col, ""))
            rec["match_type"]    = "heuristic"
            rec["confidence"]    = f"{best_conf:.3f}"
            rec["estc_title"]    = normalise(best_rec.get(estc_title_col, ""))
            rec["estc_author"]   = normalise(best_rec.get(estc_author_col, ""))
            rec["estc_year"]     = normalise(best_rec.get(estc_year_col, ""))
            rec["estc_language"] = normalise(best_rec.get(estc_lang_col, ""))
            stats["pass2_heuristic"] += 1
        elif llm_accepted:
            llm_accepted.sort(key=lambda pair: pair[1], reverse=True)
            top_rec, top_conf = llm_accepted[0]
            rec["estc_id"]       = normalise(top_rec.get(estc_id_col, ""))
            rec["confidence"]    = f"{top_conf:.3f}"
            rec["estc_title"]    = normalise(top_rec.get(estc_title_col, ""))
            rec["estc_author"]   = normalise(top_rec.get(estc_author_col, ""))
            rec["estc_year"]     = normalise(top_rec.get(estc_year_col, ""))
            rec["estc_language"] = normalise(top_rec.get(estc_lang_col, ""))
            if len(llm_accepted) > 1:
                # Multiple plausible translation candidates for the same
                # author (typical of classical authors with several
                # independent translations): don't silently guess — flag for
                # manual review instead of asserting a direct link.
                rec["match_type"] = "ambiguous_translation"
                alt_ids = ", ".join(
                    normalise(alt_rec.get(estc_id_col, "")) or "?"
                    for alt_rec, _ in llm_accepted[1:4]
                )
                rec["notes"] = (
                    f"{len(llm_accepted)} candidate translations passed the "
                    f"LLM check; picked highest-confidence, alternates: {alt_ids}"
                )
                stats["pass3_llm_ambiguous"] += 1
            else:
                rec["match_type"] = "llm"
                stats["pass3_llm"] += 1
        else:
            rec["match_type"] = "unmatched"
            stats["unmatched"] += 1

        results.append(rec)
        monitor_state = _monitor_checkpoint(
            monitor_module, monitor_state, i + 1, len(bnf_editions), rec)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed ESTC/ECCO mapping run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

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
    print(f"  Pass-1 (ID)         : {stats['pass1_id']:,}")
    print(f"  Pass-2 (heuristic)  : {stats['pass2_heuristic']:,}")
    print(f"  Pass-3 (LLM)        : {stats['pass3_llm']:,}")
    print(f"  Pass-3 (ambiguous)  : {stats['pass3_llm_ambiguous']:,}")
    print(f"  Unmatched           : {stats['unmatched']:,}")


def main():
    parser = argparse.ArgumentParser(
        description="BnF editions → ESTC/ECCO matching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--bnf-editions",    default=BNF_EDITIONS_DEFAULT)
    parser.add_argument("--estc-csv",        default=ESTC_CSV_DEFAULT)
    parser.add_argument("--output",          default=OUTPUT_DEFAULT)
    parser.add_argument("--report",          default=REPORT_DEFAULT)
    parser.add_argument("--author-threshold", type=float, default=AUTHOR_THRESHOLD)
    parser.add_argument("--title-threshold",  type=float, default=TITLE_THRESHOLD)
    parser.add_argument("--llm-threshold",    type=float, default=LLM_THRESHOLD)
    parser.add_argument("--year-window",      type=int,   default=YEAR_WINDOW)
    parser.add_argument("--sleep",            type=float, default=SLEEP_DEFAULT)
    parser.add_argument("--max-author-candidates", type=int, default=MAX_AUTHOR_CANDIDATES_DEFAULT,
                        help="Cap on ESTC candidates retrieved per BnF edition via the "
                             "year-unconstrained author index (Pass 3 translation search).")
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",   action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run_mapping(
        args.bnf_editions, args.estc_csv,
        args.output, args.report,
        args.author_threshold, args.title_threshold, args.llm_threshold,
        args.year_window, args.sleep,
        max_author_candidates=args.max_author_candidates,
        use_monitor=not args.no_monitor,
        monitor_script=args.monitor_script,
    )

if __name__ == "__main__":
    main()
