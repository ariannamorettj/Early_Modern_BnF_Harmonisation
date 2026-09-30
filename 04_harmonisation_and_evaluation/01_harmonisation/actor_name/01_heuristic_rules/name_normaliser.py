#!/usr/bin/env python3
"""
name_normaliser.py  —  Module 04, actor_name heuristic rules.

Scope of this implementation
-----------------------------
When actor_name is empty/missing (including the "***" / "NAN" null markers,
not just blank) but actor_first_name and/or actor_last_name are present,
actor_name is derived from them (correction_type = "derived_from_first_last")
— fixing cases such as "Lucretius", whose BnF record carries the name only
in actor_last_name. When all three fields are empty, the row is left empty
(correction_type = "unresolved_missing").

When actor_name IS present, a cascade of deterministic cleanup rules is
applied, matching the anomaly categories detected by this module's own QA
evaluator (04_harmonisation_and_evaluation/02_evaluation/actor_name_evaluation.py
— PersonNameEvaluation — reimplemented here as corrections rather than mere
detection, so the two intentionally share vocabulary/logic; see each helper
function below for the exact rule):

    1. stripped_rdf_literal_tag — the RDF quoted-literal-with-language-tag
       syntax leaking through into actor_name for some records (e.g.
       '"William Blake trust"@fr' -> "William Blake trust") is unwrapped.
       Found empirically to account for 2,507 of 2,519 cases (99.5%) that
       would otherwise hit rule 2 below and come out only half-cleaned
       (closing quote and "@fr" both left in place) — see
       strip_rdf_literal_tag()'s docstring.
    2. stripped_brackets_or_separators — wrapping [], (), {}, «», <>, quotes
       removed (e.g. "[Voltaire]" -> "Voltaire"), but ONLY when doing so
       fully resolves the anomaly (no bracket/quote character left behind);
       otherwise the bracket/quote doesn't wrap the whole string (e.g. a
       book title quoted mid-sentence) and stripping would leave a stray,
       unbalanced character — flagged instead as
       "unresolved_brackets_or_separators" (low confidence, unchanged).
    3. alias_split — text from a recognised alias marker onward is dropped,
       keeping the primary name (e.g. "Jean Petit, dit le Grand" ->
       "Jean Petit"). Which name is "primary" vs. "alias" is a convention,
       not a certainty — confidence is medium, not high.
    4. stripped_title_role — an embedded title/role token is removed,
       keeping the remaining name (e.g. "Sieur de Malherbe" -> "Malherbe").
       Also medium confidence: stripping the wrong token would corrupt the
       name.
    5. unresolved_multiple_values — an internal conjunction suggests the
       cell holds more than one name (e.g. "Jean et Pierre Dupont").
       Deliberately NOT auto-split: picking one name over the other would
       be a guess, not a correction (same "never silently guess" stance as
       this module's actors_deduplication.py and 06_mapping's
       ambiguous_translation handling) — flagged, left unchanged, low
       confidence.
    6. preferred_first_last_over_initials — when actor_name looks like bare
       initials or a dotted abbreviation ("M D", "Th.") AND
       actor_first_name/actor_last_name together give something more
       informative, the latter is preferred. Without a better alternative,
       the value is left as-is (correction_type =
       "initials_or_abbreviation_unresolved", low confidence) — there is
       nothing to derive the full name from.
    7. none — no anomaly detected; value passed through unchanged, high
       confidence.

The first rule to fire wins (checked in the order above); a value can only
have one correction_type per run.

NOT implemented (left for future work, deliberately — see this module's
README): a curated name_correction_dict.json for known-erroneous strings
with no rule-based fix (that requires manual annotation of real cases, not
fabricated here), and Roman-numeral suffix handling (e.g. "Julien I" —
detected by the evaluator as a warning, but genuinely ambiguous whether "I"
is part of the name or noise, so left untouched rather than guessed at).

By default, running this script also runs the 02_llm_based residual step
immediately afterwards (single command = fully harmonised, as far as
automatically possible, same convention as dates_normaliser.py and
publisher_normaliser.py) — resolving the unresolved_brackets_or_separators /
unresolved_multiple_values / initials_or_abbreviation_unresolved residual
via an LLM (see 02_llm_based/llm_name_normaliser.py's module docstring for
exactly which correction_type values are and are not sent to it). Pass
--no-llm to skip it and get the heuristic-only output.

Input
-----
Raw actor dataset (CSV, or ZIP containing one or more CSVs) with columns:
    actor, actor_name, actor_first_name, actor_last_name
e.g. 01_data_retrieval/02_actors/actors_data/actor_data.csv (module 1's raw
acquisition output).

Each actor URI typically appears on multiple rows in that raw dataset (one
row per external-link binding returned by the SPARQL acquisition query), and
actor_name / actor_first_name / actor_last_name are repeated identically
across an actor's rows. This script therefore deduplicates by actor URI
before applying the rule — the output has exactly one row per unique actor.

Output (actor_name_harmonised.csv)
-----------------------------------
    actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by module 1's query_agents.R / query_editions.R and by
06_mapping/02_map_wikidata.py: one checkpoint every MONITOR_CHECKPOINT_EVERY
(1,000) actors and at the last one, plus a final checkpoint on completion.
(A checkpoint costs ~55 ms, mostly the nvidia-smi GPU read, so one per
actor added about two hours to a 124,695-actor run.) Reports land in
00_monitor/report/name_normaliser_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python name_normaliser.py \\
    --input  01_data_retrieval/02_actors/actors_data/actor_data.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output

# disable the monitor report
python name_normaliser.py --no-monitor
"""

import os, csv, re, sys, zipfile, argparse, importlib.util
from pathlib import Path

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) used below, raising
# UnicodeEncodeError. Reconfigure to UTF-8 up front.
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

INPUT_DEFAULT = "01_data_retrieval/02_actors/actors_data/actor_data.csv"
OUTPUT_DIR_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output"
)
OUTPUT_FILENAME_DEFAULT = "actor_name_harmonised.csv"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per record cost ~55 ms each (mostly the nvidia-smi GPU read),
# about two hours over 124,695 actors; checkpoint every N records plus the
# last one instead, like 06_mapping/05_map_estc_actors.py.
MONITOR_CHECKPOINT_EVERY = 1_000

OUTPUT_FIELDS = [
    "actor_uri", "actor_name_original", "actor_name_harmonised",
    "correction_type", "confidence",
]


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and 06_mapping's scripts."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_name_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, actor_uri, correction_type):
    if monitor_module is None:
        return monitor_state
    if index % MONITOR_CHECKPOINT_EVERY and index != total:
        return monitor_state
    context = (f"Processed actor {actor_uri} (index {index}/{total}) "
              f"- correction_type={correction_type}")
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


def load_llm_module():
    """Load the sibling 02_llm_based/llm_name_normaliser.py module, mirroring
    dates_normaliser.py's/publisher_normaliser.py's load_llm_module(). Only
    used from main() — run() above stays a pure, heuristic-only function
    with no dependency on this module, so importing this file never
    requires anthropic/pydantic to be installed unless the CLI's LLM step
    actually runs."""
    script_path = Path(__file__).resolve().parent.parent / "02_llm_based" / "llm_name_normaliser.py"
    spec = importlib.util.spec_from_file_location("llm_name_normaliser", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NULL_MARKERS = {"NA", "N/A", "NULL", "NONE", "NAN", "***", ""}


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in NULL_MARKERS else s


# ── Name-cleanup rule vocabulary ──────────────────────────────────────────────
# Shares its categories/vocabulary by design with PersonNameEvaluation
# (04_harmonisation_and_evaluation/02_evaluation/actor_name_evaluation.py),
# reimplemented here as corrections rather than detection-only. Duplicated
# rather than imported: that module is QA tooling with its own package
# structure (relative imports), and this codebase's convention is to keep
# each script's small helpers self-contained (see e.g. normalise() above,
# duplicated across every script in this pipeline) rather than share a
# cross-module dependency for a handful of constants.

PARTICLES = {"de", "da", "di", "del", "van", "von", "y", "e", "et", "und"}
CONJUNCTIONS = {"e", "and", "et", "y", "und"}

_BRACKET_PAIRS = {"[": "]", "(": ")", "{": "}", "«": "»", "<": ">",
                 '"': '"', "'": "'"}

_ALIAS_MARKER_RE = re.compile(
    r"\b(alias|dit\s+le|dit\s+la|dit\s+il|detto\s+il|detto\s+lo|detto\s+la|"
    r"detta\s+la|called|also\s+known\s+as|known\s+as|surnomm[ée]e?|"
    r"llamad[oa]|conocid[oa]\s+como|apodad[oa]|genannt|bekannt\s+als)\b",
    re.IGNORECASE,
)

_SINGLE_WORD_TITLES = {
    "veuve", "vve", "seigneur", "sieur", "prince", "chevalier", "comte",
    "comtesse", "duque", "duc", "cardinal", "officier", "officer", "colonel",
    "dame", "madame", "mme", "abbé", "abbe", "abate", "abbot", "herr",
    "frau", "rey", "reina", "king", "queen",
}
_MULTI_WORD_TITLES = [
    "vve de", "veuve de", "widow of", "vedova di", "viuda de", "witwe von",
    "sieur de", "le fils du", "fils de", "son of", "hijo de", "figlio di",
    "homme de lettres",
]
_TITLE_PHRASES = (sorted(_MULTI_WORD_TITLES, key=len, reverse=True)
                 + sorted(_SINGLE_WORD_TITLES, key=len, reverse=True))
_TITLE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _TITLE_PHRASES) + r")\b",
    re.IGNORECASE,
)


_RDF_LITERAL_RE = re.compile(r'^"(.*)"@[a-z]{2,3}$')


def strip_rdf_literal_tag(value: str):
    """Returns (inner_text, found). Handles the RDF quoted-literal-with-
    language-tag syntax (e.g. '"William Blake trust"@fr') that leaks
    through into actor_name for some records — found empirically to
    account for the overwhelming majority (2,507 of 2,519 in a full-dataset
    validation run) of what would otherwise fall into the generic
    stripped_brackets_or_separators rule below. That generic rule's
    trailing-non-alnum trim only strips symmetric wrapping (checked via
    contains_brackets_or_separators()/_BRACKET_PAIRS), so it left the
    closing quote AND the "@fr" tag both in place — checked here first,
    as a dedicated, well-defined pattern, instead."""
    m = _RDF_LITERAL_RE.match(value.strip())
    if m:
        inner = m.group(1).strip()
        if inner:
            return inner, True
    return value, False


def contains_brackets_or_separators(value: str) -> bool:
    """Gate for strip_wrapping_punctuation(): mirrors
    PersonNameEvaluation._contains_brackets_or_separators exactly. Without
    this gate, strip_wrapping_punctuation()'s trailing-non-alnum trim would
    also eat the period off a plain abbreviation like "Th." — the trim is
    only appropriate once we know a real bracket/quote/separator is present."""
    separators = "[](){}\"<>"
    return any(ch in value for ch in separators) or "//" in value


def strip_wrapping_punctuation(value: str) -> str:
    """Remove a matched wrapping bracket/quote pair, then any remaining
    non-alphanumeric characters at either end. Mirrors
    PersonNameEvaluation._strip_wrapping_punctuation exactly."""
    s = value.strip()
    if not s:
        return s
    first, last = s[0], s[-1]
    if first in _BRACKET_PAIRS and last == _BRACKET_PAIRS[first]:
        s = s[1:-1].strip()
    while s and not s[0].isalnum():
        s = s[1:].lstrip()
    while s and not s[-1].isalnum():
        s = s[:-1].rstrip()
    return s


def split_on_alias_marker(value: str):
    """Returns (primary_name, found). The text from the first recognised
    alias marker onward (e.g. ", dit le Grand") is dropped; only the
    portion before it is kept as the primary name."""
    m = _ALIAS_MARKER_RE.search(value)
    if not m:
        return value, False
    primary = value[:m.start()].strip(" ,;.")
    if primary:
        return primary, True
    return value, False


def strip_title_or_role(value: str):
    """Returns (remainder, found). Removes the first recognised title/role
    token or phrase (checked longest-first so e.g. "sieur de" matches
    whole rather than leaving a dangling "de"), joining what remains."""
    m = _TITLE_RE.search(value)
    if not m:
        return value, False
    remainder = (value[:m.start()] + " " + value[m.end():])
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,;")
    if remainder:
        return remainder, True
    return value, False


def _looks_like_bare_initial(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]\.?", token))


def looks_like_multiple_values(value: str) -> bool:
    """Conservative subset of PersonNameEvaluation._contains_multiple_values:
    an internal (not first, not last token) bare conjunction suggests two
    concatenated names, unless:
    - the tokens instead match a compound-surname pattern ("... de|del|di|
      da|of ... e|and|et|y|und ...", e.g. "Fernando Álvarez de Toledo y
      Pimentel"), legitimately one name; or
    - the conjunction is the SECOND-TO-LAST token with at least two tokens
      ahead of it (a given name and a first surname), e.g. "Juan Melo y
      Girón", "Friedrich ... von Zinzendorf und Pottendorf" — the standard
      Iberian/German double-surname convention. Found empirically (full-
      dataset validation run) to be by far the dominant shape of what would
      otherwise be flagged: unlike a real "Name1 CONJ Name2 Surname"
      concatenation (conjunction near the START), a compound surname has
      the conjunction near the END, immediately before the second surname; or
    - the conjunction candidate sits next to a bare single-letter token
      (e.g. "A E Crous", "F E Louys") — found empirically to be a middle
      initial, not the Italian conjunction "e", in every sampled case. A
      real conjunction joins two names, not an initial and a name."""
    tokens = [t.strip(".,;") for t in value.split()]
    if len(tokens) < 3:
        return False
    lower = [t.lower() for t in tokens]

    preps = {"de", "del", "di", "da", "of"}
    for i, tok in enumerate(lower[:-2]):
        if tok in preps:
            for j in range(i + 1, len(lower) - 1):
                if lower[j] in CONJUNCTIONS:
                    return False  # compound-surname pattern, not multiple values

    if len(lower) >= 4 and lower[-2] in CONJUNCTIONS:
        return False  # "Given [Given...] Surname1 CONJ Surname2" pattern

    for i in range(1, len(lower) - 1):
        if lower[i] not in CONJUNCTIONS:
            continue
        # A single UPPERCASE letter in the conjunction slot itself is a
        # middle initial, not the word "e"/"y" (e.g. "Eric E Edner",
        # "Sherman E. Lee") — case is the signal: a real conjunction reads
        # lowercase in running prose even mid-name-string, an initial is
        # capitalised. Checked case-sensitively (tokens[i], not lower[i]).
        if len(tokens[i]) == 1 and tokens[i].isupper():
            continue
        if _looks_like_bare_initial(tokens[i - 1]) or _looks_like_bare_initial(tokens[i + 1]):
            continue  # adjacent to a bare initial too (e.g. "A E Crous")
        return True

    return False


def looks_like_initials_or_abbreviation(value: str) -> bool:
    """Conservative subset of PersonNameEvaluation's
    is_dotted_initials_only / is_initials_only / is_possible_abbreviation:
    a single dotted abbreviation ("Th.", "M."), an all-dotted-initials
    string ("M. B. L."), or bare short tokens ("M D", "M D P", particles
    ignored)."""
    tokens = value.split()
    if not tokens:
        return False

    if len(tokens) == 1 and re.fullmatch(r"[A-Za-z]{1,3}\.", tokens[0]):
        return True

    if all(re.fullmatch(r"[A-Za-z]\.", t) for t in tokens):
        return True

    significant = [t for t in tokens if t.strip(".").lower() not in PARTICLES]
    if len(tokens) >= 2 and significant and all(len(t.strip(".")) <= 2 for t in significant):
        return True

    return False


def iter_actor_rows(path: str):
    """Yield row dicts from a plain CSV, or from every CSV inside a ZIP."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name, "r") as f:
                    lines = (line.decode("utf-8", errors="replace") for line in f)
                    yield from csv.DictReader(lines)
    else:
        with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
            yield from csv.DictReader(f)


def apply_name_cleanup_rules(actor_name: str, first_name: str, last_name: str):
    """
    Cascade of deterministic cleanup rules applied when actor_name is
    non-empty (see module docstring for the full rationale per rule). The
    first rule to fire wins. Returns (harmonised, correction_type, confidence).
    """
    rdf_inner, found_rdf = strip_rdf_literal_tag(actor_name)
    if found_rdf:
        return rdf_inner, "stripped_rdf_literal_tag", "high"

    if contains_brackets_or_separators(actor_name):
        cleaned = strip_wrapping_punctuation(actor_name)
        # Only accept the strip if it fully removed the offending
        # character(s) — found empirically (full-dataset validation run)
        # that a bracket/quote NOT wrapping the whole string (e.g. a book
        # title quoted mid-sentence, "Un Prêtre ... [de l'oratoire ...]"
        # missing its closing "]") leaves a stray, unbalanced character
        # behind, actively corrupting the value rather than cleaning it.
        if cleaned and cleaned != actor_name and not contains_brackets_or_separators(cleaned):
            return cleaned, "stripped_brackets_or_separators", "high"
        return actor_name, "unresolved_brackets_or_separators", "low"

    primary, found_alias = split_on_alias_marker(actor_name)
    if found_alias:
        return primary, "alias_split", "medium"

    remainder, found_title = strip_title_or_role(actor_name)
    if found_title:
        return remainder, "stripped_title_role", "medium"

    if looks_like_multiple_values(actor_name):
        return actor_name, "unresolved_multiple_values", "low"

    if looks_like_initials_or_abbreviation(actor_name):
        derived = " ".join(part for part in (first_name, last_name) if part)
        if derived and derived.lower() != actor_name.lower():
            return derived, "preferred_first_last_over_initials", "high"
        return actor_name, "initials_or_abbreviation_unresolved", "low"

    return actor_name, "none", "high"


def derive_actor_name(actor_name: str, first_name: str, last_name: str) -> dict:
    """
    Apply the full name-harmonisation cascade to one actor's already-
    deduplicated field values (all three already normalise()'d — empty
    string means absent): derive_from_first_last when actor_name is empty,
    otherwise apply_name_cleanup_rules() (see module docstring for the
    full list of correction_type values this can return).

    Returns a dict with keys: harmonised (str), correction_type (str),
    confidence ('high' / 'medium' / 'low').
    """
    if actor_name:
        harmonised, correction_type, confidence = apply_name_cleanup_rules(
            actor_name, first_name, last_name)
        return {"harmonised": harmonised, "correction_type": correction_type,
                "confidence": confidence}

    derived = " ".join(part for part in (first_name, last_name) if part)
    if derived:
        return {
            "harmonised": derived,
            "correction_type": "derived_from_first_last",
            "confidence": "high",
        }

    return {"harmonised": "", "correction_type": "unresolved_missing", "confidence": "low"}


def collect_unique_actors(input_path: str) -> dict[str, dict[str, str]]:
    """
    Deduplicate raw rows by actor URI, keeping the first non-empty value seen
    for actor_name / actor_first_name / actor_last_name per actor.
    """
    actors: dict[str, dict[str, str]] = {}
    for row in iter_actor_rows(input_path):
        actor_uri = normalise(row.get("actor", ""))
        if not actor_uri:
            continue
        entry = actors.setdefault(actor_uri, {
            "actor_name": "", "actor_first_name": "", "actor_last_name": "",
        })
        for field in ("actor_name", "actor_first_name", "actor_last_name"):
            if not entry[field]:
                val = normalise(row.get(field, ""))
                if val:
                    entry[field] = val
    return actors


def run(input_path: str, output_dir: str,
       output_filename: str = OUTPUT_FILENAME_DEFAULT,
       use_monitor: bool = False,
       monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:
    """
    Load the input CSV/ZIP, apply derive_actor_name() to each unique actor,
    and write the output mapping CSV. Returns the output file path.
    """
    actors = collect_unique_actors(input_path)
    total = len(actors)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    stats: dict = {}

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during name_normaliser.py execution",
            print_start_message=True,
        )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, (actor_uri, fields) in enumerate(sorted(actors.items())):
            result = derive_actor_name(
                fields["actor_name"], fields["actor_first_name"], fields["actor_last_name"])
            stats[result["correction_type"]] = stats.get(result["correction_type"], 0) + 1
            writer.writerow({
                "actor_uri": actor_uri,
                "actor_name_original": fields["actor_name"],
                "actor_name_harmonised": result["harmonised"],
                "correction_type": result["correction_type"],
                "confidence": result["confidence"],
            })
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i + 1, total,
                actor_uri, result["correction_type"])

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actor_name harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {len(actors):,} actors -> {output_path}")
    for correction_type, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {correction_type:<35} {n:,}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_name heuristic normaliser "
                    "(see module docstring for the full rule cascade). "
                    "By default also runs the 02_llm_based residual step "
                    "afterwards (see --no-llm).")
    parser.add_argument("--input", default=INPUT_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Output directory")
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip the 02_llm_based/llm_name_normaliser.py residual step "
                            "that otherwise runs by default right after this heuristic "
                            "step, resolving the unresolved_brackets_or_separators / "
                            "unresolved_multiple_values / initials_or_abbreviation_unresolved "
                            "residual via an LLM call.")
    parser.add_argument("--llm-model", default="claude-opus-5")
    parser.add_argument("--llm-effort", default="low",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--llm-cache", default=None,
                        help="Override the LLM response cache path "
                            "(default: llm_name_normaliser.py's own CACHE_PATH_DEFAULT).")
    args = parser.parse_args()

    output_path = run(args.input, args.output, args.output_filename,
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
