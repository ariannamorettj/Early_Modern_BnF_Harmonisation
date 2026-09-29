#!/usr/bin/env python3
"""
language_normaliser.py  —  Module 04, language heuristic rules.

Scope of this implementation
-----------------------------
Normalises the `language` field of the bnf_edition_data dataset (language of
the bibliographic Expression, rdcterms:language) to ISO 639-2 codes.

IMPORTANT — this supersedes the free-text anomaly categories speculated in
this module's original placeholder docstring and in the module README
("français", "vieux français", "Latin et français", "???", etc.): a full
scan of the real raw dataset (01_data_retrieval/01_editions/data/
bnf_edition_data_raw.csv, 1,344,914 rows) found NONE of that free text.
The field's non-empty values are ALWAYS an RDF-wrapped LOC vocabulary URI:

    "<http://id.loc.gov/vocabulary/iso639-2/fre>"
    "<http://id.loc.gov/vocabulary/iso639-2/lat>"
    ...

106 distinct non-empty raw values were found across the full dataset, and
every single one matches this exact pattern (0 exceptions) — the trailing
path segment is already a valid ISO 639-2 (bibliographic) three-letter code
(confirmed against the LOC vocabulary: afr, ara, chi, dut, eng, fre, ger,
grc, gre, lat, mul, zxx, ... all 106 are legitimate distinct codes, not
duplicates or errors). "mul" (multiple languages) and "zxx" (no linguistic
content) are themselves already the source's own codes for those cases —
i.e. multi-language expressions are already handled upstream by BnF as a
single controlled code, not as concatenated free text the way the README
speculated.

Because of this, the whole field reduces to a single deterministic rule:
strip the RDF '<...>' wrapper, take the URI's trailing path segment, and
validate it is 3 lowercase letters. No lookup dictionary (language_lookup.json)
is needed, and no LLM step is needed — 100% of the real data resolves
deterministically with high confidence. The 'non_parseable' category below
is kept as a safety net for any future data that does not match the pattern
above (documented for completeness, not currently populated: 0/106).

Input
-----
Raw edition dataset (module 1's acquisition output) with columns including
`edition` and `language`, e.g.
01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv
Same source and same row-multiplicity characteristics as
publication_place/02_tgn_lookup/bnf_place_harmonisation.py (the raw dataset
has ~35% duplicate rows per edition from SPARQL multi-valued role columns);
this script dedupes to the first non-empty `language` value seen per
edition, mirroring bnf_place_harmonisation.py's edition_to_place approach —
language does not vary across an edition's duplicate raw rows the way role
columns do.

Output
------
04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/output/language_harmonised.csv:
    edition | language_original | language_harmonised | correction_type | confidence

04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/report/language_report.json:
    summary statistics (distinct raw values, category counts)

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: one checkpoint every 50,000 editions processed,
plus a final checkpoint. Reports land in
00_monitor/report/language_normaliser_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python language_normaliser.py \\
    --input  01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/output/language_harmonised.csv \\
    --report 04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/report/language_report.json

# disable the monitor report
python language_normaliser.py --no-monitor
"""

import os, csv, sys, re, json, argparse, importlib.util
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

INPUT_DEFAULT = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv"
_LANGUAGE_DIR = "04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules"
OUTPUT_DEFAULT = f"{_LANGUAGE_DIR}/output/language_harmonised.csv"
REPORT_DEFAULT = f"{_LANGUAGE_DIR}/report/language_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
MONITOR_CHECKPOINT_EVERY = 50_000

OUTPUT_FIELDS = ["edition", "language_original", "language_harmonised", "correction_type", "confidence"]

# The BnF source always expresses language as this exact LOC vocabulary URI
# form, RDF-wrapped in angle brackets — verified against the full raw
# dataset (106/106 distinct non-empty values match, 0 exceptions). See
# module docstring.
_ISO_URI_RE = re.compile(r"^<http://id\.loc\.gov/vocabulary/iso639-2/([a-z]{3})>$")


def detect_language_format(raw_value: str) -> str:
    """
    Classify a raw (already normalise()'d) language string into one of:

        missing        - empty string / null marker
        iso_code_uri    - "<http://id.loc.gov/vocabulary/iso639-2/xxx>"
                          (100% of the real dataset's non-empty values)
        non_parseable   - anything else. Kept as a safety net for future
                          data; not populated by the current dataset.
    """
    if not raw_value:
        return "missing"
    if _ISO_URI_RE.match(raw_value):
        return "iso_code_uri"
    return "non_parseable"


def normalise_language(raw_value: str) -> dict:
    """
    Convert a raw (already normalise()'d) language string to its ISO 639-2
    code, dispatching on detect_language_format().

    Returns: { 'harmonised': str, 'correction_type': str, 'confidence': str }
    """
    fmt = detect_language_format(raw_value)

    if fmt == "missing":
        return {"harmonised": "", "correction_type": fmt, "confidence": "low"}

    if fmt == "iso_code_uri":
        code = _ISO_URI_RE.match(raw_value).group(1)
        return {"harmonised": code, "correction_type": fmt, "confidence": "high"}

    # non_parseable: left unresolved rather than guessed at, same
    # incremental philosophy as dates_normaliser.py's non_parseable residual.
    return {"harmonised": "", "correction_type": fmt, "confidence": "low"}


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring bnf_place_harmonisation.py."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_language_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(input_path: str, output_path: str, report_path: str,
       use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:

    # Pass 1: first (edition -> language) seen per edition — language does
    # not vary across an edition's duplicate raw rows.
    edition_to_language: dict[str, str] = {}
    with open(input_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            edition = normalise(row.get("edition", ""))
            if not edition or edition in edition_to_language:
                continue
            edition_to_language[edition] = normalise(row.get("language", ""))

    total = len(edition_to_language)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during language_normaliser.py execution",
            print_start_message=True,
        )

    stats = {"iso_code_uri": 0, "missing": 0, "non_parseable": 0}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, (edition, raw_value) in enumerate(sorted(edition_to_language.items())):
            result = normalise_language(raw_value)
            stats[result["correction_type"]] += 1
            writer.writerow({
                "edition": edition,
                "language_original": raw_value,
                "language_harmonised": result["harmonised"],
                "correction_type": result["correction_type"],
                "confidence": result["confidence"],
            })

            if use_monitor and (i + 1) % MONITOR_CHECKPOINT_EVERY == 0:
                monitor_state = monitor_module.update_monitor_state(
                    state=monitor_state,
                    context=f"Processed {i + 1:,}/{total:,} editions",
                    print_console=True,
                )

    report = {
        "total_editions": total,
        "distinct_raw_values": len({v for v in edition_to_language.values() if v}),
        **stats,
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed language harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {total:,} editions -> {output_path}")
    for correction_type, count in stats.items():
        print(f"  {correction_type:<16}: {count:,}")
    print(f"✓ Report -> {report_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="language heuristic normaliser "
                    "(LOC iso639-2 vocabulary URI -> ISO 639-2 code; see module docstring). "
                    "No lookup dictionary and no LLM step needed (100% deterministic coverage).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",          default=INPUT_DEFAULT)
    parser.add_argument("--output",         default=OUTPUT_DEFAULT)
    parser.add_argument("--report",         default=REPORT_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",     action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.output, args.report,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
