#!/usr/bin/env python3
"""
dates_normaliser.py  —  Module 04, actor_dates heuristic rules.

Scope of this implementation
-----------------------------
Converts actor_birth, actor_death, actor_start, actor_end to EDTF
(Extended Date/Time Format).

IMPORTANT — this supersedes the free-text anomaly categories speculated in
this module's README ("ca. 1750", "vers 1720", "XVIIIe siècle", etc.): a
full scan of the real raw dataset (01_data_retrieval/02_actors/actors_data/
actor_data.csv, ~1.73M non-empty date values) found NONE of that free text.
The BnF source already encodes dates with a structured numeric convention:

    exact_year        "1750", "43", "882"        -> optional sign, 1-4 digits
    exact_date         "1594-06-14"                -> full ISO-like date
    year_month          "1564-04"                   -> year + month, no day
    masked_precision    "17..", "17XX", "1..."      -> trailing '.'/'X' mask
                                                          unspecified digits
                                                          (century/decade/
                                                          millennium-level
                                                          precision)
    missing             "NA", "", None
    non_parseable       everything else (~0.02% of values: masked digits
                         inside a full date e.g. "150.-02-20", stray "?"
                         mask char, missing zero-padding on day, etc.)

These six categories (not the README's) are what detect_date_format()
actually returns. 01_harmonisation/README section 3.2 / the top-level
04_harmonisation_and_evaluation/README.md have been updated accordingly.

BCE (negative year) design decision
------------------------------------
The source marks BCE years with a leading '-' (with or without a following
space: both "-43" and "- 43" occur). EDTF/ISO 8601-2 negative years use
*astronomical* year numbering (year 0000 = 1 BCE, so 43 BCE would be
"-0042" — an off-by-one from ordinary historical BCE counting, because ISO
years include a year zero that historians don't use).

This implementation does NOT apply that offset — it zero-pads the digits
already present and keeps the sign as-is (43 BCE -> "-0043"). This was
verified empirically, not assumed: one actor in the dataset has
actor_birth="- 384", actor_death="- 322" — Aristotle's well-known dates
(384-322 BCE) match those digits exactly with no shift, which would not be
the case under strict ISO astronomical numbering (that would require
"-0383"/"-0321"). The source is already using the ordinary historical BCE
convention, common in GLAM/library linked data, so re-deriving an
astronomical offset here would introduce a silent one-year error instead of
fixing one. date_original is preserved unchanged alongside date_harmonised
so this decision can be revisited later if the true BnF convention is ever
documented otherwise.

Only ONE rule is implemented: format detection + EDTF conversion of the six
categories above. No LLM step has been wired in yet.

Deterministic-first, LLM-as-last-resort: this heuristic rule alone already
resolves 99.98% of all non-empty date values (1,731,680 of 1,731,972,
verified by running detect_date_format() over the full raw dataset — see
the category table above) — the project's general principle (04_harmonisation_and_evaluation/
README.md section 1) is to exhaust cheap, deterministic, reproducible
resolution before ever reaching for an LLM, precisely because a regex rule
is free/instant/reproducible-on-rerun and an LLM call is none of those.
Only the non_parseable residual (~0.013%, a few hundred rows total) is a
genuine candidate for 02_llm_based/llm_dates_normaliser.py — mirrors
actor_name/name_normaliser.py's incremental approach: non_parseable values
are flagged with low confidence and left for future work rather than
attempted here. Once implemented, the LLM step is intended to run by
default as the next stage after this one (single-command harmonisation),
with a --no-llm flag to skip it — see the README section above for why
default-on is still consistent with "prefer the lighter resolution": the
LLM only ever sees the small residual this script couldn't resolve, never
re-processes rows already resolved here with high confidence.

Input
-----
Raw actor dataset (CSV, or ZIP containing one or more CSVs) with columns:
    actor, actor_birth, actor_death, actor_start, actor_end
e.g. 01_data_retrieval/02_actors/actors_data/actor_data.csv (module 1's raw
acquisition output).

Each actor URI typically appears on multiple rows in that raw dataset (one
row per external-link binding returned by the SPARQL acquisition query), and
the four date fields are repeated identically across an actor's rows. This
script therefore deduplicates by actor URI before applying the rule, keeping
the first non-empty value seen per field.

Output (actor_dates_harmonised.csv)
------------------------------------
One row per (actor_uri, field) — i.e. up to 4 rows per actor, one for each
of actor_birth/actor_death/actor_start/actor_end, including fields whose
original value is missing (needed downstream: the evaluator's
"missing_value" check assumes it can see those rows):

    actor_uri | field | date_original | date_harmonised | date_format_detected | confidence

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by 01_harmonisation/actor_name/01_heuristic_rules/
name_normaliser.py: one checkpoint per processed actor, plus a final
checkpoint on completion. Reports land in
00_monitor/report/dates_normaliser_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python dates_normaliser.py \\
    --input  01_data_retrieval/02_actors/actors_data/actor_data.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/output

# disable the monitor report
python dates_normaliser.py --no-monitor
"""

import os, csv, sys, re, zipfile, argparse, importlib.util
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
    "04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/output"
)
OUTPUT_FILENAME_DEFAULT = "actor_dates_harmonised.csv"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"

DATE_FIELDS = ["actor_birth", "actor_death", "actor_start", "actor_end"]

OUTPUT_FIELDS = [
    "actor_uri", "field", "date_original", "date_harmonised",
    "date_format_detected", "confidence",
]

# ── Format detection / EDTF conversion ─────────────────────────────────────
#
# Six categories, derived empirically from a full scan of the raw dataset
# (see module docstring) rather than from the free-text anomalies this
# module's README originally speculated about (those do not occur at all).
# Each category below states: what it looks like in the raw data, why it is
# its own category, and the confidence assigned to its EDTF conversion.

# Optional BCE sign: "-43" (no space) and "- 43" (with space) BOTH occur in
# the raw dataset for the same underlying meaning (43 BCE) — the group is
# used only to detect presence of the sign; the space, if any, is discarded.
_SIGN_RE = r"-\s?"

# exact_date: "YYYY-MM-DD", e.g. "1594-06-14" (~22.8% of all non-empty
# values). Day-level precision, already ISO-like. High confidence: only the
# year part needs zero-padding, month/day pass through unchanged.
_EXACT_DATE_RE = re.compile(rf"^({_SIGN_RE})?(\d{{1,4}})-(\d{{2}})-(\d{{2}})$")

# year_month: "YYYY-MM", e.g. "1564-04" (~0.9%). Month-level precision, no
# day recorded. EDTF natively supports this precision level ("1564-04" is
# already valid EDTF) — high confidence.
_YEAR_MONTH_RE = re.compile(rf"^({_SIGN_RE})?(\d{{1,4}})-(\d{{2}})$")

# exact_year: 1-4 digits, no leading zeros in the source (e.g. "1750",
# "882", "43"). The single largest category (~50.6%). High confidence:
# converting to EDTF is pure zero-padding to 4 digits, no digits are
# invented ("43" -> "0043").
_EXACT_YEAR_RE = re.compile(rf"^({_SIGN_RE})?(\d{{1,4}})$")

# masked_precision: 1-3 known leading digits followed by 1-3 mask
# characters standing for unknown trailing digits, e.g. "17.." (century
# known, decade+year unknown) or "1..." (millennium known only). The BnF
# source uses '.' for this (91.5k occurrences) and, rarely, 'X' (35
# occurrences) for the exact same meaning — both are accepted here and
# normalised to the same EDTF output. This is NOT the same thing as EDTF's
# '~' (approximate) or '?' (uncertain) qualifiers, which express epistemic
# doubt about a value that IS known: masked_precision instead means the
# source itself never recorded those digits at all — a structural gap, not
# an approximation. EDTF Level 2 defines 'X' as the standard character for
# exactly this ("unspecified digit"), so the digit-for-digit '.'/'X' -> 'X'
# substitution below is a faithful, mechanical transcription (~4.1%, high
# confidence) — NOT an inference about what the missing digits might be.
#
# The known+mask digit count is required to sum to exactly 4 (validated
# below, in detect_date_format) because every masked_precision value
# observed in the real dataset spans exactly one 4-digit year — there is
# never ambiguity about how many digits are missing.
_MASKED_RE = re.compile(rf"^({_SIGN_RE})?(\d{{1,3}})([.X]{{1,3}})$")


def detect_date_format(raw_value: str) -> str:
    """
    Classify a raw (already normalise()'d) date string into one of:

        missing           - empty string / null marker (nothing to harmonise;
                             not a parsing failure, the source has no value)
        exact_date         - "YYYY-MM-DD" (day precision)
        year_month          - "YYYY-MM" (month precision, no day)
        exact_year          - "YYYY" (year precision, 1-4 digits, no padding)
        masked_precision    - "17..", "1...", "17XX" (century/decade/
                              millennium precision only, trailing digits
                              structurally unrecorded by the source)
        non_parseable        - anything else: real but rare (~0.013% of the
                              dataset) hybrid/malformed forms such as a mask
                              character inside a full date ("175.-07-27"), a
                              masked day instead of year ("1799-03-2."), or
                              an unexpected mask character ("14??"). Left
                              unresolved on purpose rather than special-cased
                              with ever more contorted regexes for a
                              fraction-of-a-percent of the data — same
                              incremental philosophy as name_normaliser.py's
                              derive_from_first_last rule. Candidates for the
                              (still unimplemented) LLM step or manual review.

    All BCE sign variants ("-43", "- 43") are handled identically within
    each category above — the sign only changes whether the EDTF output
    is prefixed with '-' (see normalise_date()), not which category applies.
    """
    if not raw_value:
        return "missing"
    if _EXACT_DATE_RE.match(raw_value):
        return "exact_date"
    if _YEAR_MONTH_RE.match(raw_value):
        return "year_month"
    if _EXACT_YEAR_RE.match(raw_value):
        return "exact_year"
    m = _MASKED_RE.match(raw_value)
    if m and len(m.group(2)) + len(m.group(3)) == 4:
        return "masked_precision"
    return "non_parseable"


def _sign_prefix(sign_group) -> str:
    """
    '-' if the value carried a BCE sign, '' otherwise.

    Deliberately does NOT apply the ISO 8601-2/EDTF "astronomical year"
    offset (where year 0000 = 1 BCE, so 43 BCE would need to be written
    "-0042", not "-0043"). The raw sign and digits are passed straight
    through into the zero-padded EDTF year. See the module docstring for
    the empirical justification (the Aristotle "-384"/"-322" case) and
    04_harmonisation_and_evaluation/README.md section 3.2 for the same
    reasoning in the module-level documentation.
    """
    return "-" if sign_group else ""


def normalise_date(raw_value: str) -> dict:
    """
    Convert a raw (already normalise()'d) date string to EDTF, dispatching
    on detect_date_format(). See that function's docstring for what each
    category means; this function only covers the *conversion* logic.

    Returns: { 'harmonised': str, 'format_detected': str, 'confidence': str }
    """
    fmt = detect_date_format(raw_value)

    if fmt in ("missing", "non_parseable"):
        # Nothing to convert: 'missing' has no source value at all, and
        # 'non_parseable' is a value this heuristic rule deliberately does
        # not attempt (see detect_date_format() docstring). Both are left
        # as an empty harmonised value with low confidence rather than
        # guessed at, so downstream consumers (03_ready_dataset_assembly,
        # the evaluator's future 'missing_value' check) can tell "no data"
        # and "data we couldn't confidently parse" apart from a real date.
        return {"harmonised": "", "format_detected": fmt, "confidence": "low"}

    if fmt == "exact_date":
        # "1594-06-14" -> "1594-06-14" (year zero-padded if <4 digits,
        # month/day already 2 digits by construction of _EXACT_DATE_RE).
        sign, year, month, day = _EXACT_DATE_RE.match(raw_value).groups()
        harmonised = f"{_sign_prefix(sign)}{year.zfill(4)}-{month}-{day}"
        return {"harmonised": harmonised, "format_detected": fmt, "confidence": "high"}

    if fmt == "year_month":
        # "1564-04" -> "1564-04" (year zero-padded, month passes through).
        sign, year, month = _YEAR_MONTH_RE.match(raw_value).groups()
        harmonised = f"{_sign_prefix(sign)}{year.zfill(4)}-{month}"
        return {"harmonised": harmonised, "format_detected": fmt, "confidence": "high"}

    if fmt == "exact_year":
        # "43" -> "0043", "1750" -> "1750": zero-pad to EDTF's canonical
        # 4-digit year width. No digits are invented, only padded.
        sign, year = _EXACT_YEAR_RE.match(raw_value).groups()
        harmonised = f"{_sign_prefix(sign)}{year.zfill(4)}"
        return {"harmonised": harmonised, "format_detected": fmt, "confidence": "high"}

    # masked_precision: "17.." -> "17XX", "1..." -> "1XXX". Digit-for-digit
    # substitution of the source's mask character ('.' or 'X') with EDTF's
    # standard "unspecified digit" character 'X' (EDTF Level 2). The known
    # digits are copied through unchanged; only the mask characters change
    # form. known+mask already validated to sum to 4 by detect_date_format().
    sign, known, mask = _MASKED_RE.match(raw_value).groups()
    harmonised = f"{_sign_prefix(sign)}{known}{'X' * len(mask)}"
    return {"harmonised": harmonised, "format_detected": fmt, "confidence": "high"}


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and name_normaliser.py."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_dates_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, actor_uri):
    if monitor_module is None:
        return monitor_state
    context = f"Processed actor {actor_uri} (index {index}/{total})"
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


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


def collect_unique_actor_dates(input_path: str) -> dict[str, dict[str, str]]:
    """
    Deduplicate raw rows by actor URI, keeping the first non-empty value seen
    for each of DATE_FIELDS per actor.
    """
    actors: dict[str, dict[str, str]] = {}
    for row in iter_actor_rows(input_path):
        actor_uri = normalise(row.get("actor", ""))
        if not actor_uri:
            continue
        entry = actors.setdefault(actor_uri, {field: "" for field in DATE_FIELDS})
        for field in DATE_FIELDS:
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
    Load the input CSV/ZIP, apply normalise_date() to each unique actor's
    four date fields, and write the output mapping CSV. Returns the output
    file path.
    """
    actors = collect_unique_actor_dates(input_path)
    total = len(actors)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    stats = {"exact_year": 0, "exact_date": 0, "year_month": 0,
             "masked_precision": 0, "missing": 0, "non_parseable": 0}

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during dates_normaliser.py execution",
            print_start_message=True,
        )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, (actor_uri, fields) in enumerate(sorted(actors.items())):
            for field in DATE_FIELDS:
                original = fields[field]
                result = normalise_date(original)
                stats[result["format_detected"]] += 1
                writer.writerow({
                    "actor_uri": actor_uri,
                    "field": field,
                    "date_original": original,
                    "date_harmonised": result["harmonised"],
                    "date_format_detected": result["format_detected"],
                    "confidence": result["confidence"],
                })
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i + 1, total, actor_uri)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actor_dates harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {total:,} actors x {len(DATE_FIELDS)} fields -> {output_path}")
    for fmt, count in stats.items():
        print(f"  {fmt:<18}: {count:,}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_dates heuristic normaliser "
                    "(numeric BnF date convention -> EDTF; see module docstring)")
    parser.add_argument("--input", default=INPUT_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Output directory")
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.output, args.output_filename,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
