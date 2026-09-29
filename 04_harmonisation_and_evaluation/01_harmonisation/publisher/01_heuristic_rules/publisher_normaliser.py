#!/usr/bin/env python3
"""
publisher_normaliser.py  —  Module 04, publisher heuristic rules.

Scope of this implementation
-----------------------------
Normalises the `publisher` field of the bnf_edition_data dataset (free-text
publisher statement, rdam:P30176 — distinct from `publisher_2`, which is
already a clean agent URI and needs no harmonisation).

Unlike actor_dates and language (see those normalisers' module docstrings),
this field's original placeholder speculation IS confirmed by the real raw
dataset (01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv,
1,344,914 rows, 128,811 distinct non-empty `publisher` values):

    - sine-nomine markers:      '[s.n.]' (93,251x), '[sans nom]' (2,730x)
    - self-published markers:   'Auteur' (7,016x), "l'auteur" (4,006x),
                                 "chez l'auteur" (2,438x) — distinct from
                                 sine-nomine: a known agent (the author) IS
                                 identified here, just not as a formal
                                 publishing house
    - abbreviation + case variants of the SAME publisher, verified from
      real top-frequency data: 'Impr. royale' (19,364x), 'Impr. nationale'
      (14,780x), 'Imp. royale' (5,305x), 'imp. royale' (4,827x) — note the
      second word is already consistently lowercase "royale"/"nationale"
      across all four forms, so token-level abbreviation expansion alone
      (Impr./Imp./imp. -> "Imprimerie") collapses all four into the
      identical string "Imprimerie royale" / "Imprimerie nationale"
    - bracketed, editorially-supplied names: '[G. L. Le Rouge]',
      '[J. Audran et F. Chereau]' — BnF's convention for an inferred/
      uncertain publisher name (same square-bracket uncertainty convention
      already handled for the `place` field by
      publication_place/02_tgn_lookup/bnf_place_harmonisation.py)
    - multiple publishers concatenated in one cell: 'Vve F. Muguet et H.
      Muguet', 'Vve Saugrain et. - P. Prault'

128,811 distinct values makes full pairwise fuzzy-distance clustering (e.g.
comparing every value against every other, O(n^2)) impractical in one pass,
and the project's existing fuzzy-matching convention is stdlib
difflib.SequenceMatcher (see 06_mapping/01_map_viaf.py), not a new
dependency like rapidfuzz. This implementation uses two clustering passes:

  1. NORMALISED-KEY clustering (cluster_by_canonical_key()): after per-value
     heuristic normalisation, values sharing the same accent/case/
     punctuation-insensitive key are merged onto the most frequent literal
     form among them — an O(n) operation that resolves the case/
     abbreviation-spacing variants observed above.
  2. FUZZY-SIMILARITY clustering (cluster_by_fuzzy_similarity()): among the
     distinct canonical keys pass 1 left standing, values are blocked by a
     4-character canonical-key prefix (bounding comparison to same-prefix
     groups instead of all ~100k+ keys against each other) and compared
     pairwise with difflib.SequenceMatcher within each block, merging above
     a similarity threshold via a small union-find (so A~B~C transitively
     merge even without a direct A~C match). This catches genuine
     near-misses a normalised key alone doesn't (a typo, an OCR-style
     substitution) that pass 1 cannot. correction_type='fuzzy_clustered'
     carries confidence='medium', deliberately lower than pass 1's 'high' —
     fuzzy matching carries real risk of merging two different but
     similar-looking names, and the lower confidence says so honestly.

Known, accepted limitation of the blocking strategy: a near-duplicate whose
canonical key differs in its first few characters (rather than later in the
string) will land in a different block and never be compared — an inherent
trade-off of blocking at this scale, not solved further here. A block larger
than MAX_FUZZY_BLOCK_SIZE is skipped entirely (logged in the report) rather
than run at O(block^2), guarding against a pathological common-prefix block.

Multi-publisher cells are FLAGGED (correction_type='multi_value'), never
silently split — guessing which of two concatenated names is "the"
publisher would invent information the source doesn't unambiguously give.
Known limitation, documented rather than hidden: the multi-value delimiter
check (" et " / " - " / ";") will also flag some single-firm names that
happen to use "et" idiomatically (e.g. a hypothetical "X et fils" father-
and-son firm name) — same kind of accepted trade-off
actor_name_evaluation.py already documents for its own "possibly contains
multiple values" warning (there excluding Spanish "y" compounds, but not
every idiomatic case). A false positive here only means the row is flagged
for review, not silently merged or split, so the risk is a review-queue
false positive, not a data-integrity one.

Processing order per distinct raw value (see _classify_and_normalise()):
    1. missing                 - empty / null marker
    2. sine_nomine              - '[s.n.]', 'sans nom', 'sine nomine'
                                  (bracket-unwrapped first)
    3. self_published            - 'Auteur', "l'auteur", "chez l'auteur"
                                  (bracket-unwrapped first)
    4. multi_value              - delimiter check (';' / ' et ' / ' - ')
                                  on the bracket-unwrapped value; original
                                  value passed through unchanged (flag only)
    5+6+7 compose sequentially on what's left (bracket-unwrap already
    applied; location-strip, then abbreviation-expansion), reported as
    whichever of these actually changed the string, in this priority:
        location_stripped        - trailing "(City)" segment removed
                                    (never a year/date-range parenthesis)
        abbreviation_expanded    - a known abbreviation token was expanded
                                    via publisher_abbreviations.json
        bracketed_uncertain      - only the outer [...] wrap was removed,
                                    nothing else changed
        passthrough              - nothing matched; value kept as-is

Pass 2 (cluster_by_canonical_key()) then merges normalised-key duplicates
among passthrough/abbreviation_expanded/bracketed_uncertain values onto
their dataset's most frequent literal form, correction_type overridden to
'canonical_clustered' only for the members that actually change.

Input
-----
Raw edition dataset (module 1's acquisition output) with columns including
`edition` and `publisher`, e.g.
01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv
Same row-multiplicity characteristics as language_normaliser.py /
bnf_place_harmonisation.py; dedupes to the first non-empty `publisher`
value seen per edition.

Output
------
04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/output/publisher_harmonised.csv:
    edition | publisher_original | publisher_harmonised | correction_type | confidence

04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/report/publisher_report.json:
    summary statistics (distinct raw values, category counts, clusters merged)

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: one checkpoint every 20,000 distinct publisher
values processed, plus a final checkpoint. Reports land in
00_monitor/report/publisher_normaliser_<timestamp>_py.txt. Disable with
--no-monitor.

By default, running this script also runs the 02_llm_based residual step
immediately afterwards (single command = fully harmonised, as far as
automatically possible, same convention as dates_normaliser.py) — resolving
the low-confidence residual (values with unrecognised abbreviations,
flagged multi-value cells, or non-alphanumeric noise) via an LLM. Pass
--no-llm to skip it and get the heuristic-only output.

Usage
-----
python publisher_normaliser.py \\
    --input  01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/output/publisher_harmonised.csv \\
    --report 04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/report/publisher_report.json

# disable the monitor report and the LLM residual step
python publisher_normaliser.py --no-monitor --no-llm
"""

import os, csv, sys, re, json, argparse, unicodedata, importlib.util, difflib
from collections import Counter
from pathlib import Path

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or accented publisher names
# used below, raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
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

INPUT_DEFAULT = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv"
_PUBLISHER_DIR = "04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules"
OUTPUT_DEFAULT = f"{_PUBLISHER_DIR}/output/publisher_harmonised.csv"
REPORT_DEFAULT = f"{_PUBLISHER_DIR}/report/publisher_report.json"
ABBREVIATIONS_PATH_DEFAULT = f"{_PUBLISHER_DIR}/publisher_abbreviations.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 20_000

# See cluster_by_fuzzy_similarity()'s docstring: blocking + similarity-ratio
# threshold + a per-block size cap, in the same neighbourhood as
# 06_mapping/01_map_viaf.py's existing 0.80-0.85 Levenshtein-ratio
# convention, tightened here since publisher names are short.
FUZZY_THRESHOLD_DEFAULT = 0.87
MAX_FUZZY_BLOCK_SIZE = 500

OUTPUT_FIELDS = ["edition", "publisher_original", "publisher_harmonised", "correction_type", "confidence"]

# ── Lookup / detection tables ────────────────────────────────────────────

_SINE_NOMINE_RE = re.compile(r"^(s\.?\s?n\.?|sine\s+nomine|sans\s+nom)$", re.IGNORECASE)
_SELF_PUBLISHED_RE = re.compile(r"^(chez\s+l['’]\s?auteur|l['’]\s?auteur|auteur)$", re.IGNORECASE)

# Real delimiter patterns seen concatenating two publisher names in the
# same cell: 'Vve F. Muguet et H. Muguet', 'Vve Saugrain et. - P. Prault'.
# Known false-positive risk: idiomatic single-firm names using "et" (e.g.
# a hypothetical "X et fils") also match — see module docstring.
_MULTI_VALUE_RE = re.compile(r";|\s-\s|\bet\.?\b", re.IGNORECASE)

_OUTER_BRACKETS_RE = re.compile(r"^\[(.+)\]$")
_TRAILING_LOCATION_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<loc>[^()]+)\)\s*$")
_YEAR_OR_RANGE_RE = re.compile(r"^\d{3,4}\.?(-\d{3,4}\.?)?$")


def load_abbreviations(path: str = ABBREVIATIONS_PATH_DEFAULT) -> dict:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parent / Path(path).name
    if not resolved.exists():
        resolved = Path(path)
    with open(resolved, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_abbreviation_regex(abbreviations: dict) -> re.Pattern:
    # (?<!\w) / (?!\w) instead of \b: a plain \b after a key ending in "."
    # would never match, because \b requires a word/non-word TRANSITION,
    # and "." followed by a space (the common case, e.g. "Impr. royale")
    # is non-word-to-non-word -- no transition, so \b fails right where a
    # period-ending abbreviation needs it to succeed. (?<!\w)/(?!\w) only
    # require the neighbouring character to NOT be a word character,
    # which correctly covers "followed by a period", "followed by a
    # space", and "followed by end-of-string" alike.
    # Longest-key-first so e.g. "impr." is tried before the shorter
    # "impr" for the same input.
    alternatives = "|".join(re.escape(k) for k in sorted(abbreviations, key=len, reverse=True))
    return re.compile(rf"(?<!\w)({alternatives})(?!\w)", re.IGNORECASE)


_ABBREVIATIONS = load_abbreviations()
_ABBREV_TOKEN_RE = _build_abbreviation_regex(_ABBREVIATIONS)


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def canonical_key(s: str) -> str:
    """Accent/case/punctuation-insensitive clustering key."""
    s = strip_accents(s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_outer_brackets(s: str) -> tuple[str, bool]:
    m = _OUTER_BRACKETS_RE.match(s)
    return (m.group(1).strip(), True) if m else (s, False)


def _strip_trailing_location(s: str) -> tuple[str, bool]:
    m = _TRAILING_LOCATION_RE.match(s)
    if not m:
        return s, False
    loc = m.group("loc").strip()
    if _YEAR_OR_RANGE_RE.match(loc):
        # e.g. "J. Smith [1750-1780]"-style embedded date span, not a place
        return s, False
    name = m.group("name").strip()
    if not name:
        return s, False
    return name, True


def _expand_abbreviations(s: str) -> tuple[str, bool]:
    changed = False

    def _sub(match: re.Match) -> str:
        nonlocal changed
        changed = True
        return _ABBREVIATIONS[match.group(1).lower()]

    result = _ABBREV_TOKEN_RE.sub(_sub, s)
    result = re.sub(r"\s+", " ", result).strip()
    return result, changed


def classify_and_normalise(raw_value: str) -> dict:
    """
    Normalise a single publisher value (already normalise()'d).

    Returns: { 'harmonised': str, 'correction_type': str, 'confidence': str }
    See module docstring for the full category list and precedence order.
    """
    if not raw_value:
        return {"harmonised": "", "correction_type": "missing", "confidence": "low"}

    unwrapped, had_brackets = _strip_outer_brackets(raw_value)

    if _SINE_NOMINE_RE.match(unwrapped):
        return {"harmonised": "", "correction_type": "sine_nomine", "confidence": "high"}

    if _SELF_PUBLISHED_RE.match(unwrapped):
        return {"harmonised": "L'auteur", "correction_type": "self_published", "confidence": "high"}

    if _MULTI_VALUE_RE.search(unwrapped):
        # Flagged, not split or altered — see module docstring.
        return {"harmonised": raw_value, "correction_type": "multi_value", "confidence": "low"}

    working = unwrapped
    location_stripped = False
    working, location_stripped = _strip_trailing_location(working)
    working, abbrev_changed = _expand_abbreviations(working)

    if location_stripped:
        correction_type = "location_stripped"
    elif abbrev_changed:
        correction_type = "abbreviation_expanded"
    elif had_brackets:
        correction_type = "bracketed_uncertain"
    else:
        correction_type = "passthrough"

    confidence = "high" if correction_type != "bracketed_uncertain" else "medium"
    return {"harmonised": working, "correction_type": correction_type, "confidence": confidence}


# Categories eligible for normalised-key clustering: real name variants
# where merging onto one canonical literal form is meaningful. sine_nomine/
# self_published/multi_value/missing are excluded on purpose — clustering
# "no publisher" markers or flagged ambiguous cells would misrepresent them.
_CLUSTERABLE_TYPES = {"passthrough", "abbreviation_expanded", "bracketed_uncertain", "location_stripped"}


def cluster_by_canonical_key(results: dict[str, dict], raw_value_counts: Counter) -> tuple[dict[str, dict], int]:
    """
    Merge distinct raw values whose normalised harmonised() forms share a
    canonical_key() onto the most frequent literal form in the group
    (frequency = how often the RAW value occurs in the dataset; ties broken
    alphabetically for determinism). Only touches _CLUSTERABLE_TYPES.
    Returns (updated results, number of values actually changed).
    """
    groups: dict[str, list[str]] = {}
    for raw_value, result in results.items():
        if result["correction_type"] not in _CLUSTERABLE_TYPES:
            continue
        key = canonical_key(result["harmonised"])
        if not key:
            continue
        groups.setdefault(key, []).append(raw_value)

    changed = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # Pick the canonical literal form by raw-value frequency, i.e. the
        # most common way this publisher actually appears in the source.
        canonical_literal = max(
            sorted({results[m]["harmonised"] for m in members}),
            key=lambda literal: sum(
                raw_value_counts[m] for m in members if results[m]["harmonised"] == literal
            ),
        )
        for m in members:
            if results[m]["harmonised"] != canonical_literal:
                results[m] = {
                    "harmonised": canonical_literal,
                    "correction_type": "canonical_clustered",
                    "confidence": "high",
                }
                changed += 1

    return results, changed


# Eligible for fuzzy clustering: the original clusterable types, plus
# 'canonical_clustered' itself -- a value pass 1 already merged once can
# still be swept into a larger fuzzy cluster in pass 2.
_FUZZY_ELIGIBLE_TYPES = _CLUSTERABLE_TYPES | {"canonical_clustered"}


def _uf_find(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]  # path halving
        x = parent[x]
    return x


def _uf_union(parent: dict, a: str, b: str) -> None:
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra != rb:
        parent[ra] = rb


def cluster_by_fuzzy_similarity(
    results: dict[str, dict], raw_value_counts: Counter,
    threshold: float = FUZZY_THRESHOLD_DEFAULT,
    max_block_size: int = MAX_FUZZY_BLOCK_SIZE,
) -> tuple[dict[str, dict], int, int]:
    """
    Second clustering pass, run after cluster_by_canonical_key(): merges
    distinct HARMONISED LITERALS that pass 1 left standing (i.e. don't share
    an exact canonical_key) but are near-duplicates of each other -- a typo,
    an OCR-style substitution -- using difflib.SequenceMatcher similarity.

    Blocked by the harmonised literal's canonical_key() first 4 characters
    to avoid all-pairs comparison across every distinct literal; a block
    bigger than `max_block_size` is skipped entirely (see module docstring).

    Only touches _FUZZY_ELIGIBLE_TYPES. Union-find merges transitively (A~B
    and B~C match, even without a direct A~C match, still end up in one
    cluster). Changed members get correction_type='fuzzy_clustered',
    confidence='medium' (deliberately lower than pass 1's 'high').

    Returns (updated results, number of raw values changed, number of
    oversized blocks skipped).
    """
    # One representative literal per canonical key, with its aggregated
    # raw-value frequency across every raw value currently mapping to it.
    literal_of_key: dict[str, str] = {}
    freq_of_key: Counter = Counter()
    members_of_literal: dict[str, list[str]] = {}
    for raw_value, result in results.items():
        if result["correction_type"] not in _FUZZY_ELIGIBLE_TYPES:
            continue
        literal = result["harmonised"]
        key = canonical_key(literal)
        if not key:
            continue
        literal_of_key.setdefault(key, literal)
        freq_of_key[key] += raw_value_counts[raw_value]
        members_of_literal.setdefault(literal, []).append(raw_value)

    keys = sorted(literal_of_key)
    blocks: dict[str, list[str]] = {}
    for key in keys:
        blocks.setdefault(key[:4], []).append(key)

    parent = {key: key for key in keys}
    blocks_skipped = 0
    for block_keys in blocks.values():
        if len(block_keys) > max_block_size:
            blocks_skipped += 1
            continue
        for i in range(len(block_keys)):
            for j in range(i + 1, len(block_keys)):
                a, b = block_keys[i], block_keys[j]
                if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
                    _uf_union(parent, a, b)

    clusters: dict[str, list[str]] = {}
    for key in keys:
        clusters.setdefault(_uf_find(parent, key), []).append(key)

    changed = 0
    for cluster_keys in clusters.values():
        if len(cluster_keys) < 2:
            continue
        canonical_key_ = max(cluster_keys, key=lambda k: (freq_of_key[k], k))
        canonical_literal = literal_of_key[canonical_key_]
        for key in cluster_keys:
            if key == canonical_key_:
                continue
            for raw_value in members_of_literal[literal_of_key[key]]:
                if results[raw_value]["harmonised"] != canonical_literal:
                    results[raw_value] = {
                        "harmonised": canonical_literal,
                        "correction_type": "fuzzy_clustered",
                        "confidence": "medium",
                    }
                    changed += 1

    return results, changed, blocks_skipped


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring bnf_place_harmonisation.py."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_publisher_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_llm_module():
    """Load the sibling 02_llm_based/llm_publisher_normaliser.py module, mirroring
    dates_normaliser.py's load_llm_module()."""
    script_path = Path(__file__).resolve().parent.parent / "02_llm_based" / "llm_publisher_normaliser.py"
    spec = importlib.util.spec_from_file_location("llm_publisher_normaliser", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(input_path: str, output_path: str, report_path: str,
       abbreviations_path: str = ABBREVIATIONS_PATH_DEFAULT,
       fuzzy_clustering: bool = True,
       fuzzy_threshold: float = FUZZY_THRESHOLD_DEFAULT,
       use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:

    global _ABBREVIATIONS, _ABBREV_TOKEN_RE
    if abbreviations_path != ABBREVIATIONS_PATH_DEFAULT:
        _ABBREVIATIONS = load_abbreviations(abbreviations_path)
        _ABBREV_TOKEN_RE = _build_abbreviation_regex(_ABBREVIATIONS)

    # Pass 1: first (edition -> publisher) seen per edition, and frequency
    # of every distinct raw value across the whole dataset (mirrors
    # bnf_place_harmonisation.py's distinct_places / edition_to_place split).
    edition_to_publisher: dict[str, str] = {}
    raw_value_counts: Counter = Counter()
    with open(input_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            edition = normalise(row.get("edition", ""))
            publisher = normalise(row.get("publisher", ""))
            if not edition:
                continue
            if edition not in edition_to_publisher:
                edition_to_publisher[edition] = publisher
            if publisher:
                raw_value_counts[publisher] += 1

    total_editions = len(edition_to_publisher)
    distinct_values = sorted(raw_value_counts)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during publisher_normaliser.py execution",
            print_start_message=True,
        )

    # Pass 2: classify each distinct raw value once.
    results: dict[str, dict] = {}
    for i, raw_value in enumerate(distinct_values):
        results[raw_value] = classify_and_normalise(raw_value)
        if use_monitor and (i + 1) % MONITOR_CHECKPOINT_EVERY == 0:
            monitor_state = monitor_module.update_monitor_state(
                state=monitor_state,
                context=f"Classified {i + 1:,}/{len(distinct_values):,} distinct publisher values",
                print_console=True,
            )

    # Pass 2.5: normalised-key clustering.
    results, clustered_count = cluster_by_canonical_key(results, raw_value_counts)

    # Pass 2.6: fuzzy-similarity clustering (catches near-misses pass 2.5's
    # exact-key match doesn't) -- see module docstring and
    # cluster_by_fuzzy_similarity()'s own docstring.
    fuzzy_clustered_count = 0
    fuzzy_blocks_skipped = 0
    if fuzzy_clustering:
        results, fuzzy_clustered_count, fuzzy_blocks_skipped = cluster_by_fuzzy_similarity(
            results, raw_value_counts, threshold=fuzzy_threshold)

    # Pass 3: emit one row per edition.
    stats = Counter()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for edition, raw_value in sorted(edition_to_publisher.items()):
            if not raw_value:
                result = {"harmonised": "", "correction_type": "missing", "confidence": "low"}
            else:
                result = results[raw_value]
            stats[result["correction_type"]] += 1
            writer.writerow({
                "edition": edition,
                "publisher_original": raw_value,
                "publisher_harmonised": result["harmonised"],
                "correction_type": result["correction_type"],
                "confidence": result["confidence"],
            })

    report = {
        "total_editions": total_editions,
        "distinct_raw_values": len(distinct_values),
        "clustered_values": clustered_count,
        "fuzzy_clustered_count": fuzzy_clustered_count,
        "fuzzy_blocks_skipped_oversized": fuzzy_blocks_skipped,
        "category_counts": dict(stats),
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed publisher harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {total_editions:,} editions ({len(distinct_values):,} distinct values, "
          f"{clustered_count:,} exact-key clustered, {fuzzy_clustered_count:,} fuzzy clustered"
          f"{f', {fuzzy_blocks_skipped:,} oversized blocks skipped' if fuzzy_blocks_skipped else ''}"
          f") -> {output_path}")
    for correction_type, count in stats.items():
        print(f"  {correction_type:<22}: {count:,}")
    print(f"✓ Report -> {report_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="publisher heuristic normaliser "
                    "(sine-nomine/self-published detection, abbreviation expansion, "
                    "location stripping, normalised-key clustering; see module docstring). "
                    "By default also runs the 02_llm_based residual step afterwards (see --no-llm).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",          default=INPUT_DEFAULT)
    parser.add_argument("--output",         default=OUTPUT_DEFAULT)
    parser.add_argument("--report",         default=REPORT_DEFAULT)
    parser.add_argument("--abbreviations",  default=ABBREVIATIONS_PATH_DEFAULT)
    parser.add_argument("--fuzzy-threshold", type=float, default=FUZZY_THRESHOLD_DEFAULT,
                        help="Minimum difflib.SequenceMatcher ratio for pass-2.6 fuzzy "
                            "clustering to merge two canonical keys (default: "
                            f"{FUZZY_THRESHOLD_DEFAULT}).")
    parser.add_argument("--no-fuzzy-clustering", action="store_true",
                        help="Skip pass 2.6 (fuzzy-similarity clustering); keep only the "
                            "exact-canonical-key clustering from pass 2.5.")
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",     action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    parser.add_argument("--no-llm",         action="store_true",
                        help="Skip the 02_llm_based/llm_publisher_normaliser.py residual step "
                            "that otherwise runs by default right after this heuristic step.")
    parser.add_argument("--llm-model",  default="claude-opus-5")
    parser.add_argument("--llm-effort", default="low",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--llm-cache",  default=None,
                        help="Override the LLM response cache path "
                            "(default: llm_publisher_normaliser.py's own CACHE_PATH_DEFAULT).")
    args = parser.parse_args()

    output_path = run(args.input, args.output, args.report, args.abbreviations,
        fuzzy_clustering=not args.no_fuzzy_clustering, fuzzy_threshold=args.fuzzy_threshold,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)

    if not args.no_llm:
        llm_module = load_llm_module()
        llm_module.run(
            heuristic_output_csv=output_path,
            output_path=output_path,
            cache_path=args.llm_cache or llm_module.CACHE_PATH_DEFAULT,
            model=args.llm_model,
            effort=args.llm_effort,
            use_monitor=not args.no_monitor,
            monitor_script=args.monitor_script,
        )


if __name__ == "__main__":
    main()
