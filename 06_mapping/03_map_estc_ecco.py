#!/usr/bin/env python3
"""
03_map_estc_ecco.py  —  Module 06, Step 3
BnF editions → ESTC / ECCO matching.

Background
----------
ECCO (Eighteenth Century Collections Online) is based on the ESTC (English
Short Title Catalogue), harmonised and published as CSV by the Computational
History Group (COMHIS) at the University of Helsinki. The COMHIS release in
data/estc/ is split in three tables:

    estc_core.csv         one row per ESTC record: estc_id, short_title,
                          publication_year, primary_language,
                          publication_place, publication_country, ...
    estc_actor_links.csv  estc_id -> actor_id, with one boolean column per
                          role (actor_role_author, ...)
    estc_actors.csv       actor_id -> name_unified, viaf_link, dates

`--estc` accepts that directory (the three tables are joined on load) or a
single CSV with estc_id, title, author, year, language columns.

The ESTC covers what was printed in English anywhere, and anything printed
in the British Isles and British America, up to 1800. A BnF edition can
only have an ESTC record inside that scope, so Passes 1 and 2 only look at
BnF editions in English or published in those countries (about 45,000 of
the 814,031). The other editions are counted in the report and not written.

Matching strategy
-----------------
All passes compare the BnF edition with ESTC records of the same author, so
no pass ever scans the whole ESTC.

Pass 1 — Actor bridge (same edition, author certain):
    05_map_estc_actors.py links BnF actors to ESTC actors (confident rows
    only: shared VIAF id, or name + dates). For each author of the BnF
    edition that has such a link, the candidates are that ESTC actor's own
    records within ±year_window years; a title similarity ≥ title_threshold
    accepts one. match_type = "actor_bridge", confidence = (1 + title) / 2.

Pass 2 — Heuristic, "same edition in both catalogues" (no actor link):
    ESTC records are indexed by (publication year, author-name token).
    Candidates share a name token with a BnF author and fall within
    ±year_window years. Author names are compared as order-invariant token
    sets (BnF "Given Family", ESTC "Family, Given"), titles on their common
    length (ESTC keeps a short title, BnF the full one). Author ≥
    author_threshold and title ≥ title_threshold → match_type = "heuristic",
    confidence = mean of the two scores.

    Editions without an author are not matched: a title and a year alone
    are not enough evidence for the same edition.

Ambiguity:
    When a second ESTC record scores within AMBIGUITY_MARGIN of the best one
    (typically the same title reissued in consecutive years), a single
    near-tie with the BnF edition's own year is taken as the match. Otherwise
    the edition is not auto-resolved: match_type gets
    the prefix "ambiguous_", the best candidate is kept and `notes` lists
    the alternates. 04_merge_mappings.py writes it to estc_candidate_id,
    not estc_id.

Pass 3 — LLM translation disambiguation (optional, requires API key):
    A translation can be published decades after the original work, so this
    pass does NOT use the year-windowed candidate pool from Pass 2. Instead
    it searches two candidate pools for the same BnF edition:
      - the Pass-2 year-windowed candidates whose author matched but whose
        title failed the Pass-2 check;
      - a year-unconstrained pool retrieved via an author-only index
        (`author_index`, blocked on the first token of the normalised author
        name — the library-authority "Surname, Firstname" convention).
    For every candidate in either pool whose author matches but whose title
    does not, and whose language differs from the BnF edition's, a single
    call to the Anthropic Claude API asks whether one title translates the
    other. If exactly one candidate is accepted → match_type = "llm"; if
    more than one → "ambiguous_translation" (see Ambiguity).

    The API key is read from the environment variable ANTHROPIC_API_KEY.
    If the key is absent, Pass 3 is skipped, and so are the editions outside
    the ESTC scope. With a key, every edition with an author goes through
    Pass 3, since a French edition can have an English translation in ESTC.

Outputs
-------
output/estc_mapping.csv
    BnF_edition_id, estc_id, match_type, confidence,
    estc_title, estc_author, estc_year, estc_language,
    bnf_title, bnf_year, bnf_language, notes

report/estc_mapping_report.json
    counts per match_type, computed from the whole output file

Resilience
----------
Results are appended to the output CSV as they are produced
(06_mapping/resumable.py): re-running the same command resumes at the
first edition not yet written, --restart starts over.

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API (same mechanism
used by module 1's query_agents.R / query_editions.R, and by
02_map_wikidata.py): one checkpoint every MONITOR_CHECKPOINT_EVERY (1000)
BnF editions and at the last one, plus a final checkpoint on completion.
Reports land in 00_monitor/report/03_map_estc_ecco_<timestamp>_py.txt.
Disable with --no-monitor.

Usage
-----
python 06_mapping/03_map_estc_ecco.py \\
    --bnf-editions  data/bnf_edition_data/bnf_editions_ready.csv \\
    --bnf-actors    04_harmonisation_and_evaluation/output/bnf_actors_ready.csv \\
    --estc          data/estc \\
    --estc-actor-mapping 06_mapping/output/estc_actor_mapping_confident.csv \\
    --output        06_mapping/output/estc_mapping.csv \\
    --report        06_mapping/report/estc_mapping_report.json \\
    --author-threshold 0.80 \\
    --title-threshold  0.75 \\
    --llm-threshold    0.80 \\
    --year-window   2

# start over instead of resuming; disable the monitor report
python 06_mapping/03_map_estc_ecco.py --restart --no-monitor
"""

import os, csv, sys, json, re, time, argparse, unicodedata, importlib.util
from difflib import SequenceMatcher
from collections import defaultdict, Counter
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resumable import ResumableCsvWriter, read_rows  # noqa: E402

# ── Defaults ──────────────────────────────────────────────────────────────────
BNF_EDITIONS_DEFAULT  = "data/bnf_edition_data/bnf_editions_ready.csv"
BNF_ACTORS_DEFAULT    = "04_harmonisation_and_evaluation/output/bnf_actors_ready.csv"
ESTC_DEFAULT          = "data/estc"
ESTC_ACTOR_MAPPING_DEFAULT = "06_mapping/output/estc_actor_mapping_confident.csv"
DEDUP_MAPPING_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "01_heuristic_rules/output/actor_dedup_mapping.csv"
)
OUTPUT_DEFAULT        = "06_mapping/output/estc_mapping.csv"
REPORT_DEFAULT        = "06_mapping/report/estc_mapping_report.json"
AUTHOR_THRESHOLD      = 0.80
TITLE_THRESHOLD       = 0.75
LLM_THRESHOLD         = 0.80
YEAR_WINDOW           = 2
AMBIGUITY_MARGIN      = 0.02
SLEEP_DEFAULT         = 0.3
MAX_AUTHOR_CANDIDATES_DEFAULT = 2000
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per record cost ~55 ms each (mostly the nvidia-smi GPU read);
# checkpoint every N records plus the last one instead, like
# 06_mapping/05_map_estc_actors.py. Passes 1-2 are local, so N matches the
# other local scripts.
MONITOR_CHECKPOINT_EVERY = 1000

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"

OUTPUT_FIELDS = [
    "BnF_edition_id", "estc_id", "match_type", "confidence",
    "estc_title", "estc_author", "estc_year", "estc_language",
    "bnf_title", "bnf_year", "bnf_language", "notes",
]

# The ESTC's own scope: English-language items anywhere, and everything
# printed in the British Isles and British America. Values as they appear
# in module 04's language_harmonised / publication_country columns.
ESTC_SCOPE_LANGUAGES = {"eng", "enm"}
ESTC_SCOPE_COUNTRIES = {
    "Great Britain", "United Kingdom", "England", "Scotland", "Wales",
    "Ireland", "Northern Ireland", "United States", "Canada", "Jamaica",
    "Barbados", "Bermuda", "Antigua and Barbuda", "Saint Kitts and Nevis",
    "Bahamas",
}

# ISO 639-2 codes for the ESTC's primary_language names, so that Pass 3
# compares like with like.
ESTC_LANGUAGE_CODES = {
    "english": "eng", "french": "fre", "latin": "lat", "german": "ger",
    "italian": "ita", "spanish": "spa", "dutch": "dut", "welsh": "wel",
    "greek": "grc", "hebrew": "heb", "portuguese": "por", "irish": "gle",
    "scottish gaelic": "gla", "danish": "dan", "swedish": "swe",
}

# Name tokens too common to block on.
NAME_STOPWORDS = {
    "and", "the", "of", "de", "du", "des", "la", "le", "les", "von", "van",
    "der", "den", "di", "da", "del", "sir", "saint", "st", "mr", "mrs",
}

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


# ── Text normalisation ────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None: return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA","N/A","NULL","NONE",""} else s

LIGATURES = str.maketrans({"æ": "ae", "œ": "oe", "ß": "ss", "ſ": "s"})

# Words skipped when looking for a title's first distinctive word.
TITLE_STOPWORDS = {
    "the", "and", "with", "from", "that", "this", "their", "upon", "unto",
    "les", "des", "dans", "avec", "pour", "sur", "une", "par",
    "della", "delle", "degli", "dell", "sopra", "cum", "sive", "seu",
}


def normalise_text(s: str) -> str:
    """Lowercase, strip accents, expand ligatures, remove punctuation, collapse spaces."""
    s = s.lower().translate(LIGATURES)
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

def author_similarity(a: str, b: str) -> float:
    """Order-invariant name comparison: "Jonathan Swift" == "Swift, Jonathan"."""
    ta, tb = sorted(normalise_text(a).split()), sorted(normalise_text(b).split())
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()

def _head_word(tokens: list) -> str:
    """First distinctive word of a title: four letters or more, not a stopword."""
    return next((t for t in tokens if len(t) >= 4 and t not in TITLE_STOPWORDS
                 and not t.isdigit()), "")

def _heads_agree(ta: list, tb: list) -> bool:
    """The first distinctive word of one title appears in the other. Two
    titles that share only their boilerplate ("a tragedy, as performed at
    the Theatre-Royal") start with different words. Checked both ways,
    because ESTC short titles sometimes open with the author's name
    ("Antonii le Grand Historia naturae")."""
    ha, hb = _head_word(ta), _head_word(tb)
    if not ha or not hb:
        return True
    return ha in tb or hb in ta

def title_similarity(a: str, b: str) -> float:
    """Titles compared on their common length: ESTC keeps a short title,
    BnF the full title with its statement of responsibility. The longer one
    is cut to the shorter one's length plus two words; titles of fewer than
    four words are compared whole, so "Poems" does not match "Poems on
    several occasions"."""
    ta, tb = normalise_text(a).split(), normalise_text(b).split()
    if not ta or not tb:
        return 0.0
    if not _heads_agree(ta, tb):
        return 0.0
    n = min(len(ta), len(tb))
    if n >= 4:
        ta, tb = ta[:n + 2], tb[:n + 2]
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()

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

def name_block_tokens(author: str) -> set:
    """Tokens an author name is indexed under for Pass 2."""
    return {t for t in normalise_text(author).split()
            if len(t) >= 3 and t not in NAME_STOPWORDS and not t.isdigit()}

def strip_brackets(iri: str) -> str:
    return normalise(iri).strip("<>")

def language_code(value: str) -> str:
    """'<http://id.loc.gov/vocabulary/iso639-2/eng>' / 'English' / 'eng' -> 'eng'."""
    v = normalise(value).strip("<>").rstrip("/")
    if "/" in v:
        v = v.rsplit("/", 1)[1]
    v = v.lower()
    return ESTC_LANGUAGE_CODES.get(v, v)


# ── ESTC loading ──────────────────────────────────────────────────────────────

def _estc_record(estc_id, title, authors, author_ids, year, language, place="", country=""):
    return {
        "estc_id": estc_id, "title": title,
        "author": "; ".join(authors), "authors": authors, "author_ids": author_ids,
        "year": str(year) if year else "", "year_int": year,
        "language": language, "place": place, "country": country,
    }

def load_estc_directory(path: str) -> list:
    """Join the three COMHIS tables into one record per ESTC item."""
    root = Path(path)
    names = {}
    with open(root / "estc_actors.csv", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            name = normalise(row.get("name_unified", ""))
            if name:
                names[row["actor_id"]] = name

    authors_of = defaultdict(list)
    with open(root / "estc_actor_links.csv", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("actor_role_author") != "TRUE":
                continue
            aid = normalise(row.get("actor_id", ""))
            if aid and aid not in authors_of[row["estc_id"]]:
                authors_of[row["estc_id"]].append(aid)

    records = []
    with open(root / "estc_core.csv", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            estc_id = row["estc_id"]
            year = (extract_year(normalise(row.get("publication_year", "")))
                    or extract_year(normalise(row.get("publication_year_from", ""))))
            ids = authors_of.get(estc_id, [])
            records.append(_estc_record(
                estc_id, normalise(row.get("short_title", "")),
                [names[a] for a in ids if a in names], ids, year,
                normalise(row.get("primary_language", "")),
                normalise(row.get("publication_place", "")),
                normalise(row.get("publication_country", "")),
            ))
    return records

def load_estc_csv(path: str) -> list:
    """A single CSV (or TSV) with estc_id / title / author / year / language
    columns, whatever their exact names."""
    sep = "\t" if path.endswith(".tsv") else ","
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        rows = list(csv.DictReader(f, delimiter=sep))
    sample = rows[0] if rows else {}
    title_col  = next((c for c in sample if "title" in c.lower()), "title")
    author_col = next((c for c in sample if "author" in c.lower()), "author")
    year_cols  = [c for c in ["year", "publication_year", "year_first", "pub_year"] if c in sample]
    lang_col   = next((c for c in sample if "lang" in c.lower()), "language")
    id_col     = next((c for c in ["estc_id", "record_id", "id"] if c in sample), "estc_id")
    records = []
    for row in rows:
        year = next((y for y in (extract_year(normalise(row.get(c, ""))) for c in year_cols) if y), None)
        author = normalise(row.get(author_col, ""))
        records.append(_estc_record(
            normalise(row.get(id_col, "")), normalise(row.get(title_col, "")),
            [author] if author else [], [], year, normalise(row.get(lang_col, "")),
        ))
    return records

def load_estc(path: str) -> list:
    print(f"Loading ESTC from {path} …")
    records = load_estc_directory(path) if os.path.isdir(path) else load_estc_csv(path)
    print(f"  {len(records):,} ESTC records loaded "
          f"({sum(1 for r in records if r['authors']):,} with an author).")
    return records


# ── ESTC indexes ──────────────────────────────────────────────────────────────

def build_actor_index(estc_records: list) -> dict:
    """ESTC actor_id -> row indices of the records it authored (Pass 1)."""
    index = defaultdict(list)
    for i, rec in enumerate(estc_records):
        for aid in rec["author_ids"]:
            index[aid].append(i)
    return index

def build_name_year_index(estc_records: list) -> dict:
    """(year, author-name token) -> row indices (Pass 2)."""
    index = defaultdict(list)
    for i, rec in enumerate(estc_records):
        if not rec["year_int"]:
            continue
        tokens = set()
        for author in rec["authors"]:
            tokens |= name_block_tokens(author)
        for t in tokens:
            index[(rec["year_int"], t)].append(i)
    return index


# ── Author index (year-unconstrained candidate pool for translation search) ───
#
# A translation can be published decades (or centuries) after the original
# work, so the year-windowed candidate pool above is not appropriate for
# translation detection (Pass 3). This index instead blocks candidates by
# author only, so Pass 3 can search across the full ESTC time range.

def build_author_index(estc_records: list[dict], author_col: str = "author") -> dict[str, list[int]]:
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
    bnf_author, capped at max_candidates."""
    if not bnf_author:
        return []
    key = author_block_key(bnf_author)
    if not key:
        return []
    return author_index.get(key, [])[:max_candidates]


# ── BnF side ──────────────────────────────────────────────────────────────────

def load_actor_names(path: str) -> dict:
    """BnF actor IRI (no brackets) -> display name, from module 04's actors."""
    names = {}
    if not path or not os.path.exists(path):
        print(f"  [info] No BnF actors file at {path!r}; author names come "
              "from the editions' author_name column only.")
        return names
    with open(path, encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            iri = strip_brackets(row.get("actor") or row.get("BnF_ID", ""))
            name = normalise(row.get("actor_name", ""))
            if not name:
                name = " ".join(p for p in (normalise(row.get("actor_first_name", "")),
                                            normalise(row.get("actor_last_name", ""))) if p)
            if iri and name:
                names[iri] = name
    return names

def load_estc_actor_mapping(mapping_path: str, dedup_path: str) -> dict:
    """BnF actor IRI (no brackets) -> ESTC actor_id, for the confident rows
    of 05_map_estc_actors.py. The mapping is keyed by canonical actor; the
    dedup table adds the duplicates that editions may still point to."""
    mapping = {}
    if not mapping_path or not os.path.exists(mapping_path):
        print(f"  [info] No ESTC actor mapping at {mapping_path!r}; Pass 1 disabled.")
        return mapping
    for row in read_rows(mapping_path):
        bnf, estc = strip_brackets(row.get("BnF_ID", "")), normalise(row.get("estc_actor_id", ""))
        if bnf and estc:
            mapping[bnf] = estc
    if dedup_path and os.path.exists(dedup_path):
        for row in read_rows(dedup_path):
            uri = strip_brackets(row.get("actor_uri", ""))
            canon = strip_brackets(row.get("canonical_actor_uri", ""))
            if uri and canon in mapping and uri not in mapping:
                mapping[uri] = mapping[canon]
    return mapping

def edition_authors(bnf: dict, actor_names: dict) -> list:
    """[(iri, name)] for the edition's authors; iri is "" for a bare name."""
    authors = []
    for iri in re.findall(r"<([^>]+)>", bnf.get("author", "")):
        authors.append((iri, actor_names.get(iri, "")))
    name = normalise(bnf.get("author_name", ""))
    if name:
        authors.append(("", name))
    return authors

def in_estc_scope(bnf: dict) -> bool:
    """English-language, or printed where the ESTC collects. Tables without
    module 04's harmonised columns are treated as in scope."""
    if "language_harmonised" not in bnf and "publication_country" not in bnf:
        return True
    return (normalise(bnf.get("language_harmonised", "")).lower() in ESTC_SCOPE_LANGUAGES
            or normalise(bnf.get("publication_country", "")) in ESTC_SCOPE_COUNTRIES)


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
    if index % MONITOR_CHECKPOINT_EVERY and index != total:
        return monitor_state
    context = (f"Processed edition {rec['BnF_edition_id']} (index {index}/{total}) "
              f"- match_type={rec['match_type'] or 'unmatched'}")
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


# ── Matching one edition ──────────────────────────────────────────────────────

def _best_author_score(bnf_names: list, estc_rec: dict) -> float:
    return max((author_similarity(a, b) for a in bnf_names for b in estc_rec["authors"]),
               default=0.0)

def _resolve(accepted: list, match_type: str, bnf_year: Optional[int] = None):
    """accepted: [(estc_record, confidence)] -> (best, confidence, match_type, notes)."""
    by_id = {}
    for rec, conf in accepted:
        if conf > by_id.get(rec["estc_id"], (None, -1))[1]:
            by_id[rec["estc_id"]] = (rec, conf)
    ranked = sorted(by_id.values(), key=lambda pair: pair[1], reverse=True)
    best, conf = ranked[0]
    if match_type == "llm":
        # Every accepted translation is a rival: two independent translations
        # of a classical author are not translations of each other.
        rivals = [r for r, _ in ranked[1:]]
    else:
        tied = [(r, c) for r, c in ranked if c >= conf - AMBIGUITY_MARGIN]
        # Among near-ties, the same edition has the same year: a single
        # record with the BnF year settles it (the others are usually the
        # same title reissued a year or two apart).
        same_year = [(r, c) for r, c in tied if bnf_year and r["year_int"] == bnf_year]
        if len(tied) > 1 and len(same_year) == 1:
            best, conf = same_year[0]
            tied = same_year
        rivals = [r for r, _ in tied if r is not best]
    if not rivals:
        return best, conf, match_type, ""
    alt_ids = ", ".join(r["estc_id"] or "?" for r in rivals[:3])
    if match_type == "llm":
        return best, conf, "ambiguous_translation", (
            f"{len(ranked)} candidate translations passed the LLM check; "
            f"picked highest-confidence, alternates: {alt_ids}")
    return best, conf, f"ambiguous_{match_type}", (
        f"{len(rivals) + 1} ESTC records within {AMBIGUITY_MARGIN} of the best "
        f"score; alternates: {alt_ids}")


def match_edition(bnf: dict, ctx: dict) -> dict:
    estc_records = ctx["estc_records"]
    bnf_id    = normalise(bnf.get("bnf_id") or bnf.get("edition", ""))
    bnf_title = normalise(bnf.get("title", ""))
    bnf_year  = extract_year(normalise(bnf.get("year_first", "")))
    bnf_lang  = language_code(bnf.get("language_harmonised") or bnf.get("language", ""))
    authors   = edition_authors(bnf, ctx["actor_names"])
    bnf_names = [name for _, name in authors if name]

    rec = {f: "" for f in OUTPUT_FIELDS}
    rec.update(BnF_edition_id=bnf_id, bnf_title=bnf_title,
               bnf_year=str(bnf_year) if bnf_year else "", bnf_language=bnf_lang)

    in_scope = in_estc_scope(bnf)
    window = ctx["year_window"]
    accepted, match_type = [], ""
    title_failed = []  # (idx, author score): Pass-3 in-window pool

    if in_scope and bnf_year and bnf_title:
        # Pass 1: actor bridge
        for iri, _ in authors:
            estc_actor = ctx["actor_mapping"].get(iri)
            for idx in ctx["actor_index"].get(estc_actor, []) if estc_actor else []:
                estc = estc_records[idx]
                if estc["year_int"] is None or abs(estc["year_int"] - bnf_year) > window:
                    continue
                ts = title_similarity(bnf_title, estc["title"])
                if ts >= ctx["title_thr"]:
                    accepted.append((estc, (1 + ts) / 2))
        if accepted:
            match_type = "actor_bridge"

        # Pass 2: name + year blocking
        if not accepted and bnf_names:
            tokens = set()
            for name in bnf_names:
                tokens |= name_block_tokens(name)
            candidates = set()
            for y in range(bnf_year - window, bnf_year + window + 1):
                for t in tokens:
                    candidates.update(ctx["name_year_index"].get((y, t), ()))
            for idx in candidates:
                estc = estc_records[idx]
                auth = _best_author_score(bnf_names, estc)
                if auth < ctx["author_thr"]:
                    continue
                ts = title_similarity(bnf_title, estc["title"])
                if ts >= ctx["title_thr"]:
                    accepted.append((estc, (auth + ts) / 2))
                else:
                    title_failed.append((idx, auth))
            if accepted:
                match_type = "heuristic"

    # Pass 3: LLM translation check
    if not accepted and ctx["api_key_available"] and bnf_names and bnf_title:
        checked = set()

        def check(idx, auth):
            if idx in checked:
                return
            checked.add(idx)
            estc = estc_records[idx]
            estc_lang = language_code(estc["language"])
            if not (bnf_lang and estc_lang and bnf_lang != estc_lang and estc["title"]):
                return
            ok, llm_conf = llm_translation_check(bnf_title, estc["title"], bnf_lang,
                                                 estc_lang, ctx["sleep"])
            if ok and llm_conf >= ctx["llm_thr"]:
                accepted.append((estc, (auth + llm_conf) / 2))

        for idx, auth in title_failed:
            check(idx, auth)
        for name in bnf_names:
            for idx in get_estc_author_candidates(name, ctx["author_index"],
                                                  ctx["max_author_candidates"]):
                if idx in checked:
                    continue
                auth = _best_author_score([name], estc_records[idx])
                if auth >= ctx["author_thr"]:
                    check(idx, auth)
        if accepted:
            match_type = "llm"

    if accepted:
        best, conf, rec["match_type"], rec["notes"] = _resolve(accepted, match_type, bnf_year)
        rec.update(estc_id=best["estc_id"], confidence=f"{conf:.3f}",
                   estc_title=best["title"], estc_author=best["author"],
                   estc_year=best["year"], estc_language=best["language"])
    elif in_scope or ctx["api_key_available"]:
        rec["match_type"] = "unmatched"
    else:
        rec["match_type"] = "out_of_scope"
    return rec


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_mapping(bnf_path, estc_path, output_path, report_path,
                author_thr, title_thr, llm_thr, year_window, sleep,
                max_author_candidates=MAX_AUTHOR_CANDIDATES_DEFAULT,
                use_monitor=False, monitor_script=MONITOR_SCRIPT_DEFAULT,
                bnf_actors_path=None, estc_actor_mapping_path=None,
                dedup_mapping_path=None, restart=False):

    with open(bnf_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        bnf_editions = list(csv.DictReader(f))
    print(f"Loaded {len(bnf_editions):,} BnF editions.")

    estc_records = load_estc(estc_path)
    api_key_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key_available:
        print("  [info] ANTHROPIC_API_KEY not set — LLM pass disabled, "
              "editions outside the ESTC scope skipped.")

    ctx = {
        "estc_records": estc_records,
        "actor_index": build_actor_index(estc_records),
        "name_year_index": build_name_year_index(estc_records),
        "author_index": build_author_index(estc_records),
        "actor_names": load_actor_names(bnf_actors_path),
        "actor_mapping": load_estc_actor_mapping(estc_actor_mapping_path, dedup_mapping_path),
        "author_thr": author_thr, "title_thr": title_thr, "llm_thr": llm_thr,
        "year_window": year_window, "sleep": sleep,
        "max_author_candidates": max_author_candidates,
        "api_key_available": api_key_available,
    }
    print(f"  {len(ctx['actor_names']):,} BnF actor names, "
          f"{len(ctx['actor_mapping']):,} BnF actors linked to an ESTC actor.")

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during 03_map_estc_ecco.py execution",
            print_start_message=True,
        )

    total = len(bnf_editions)
    out_of_scope = 0
    with ResumableCsvWriter(output_path, OUTPUT_FIELDS, "BnF_edition_id",
                            restart=restart) as writer:
        if writer.done_keys:
            print(f"  Resuming: {len(writer.done_keys):,} editions already in {output_path}")
        for i, bnf in enumerate(bnf_editions):
            if (i + 1) % 50000 == 0:
                print(f"  … {i+1:,}/{total:,}")
            bnf_id = normalise(bnf.get("bnf_id") or bnf.get("edition", ""))
            if bnf_id in writer.done_keys:
                continue
            rec = match_edition(bnf, ctx)
            if rec["match_type"] == "out_of_scope":
                out_of_scope += 1
            else:
                writer.write(rec)
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i + 1, total, rec)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed ESTC/ECCO mapping run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )
    print(f"\n✓ Mapping CSV → {output_path}")

    # Counts from the whole file, so a resumed run reports every edition.
    counts = Counter(row["match_type"] for row in read_rows(output_path))
    stats = {
        "total": total,
        "written": sum(counts.values()),
        "out_of_scope_this_run": out_of_scope,
        "pass1_actor_bridge": counts["actor_bridge"],
        "pass2_heuristic": counts["heuristic"],
        "pass3_llm": counts["llm"],
        "pass3_llm_ambiguous": counts["ambiguous_translation"],
        "ambiguous_actor_bridge": counts["ambiguous_actor_bridge"],
        "ambiguous_heuristic": counts["ambiguous_heuristic"],
        "unmatched": counts["unmatched"],
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"✓ Report       → {report_path}")
    for key, value in stats.items():
        print(f"  {key:<24}: {value:,}")
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="BnF editions → ESTC/ECCO matching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--bnf-editions",    default=BNF_EDITIONS_DEFAULT)
    parser.add_argument("--bnf-actors",      default=BNF_ACTORS_DEFAULT,
                        help="BnF actors with names (module 04), to name the editions' authors.")
    parser.add_argument("--estc", "--estc-csv", dest="estc", default=ESTC_DEFAULT,
                        help="COMHIS ESTC directory (estc_core/actor_links/actors) or one CSV.")
    parser.add_argument("--estc-actor-mapping", default=ESTC_ACTOR_MAPPING_DEFAULT,
                        help="05_map_estc_actors.py confident output (Pass 1).")
    parser.add_argument("--dedup-mapping",   default=DEDUP_MAPPING_DEFAULT)
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
    parser.add_argument("--restart", action="store_true",
                        help="Start over instead of resuming from the existing output.")
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",   action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run_mapping(
        args.bnf_editions, args.estc,
        args.output, args.report,
        args.author_threshold, args.title_threshold, args.llm_threshold,
        args.year_window, args.sleep,
        max_author_candidates=args.max_author_candidates,
        use_monitor=not args.no_monitor,
        monitor_script=args.monitor_script,
        bnf_actors_path=args.bnf_actors,
        estc_actor_mapping_path=args.estc_actor_mapping,
        dedup_mapping_path=args.dedup_mapping,
        restart=args.restart,
    )

if __name__ == "__main__":
    main()
