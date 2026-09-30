#!/usr/bin/env python3
"""
llm_dates_normaliser.py  —  Module 04, actor_dates LLM-based residual step.

Scope
-----
Resolves the small residual that 01_heuristic_rules/dates_normaliser.py
deliberately does not attempt: rows classified as 'non_parseable' (hybrid or
malformed forms such as a mask character inside a full date, e.g.
"150.-02-20", or an unexpected mask character like "14??" — see that
script's module docstring for the full category breakdown). That residual
is ~0.017% of all non-empty date values (292 rows out of 1,731,972 in the
raw dataset at the time of writing) — this step exists specifically because
the heuristic rule already covers 99.98% deterministically; see
04_harmonisation_and_evaluation/README.md section 1 ("Deterministic-first,
LLM-as-last-resort") for why that ordering, and why the LLM step is kept
default-on rather than opt-in: it only ever sees the small residual the
heuristic step could not resolve, never re-processes anything already
resolved with high confidence.

'missing' rows (no value at all in the source) are NOT sent to the LLM —
there is nothing in an empty string for a model to derive a date from, so
that would be inventing data rather than resolving an ambiguity.

Design choices
--------------
- Deduplicated by raw value, not by row: many non_parseable rows share the
  exact same raw string (e.g. "175.-07-27" appears 21 times in the actor
  dataset, across different actors/fields) because the same malformed
  source pattern recurs. The LLM is called once per UNIQUE raw value, and
  the result is applied to every row that shares it — this keeps the
  (already tiny) API cost/latency proportional to the number of distinct
  malformed patterns, not the number of affected rows, and guarantees the
  same input always maps to the same output within a run.
- Response caching (--cache, JSON file): once a raw value has been
  resolved, the result is cached to disk and reused on every subsequent
  run — re-running this script (e.g. after a heuristic-rule change touches
  unrelated rows) does not re-query already-resolved values.
- Model: Claude Opus 5 (see 04_harmonisation_and_evaluation/README.md
  section 1). Structured output (Pydantic schema via
  client.messages.parse()) guarantees a parseable {harmonised, confidence,
  explanation} response instead of hoping the model returns valid JSON.
  effort defaults to "low": this is a simple, well-scoped extraction task
  per value (not open-ended reasoning), and the dataset here is tiny
  (currently ~24 unique malformed forms) — low effort is the appropriate
  setting for this kind of task per the project's model-usage guidance,
  not a downgrade of the model itself.

Output (merged in place into the heuristic output file by default)
--------------------------------------------------------------------
Same schema as 01_heuristic_rules/dates_normaliser.py, plus llm_explanation:
    actor_uri | field | date_original | date_harmonised | date_format_detected | confidence | llm_explanation

Rows the heuristic step already resolved pass through unchanged
(llm_explanation = ""). Rows resolved by this step get date_harmonised /
confidence updated, date_format_detected set to 'llm_resolved', and
llm_explanation filled in. Rows the LLM also could not resolve keep
date_format_detected = 'non_parseable' and get llm_explanation explaining
why, so the reason is visible in the same file rather than only in logs.

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: one checkpoint every MONITOR_CHECKPOINT_EVERY
(100) unique raw values and at the last one, plus a final checkpoint. On by default via CLI, --no-monitor to disable.

Requirements
------------
Needs the `anthropic` and `pydantic` packages (see pyproject.toml) and an
Anthropic API credential resolvable by the SDK (ANTHROPIC_API_KEY env var,
or an `ant auth login` profile) to actually call the API. Both packages are
imported lazily (inside the functions that need them) so this module can
still be imported — and its non-API logic unit-tested — without either
installed; only actually calling run()/main() against the real API needs
them.

Usage
-----
python llm_dates_normaliser.py \\
    --heuristic-output 04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/output/actor_dates_harmonised.csv \\
    --output           04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/output/actor_dates_harmonised.csv \\
    --cache            04_harmonisation_and_evaluation/01_harmonisation/actor_dates/02_llm_based/llm_responses_cache/date_responses_cache.json

# disable the monitor report
python llm_dates_normaliser.py --no-monitor
"""

import os, csv, sys, json, argparse, importlib.util
from pathlib import Path

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

HEURISTIC_OUTPUT_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_dates/"
    "01_heuristic_rules/output/actor_dates_harmonised.csv"
)
OUTPUT_DEFAULT = HEURISTIC_OUTPUT_DEFAULT  # merged in place by default
CACHE_PATH_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_dates/"
    "02_llm_based/llm_responses_cache/date_responses_cache.json"
)
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per value cost ~55 ms each (mostly the nvidia-smi GPU read),
# which dominated re-runs where every value comes from the cache; checkpoint
# every N values plus the last one instead.
MONITOR_CHECKPOINT_EVERY = 100
MODEL_DEFAULT = "claude-opus-5"
EFFORT_DEFAULT = "low"

OUTPUT_FIELDS = [
    "actor_uri", "field", "date_original", "date_harmonised",
    "date_format_detected", "confidence", "llm_explanation",
]

RESOLVABLE_FORMAT = "non_parseable"

SYSTEM_PROMPT = """You resolve malformed date values from a BnF (Bibliothèque \
nationale de France) actor-date dataset into EDTF (Extended Date/Time \
Format).

Context — the source's normal convention (already handled deterministically \
elsewhere; you only see the small residual that does not fit these clean \
patterns):
- A plain year: 1-4 digits, no zero-padding, e.g. "1750", "43", "882".
- A full date: "YYYY-MM-DD", e.g. "1594-06-14".
- A year-month: "YYYY-MM", e.g. "1564-04".
- Masked precision: trailing '.' or 'X' characters replace digits the \
source never recorded (century/decade/millennium-level precision only), \
e.g. "17.." or "17XX" both mean "some year in 1700-1799" (18th century). \
Known digits + mask characters always total 4 (one full year's width).
- Optional BCE sign: a leading "-" (with or without a following space, \
e.g. "-43" or "- 43") marks a BCE year. IMPORTANT: this source uses \
ORDINARY HISTORICAL BCE counting, NOT ISO/EDTF astronomical year \
numbering — do NOT apply the +1/-1 astronomical offset. "-43" means \
literally "43 BCE", converted to EDTF as "-0043" (zero-padded, sign kept, \
digits unchanged).

Your job: the raw value you are given did NOT fit any of the patterns \
above cleanly (e.g. a mask character inside a full date like \
"150.-02-20", a masked day instead of a masked year like "1799-03-2.", or \
an unexpected mask character like "14??" used the same way as '.' or \
'X'). Using the same conventions above (mask -> 'X' in EDTF, BCE sign kept \
literally with zero-padding, no astronomical offset), work out what the \
value most likely means and express it in EDTF using 'X' for any digit \
position that is genuinely unspecified.

If you cannot confidently resolve the value even with this reasoning, \
return harmonised as an empty string and confidence "low" — do not guess. \
Return confidence "high" only when the source pattern is unambiguous once \
interpreted per the rules above; "medium" for a reasonable but not fully \
certain reading.

Always return a plain, short explanation of your reasoning, in English."""


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


# ── Cache ────────────────────────────────────────────────────────────────────

def load_cache(cache_path: str) -> dict:
    if not cache_path or not os.path.exists(cache_path):
        return {}
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache_path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True, ensure_ascii=False)


# ── LLM call (anthropic/pydantic imported lazily — see module docstring) ────

def get_client():
    import anthropic
    return anthropic.Anthropic()


def _resolution_schema():
    from pydantic import BaseModel

    class DateResolution(BaseModel):
        harmonised: str
        confidence: str
        explanation: str

    return DateResolution


def resolve_date_with_llm(client, raw_value: str,
                          model: str = MODEL_DEFAULT,
                          effort: str = EFFORT_DEFAULT) -> dict:
    """
    Call the LLM once for a single raw date value. Returns
    {harmonised, confidence, explanation}.
    """
    DateResolution = _resolution_schema()
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        output_config={"effort": effort},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_value}],
        output_format=DateResolution,
    )
    parsed = response.parsed_output
    return {
        "harmonised": parsed.harmonised,
        "confidence": parsed.confidence,
        "explanation": parsed.explanation,
    }


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_llm_dates_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def load_heuristic_rows(heuristic_output_csv: str) -> list[dict]:
    with open(heuristic_output_csv, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def collect_unique_non_parseable_values(rows: list[dict]) -> list[str]:
    """Distinct raw values among rows the heuristic step left unresolved,
    in first-seen order (deterministic across runs for the same input)."""
    seen: dict[str, None] = {}
    for row in rows:
        if normalise(row.get("date_format_detected", "")) != RESOLVABLE_FORMAT:
            continue
        raw_value = normalise(row.get("date_original", ""))
        if raw_value and raw_value not in seen:
            seen[raw_value] = None
    return list(seen.keys())


def run(heuristic_output_csv: str = HEURISTIC_OUTPUT_DEFAULT,
       output_path: str = OUTPUT_DEFAULT,
       cache_path: str = CACHE_PATH_DEFAULT,
       model: str = MODEL_DEFAULT,
       effort: str = EFFORT_DEFAULT,
       use_monitor: bool = False,
       monitor_script: str = MONITOR_SCRIPT_DEFAULT,
       client=None) -> str:
    """
    Load the heuristic normaliser's output, resolve the non_parseable
    residual via the LLM (cached, deduplicated by raw value), and write the
    merged output. `client` is injectable for testing; when None, a real
    Anthropic client is constructed lazily on first use (get_client()).
    """
    rows = load_heuristic_rows(heuristic_output_csv)
    unique_values = collect_unique_non_parseable_values(rows)
    total = len(unique_values)

    cache = load_cache(cache_path)
    already_cached = sum(1 for v in unique_values if v in cache)
    print(f"  {total:,} unique non_parseable values ({already_cached:,} already cached).")

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during llm_dates_normaliser.py execution",
            print_start_message=True,
        )

    if total > already_cached and client is None:
        client = get_client()

    resolved_count = 0
    for i, raw_value in enumerate(unique_values):
        if raw_value not in cache:
            cache[raw_value] = resolve_date_with_llm(client, raw_value, model=model, effort=effort)
            save_cache(cache_path, cache)  # persist incrementally: safe to interrupt/resume
        if cache[raw_value]["harmonised"]:
            resolved_count += 1
        if use_monitor and ((i + 1) % MONITOR_CHECKPOINT_EVERY == 0 or i + 1 == total):
            monitor_state = monitor_module.update_monitor_state(
                state=monitor_state,
                context=f"Resolved value {i + 1}/{total} ({raw_value!r})",
                print_console=True,
            )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            out_row = {field: normalise(row.get(field, "")) for field in OUTPUT_FIELDS[:-1]}
            out_row["llm_explanation"] = ""
            raw_value = out_row["date_original"]
            if out_row["date_format_detected"] == RESOLVABLE_FORMAT and raw_value in cache:
                resolution = cache[raw_value]
                if resolution["harmonised"]:
                    out_row["date_harmonised"] = resolution["harmonised"]
                    out_row["date_format_detected"] = "llm_resolved"
                    out_row["confidence"] = resolution["confidence"]
                out_row["llm_explanation"] = resolution["explanation"]
            writer.writerow(out_row)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actor_dates LLM residual run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Resolved {resolved_count:,}/{total:,} unique non_parseable values -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_dates LLM residual normaliser "
                    "(resolves the non_parseable residual left by dates_normaliser.py; "
                    "see module docstring)")
    parser.add_argument("--heuristic-output", default=HEURISTIC_OUTPUT_DEFAULT)
    parser.add_argument("--output",           default=OUTPUT_DEFAULT)
    parser.add_argument("--cache",            default=CACHE_PATH_DEFAULT)
    parser.add_argument("--model",            default=MODEL_DEFAULT)
    parser.add_argument("--effort",           default=EFFORT_DEFAULT,
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--monitor-script",   default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor",       action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.heuristic_output, args.output, args.cache, args.model, args.effort,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
