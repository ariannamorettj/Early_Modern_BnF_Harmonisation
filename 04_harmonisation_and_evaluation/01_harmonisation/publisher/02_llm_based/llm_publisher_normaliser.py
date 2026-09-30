#!/usr/bin/env python3
"""
llm_publisher_normaliser.py  —  Module 04, publisher LLM-based residual step.

Scope
-----
Resolves the residual that 01_heuristic_rules/publisher_normaliser.py
deliberately does not attempt to resolve on its own: rows flagged
'multi_value' (a cell containing what looks like more than one publisher
name concatenated together, e.g. "Vve F. Muguet et H. Muguet", or an
idiomatic single-firm name that merely contains "et"/"-" and was flagged as
a false positive, e.g. a hypothetical "X et fils" — see
publisher_normaliser.py's module docstring for why the heuristic step
deliberately flags rather than guesses here). This is the field's
equivalent of actor_dates' non_parseable residual: a real but genuinely
ambiguous case that needs judgement a regex cannot safely make — same
"deterministic-first, LLM-as-last-resort" principle documented in
04_harmonisation_and_evaluation/README.md section 1.

'missing', 'sine_nomine', and 'self_published' rows are NOT sent to the
LLM — those are already definitive answers from the heuristic step, not an
ambiguity to resolve. 'passthrough'/'abbreviation_expanded'/
'bracketed_uncertain'/'location_stripped'/'canonical_clustered' rows are
already high/medium-confidence resolved values and are also not touched.

Design choices (mirrors llm_dates_normaliser.py)
--------------------------------------------------
- Deduplicated by raw value, not by row: the same flagged publisher string
  can recur across many editions. The LLM is called once per UNIQUE raw
  value; the result is applied to every row that shares it.
- Response caching (--cache, JSON file): once a raw value has been
  resolved, the result is cached to disk and reused on every subsequent run.
- Model: Claude Opus 5, structured output via client.messages.parse()
  (Pydantic schema), effort defaults to "low" — a bounded per-value
  classification/extraction task, not open-ended reasoning.

Output (merged in place into the heuristic output file by default)
--------------------------------------------------------------------
Same schema as 01_heuristic_rules/publisher_normaliser.py, plus llm_explanation:
    edition | publisher_original | publisher_harmonised | correction_type | confidence | llm_explanation

Rows the heuristic step already resolved pass through unchanged
(llm_explanation = ""). Rows resolved by this step get publisher_harmonised
/ confidence updated, correction_type set to 'llm_resolved', and
llm_explanation filled in. Rows the LLM also could not resolve keep
correction_type = 'multi_value' and get llm_explanation explaining why.

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: one checkpoint every MONITOR_CHECKPOINT_EVERY
(100) unique raw values and at the last one, plus a final checkpoint. On by default via CLI, --no-monitor to disable.

Requirements
------------
Needs the `anthropic` and `pydantic` packages (see pyproject.toml) and an
Anthropic API credential resolvable by the SDK to actually call the API.
Both are imported lazily so this module can still be imported — and its
non-API logic unit-tested — without either installed.

Usage
-----
python llm_publisher_normaliser.py \\
    --heuristic-output 04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/output/publisher_harmonised.csv \\
    --output           04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/output/publisher_harmonised.csv \\
    --cache            04_harmonisation_and_evaluation/01_harmonisation/publisher/02_llm_based/llm_responses_cache/publisher_responses_cache.json

# disable the monitor report
python llm_publisher_normaliser.py --no-monitor
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
    "04_harmonisation_and_evaluation/01_harmonisation/publisher/"
    "01_heuristic_rules/output/publisher_harmonised.csv"
)
OUTPUT_DEFAULT = HEURISTIC_OUTPUT_DEFAULT  # merged in place by default
CACHE_PATH_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/publisher/"
    "02_llm_based/llm_responses_cache/publisher_responses_cache.json"
)
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per value cost ~55 ms each (mostly the nvidia-smi GPU read),
# which dominated re-runs where every value comes from the cache; checkpoint
# every N values plus the last one instead.
MONITOR_CHECKPOINT_EVERY = 100
MODEL_DEFAULT = "claude-opus-5"
EFFORT_DEFAULT = "low"

OUTPUT_FIELDS = [
    "edition", "publisher_original", "publisher_harmonised",
    "correction_type", "confidence", "llm_explanation",
]

RESOLVABLE_TYPE = "multi_value"

SYSTEM_PROMPT = """You resolve ambiguous publisher-statement values from a \
BnF (Bibliotheque nationale de France) bibliographic-edition dataset.

Context: a deterministic heuristic step already handled the clear cases \
(sine-nomine markers, self-published markers, known abbreviations, \
bracketed/location-stripped names). You only see values it flagged as \
'multi_value': the raw text contains a delimiter (';', ' - ', or the word \
'et') that USUALLY separates two or more distinct publisher names \
concatenated in one cell (e.g. "Vve F. Muguet et H. Muguet" = two \
publishers, the widow of F. Muguet and H. Muguet), but occasionally is \
just part of a single firm's own name that happens to contain that word \
(e.g. a firm literally named "X et fils", father-and-son, still ONE \
publisher).

Your job: decide which case applies.
- If it is genuinely multiple distinct publishers, return them joined by \
"; ", each cleaned of stray punctuation, in the order they appear.
- If it is actually a single publisher's own name, return that single \
cleaned name (do not split it).
- If you cannot confidently tell, return harmonised as an empty string and \
confidence "low" — do not guess.

Return confidence "high" only when the source pattern is unambiguous; \
"medium" for a reasonable but not fully certain reading. Always return a \
plain, short explanation of your reasoning, in English."""


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

    class PublisherResolution(BaseModel):
        harmonised: str
        confidence: str
        explanation: str

    return PublisherResolution


def resolve_publisher_with_llm(client, raw_value: str,
                               model: str = MODEL_DEFAULT,
                               effort: str = EFFORT_DEFAULT) -> dict:
    """
    Call the LLM once for a single raw publisher value. Returns
    {harmonised, confidence, explanation}.
    """
    PublisherResolution = _resolution_schema()
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        output_config={"effort": effort},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_value}],
        output_format=PublisherResolution,
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
    spec = importlib.util.spec_from_file_location("monitor_llm_publisher_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def load_heuristic_rows(heuristic_output_csv: str) -> list[dict]:
    with open(heuristic_output_csv, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def collect_unique_multi_value_values(rows: list[dict]) -> list[str]:
    """Distinct raw values among rows the heuristic step flagged as
    'multi_value', in first-seen order (deterministic across runs)."""
    seen: dict[str, None] = {}
    for row in rows:
        if normalise(row.get("correction_type", "")) != RESOLVABLE_TYPE:
            continue
        raw_value = normalise(row.get("publisher_original", ""))
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
    Load the heuristic normaliser's output, resolve the multi_value
    residual via the LLM (cached, deduplicated by raw value), and write the
    merged output. `client` is injectable for testing.
    """
    rows = load_heuristic_rows(heuristic_output_csv)
    unique_values = collect_unique_multi_value_values(rows)
    total = len(unique_values)

    cache = load_cache(cache_path)
    already_cached = sum(1 for v in unique_values if v in cache)
    print(f"  {total:,} unique multi_value values ({already_cached:,} already cached).")

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during llm_publisher_normaliser.py execution",
            print_start_message=True,
        )

    if total > already_cached and client is None:
        client = get_client()

    resolved_count = 0
    for i, raw_value in enumerate(unique_values):
        if raw_value not in cache:
            cache[raw_value] = resolve_publisher_with_llm(client, raw_value, model=model, effort=effort)
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
            raw_value = out_row["publisher_original"]
            if out_row["correction_type"] == RESOLVABLE_TYPE and raw_value in cache:
                resolution = cache[raw_value]
                if resolution["harmonised"]:
                    out_row["publisher_harmonised"] = resolution["harmonised"]
                    out_row["correction_type"] = "llm_resolved"
                    out_row["confidence"] = resolution["confidence"]
                out_row["llm_explanation"] = resolution["explanation"]
            writer.writerow(out_row)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed publisher LLM residual run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Resolved {resolved_count:,}/{total:,} unique multi_value values -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="publisher LLM residual normaliser "
                    "(resolves the multi_value residual left by publisher_normaliser.py; "
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
