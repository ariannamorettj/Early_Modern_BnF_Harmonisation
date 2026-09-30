#!/usr/bin/env python3
"""
llm_name_normaliser.py  —  Module 04, actor_name LLM-based residual step.

Scope
-----
Resolves the residual that 01_heuristic_rules/name_normaliser.py
deliberately leaves unresolved: rows whose correction_type is one of

    unresolved_brackets_or_separators — a bracket/quote/separator character
        is present but does not cleanly wrap the whole string (e.g. a book
        title quoted mid-sentence missing its closing "]"), so a blind
        strip would corrupt the value rather than clean it.
    unresolved_multiple_values — an internal conjunction suggests the cell
        concatenates two person names (e.g. "Jean et Pierre Dupont"), but
        the heuristic step deliberately never auto-splits (picking one name
        over the other would be a guess, not a correction).
    initials_or_abbreviation_unresolved — actor_name is bare initials/an
        abbreviation ("Th.", "M. B. L.") and actor_first_name/
        actor_last_name gave nothing more informative to fall back on.

This is the field's equivalent of actor_dates' non_parseable residual and
publisher's multi_value residual: real but genuinely ambiguous cases that
need judgement a regex cannot safely make — same "deterministic-first,
LLM-as-last-resort" principle documented in
04_harmonisation_and_evaluation/README.md section 1.

Deliberately NOT sent to the LLM (superseding this module's own original
placeholder plan, which spoke of "all rows with confidence != high" — a
broader net than what is actually sent here):
    - 'unresolved_missing' — no value in ANY of the three source fields
      (actor_name/actor_first_name/actor_last_name) at all; there is
      nothing in an empty string for a model to derive a name from, same
      reasoning as llm_dates_normaliser.py excluding 'missing' rows.
    - 'alias_split' / 'stripped_title_role' (medium confidence, not low) —
      these already went through a clear, well-defined textual rule (a
      recognised alias marker / title token actually matched) and produced
      a concrete transformation; medium confidence here reflects genuine
      uncertainty about which side of the split is "primary", not that the
      rule mismatched. Revisiting an already-resolved value is a different
      kind of step than resolving a genuinely unresolved one — the two
      prior LLM steps in this pipeline (llm_dates_normaliser.py,
      llm_publisher_normaliser.py) never re-touch anything the heuristic
      step successfully resolved either, only the residual it explicitly
      flagged as unresolved.

Design choices (mirrors llm_dates_normaliser.py / llm_publisher_normaliser.py)
--------------------------------------------------------------------------------
- Deduplicated by (raw actor_name, correction_type), not by row: the same
  raw string can recur across many actors, and — unlike actor_dates/
  publisher, which each have a single residual category — actor_name has
  three, so the pair (not the raw value alone) is the true dedup key: the
  same literal text could in principle need a different kind of judgement
  depending on which rule flagged it (unlikely in practice, but the pair
  key costs nothing and is the only fully correct choice).
- Response caching (--cache, JSON file), keyed by "<correction_type>::<raw
  value>". Persisted incrementally.
- Model: Claude Opus 5, structured output via client.messages.parse()
  (Pydantic schema), effort defaults to "low".

Output (merged in place into the heuristic output file by default)
--------------------------------------------------------------------
Same schema as 01_heuristic_rules/name_normaliser.py, plus llm_explanation:
    actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence | llm_explanation

Rows the heuristic step already resolved (high or medium confidence, plus
'unresolved_missing') pass through unchanged (llm_explanation = ""). Rows
resolved by this step get actor_name_harmonised / confidence updated,
correction_type set to 'llm_resolved', and llm_explanation filled in. Rows
the LLM also could not resolve keep their original correction_type and get
llm_explanation explaining why.

Monitoring
----------
Same 00_monitor/monitor.py "embedded state-based monitoring" mechanism as
the rest of the pipeline: one checkpoint every MONITOR_CHECKPOINT_EVERY
(100) unique (value, correction_type) pairs and at the last one, plus a
final checkpoint. On by default via CLI, --no-monitor
to disable.

Requirements
------------
Needs the `anthropic` and `pydantic` packages (see pyproject.toml) and an
Anthropic API credential resolvable by the SDK to actually call the API.
Both are imported lazily so this module can still be imported — and its
non-API logic unit-tested — without either installed.

Usage
-----
python llm_name_normaliser.py \\
    --heuristic-output 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output/actor_name_harmonised.csv \\
    --output           04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output/actor_name_harmonised.csv \\
    --cache            04_harmonisation_and_evaluation/01_harmonisation/actor_name/02_llm_based/llm_responses_cache/name_responses_cache.json

# disable the monitor report
python llm_name_normaliser.py --no-monitor
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
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "01_heuristic_rules/output/actor_name_harmonised.csv"
)
OUTPUT_DEFAULT = HEURISTIC_OUTPUT_DEFAULT  # merged in place by default
CACHE_PATH_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "02_llm_based/llm_responses_cache/name_responses_cache.json"
)
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per value cost ~55 ms each (mostly the nvidia-smi GPU read),
# which dominated re-runs where every value comes from the cache; checkpoint
# every N values plus the last one instead.
MONITOR_CHECKPOINT_EVERY = 100
MODEL_DEFAULT = "claude-opus-5"
EFFORT_DEFAULT = "low"

OUTPUT_FIELDS = [
    "actor_uri", "actor_name_original", "actor_name_harmonised",
    "correction_type", "confidence", "llm_explanation",
]

# The three genuinely-unresolved categories left by the heuristic step (see
# module docstring for why 'unresolved_missing'/'alias_split'/
# 'stripped_title_role' are excluded).
RESOLVABLE_TYPES = {
    "unresolved_brackets_or_separators",
    "unresolved_multiple_values",
    "initials_or_abbreviation_unresolved",
}

_ISSUE_DESCRIPTIONS = {
    "unresolved_brackets_or_separators": (
        "a bracket/quote/separator character is present but does not "
        "cleanly wrap the whole string (a blind strip would corrupt the "
        "value, e.g. leaving a stray unmatched bracket behind)"
    ),
    "unresolved_multiple_values": (
        "an internal conjunction suggests this cell may concatenate two "
        "distinct person names rather than being one name"
    ),
    "initials_or_abbreviation_unresolved": (
        "the value is bare initials or a dotted abbreviation, and no "
        "fuller form was available from separate given-name/family-name "
        "fields to fall back on"
    ),
}

SYSTEM_PROMPT = """You resolve ambiguous actor-name values from a BnF \
(Bibliotheque nationale de France) bibliographic-actor dataset that a \
deterministic heuristic step could not confidently clean up on its own.

You will be told which of three specific issues applies to the value:

1. unresolved_brackets_or_separators: a bracket/quote/separator character \
is present but doesn't cleanly wrap the whole string. If you can tell what \
the actual person's name is once the stray character(s) are accounted for, \
return the cleaned name. If not, return empty.

2. unresolved_multiple_values: the text looks like it may concatenate two \
distinct person names via a conjunction (e.g. "Jean et Pierre Dupont"). If \
it genuinely names two different people, return both names joined by "; ", \
in the order they appear. If it is actually a single person's name (a \
legitimate compound-name form the heuristic's conservative pattern missed), \
return that single cleaned name instead.

3. initials_or_abbreviation_unresolved: the value is only initials or an \
abbreviation (e.g. "Th.", "M. B. L.") with no fuller form available from \
the record's own first-name/last-name fields. Do NOT invent or guess a \
full name from outside knowledge of who a historical figure might be — \
that is a job for authority-linking (VIAF/Wikidata), not for this step. \
Only return a cleaned value if the initials/abbreviation form itself needs \
trivial formatting (e.g. spacing/punctuation), never a guessed expansion. \
In the common case, correctly return empty here.

If you cannot confidently resolve the value, return harmonised as an empty \
string and confidence "low" — do not guess. Return confidence "high" only \
when the correct reading is unambiguous; "medium" for a reasonable but not \
fully certain reading. Always return a plain, short explanation of your \
reasoning, in English."""


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def _cache_key(raw_value: str, correction_type: str) -> str:
    return f"{correction_type}::{raw_value}"


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

    class NameResolution(BaseModel):
        harmonised: str
        confidence: str
        explanation: str

    return NameResolution


def resolve_name_with_llm(client, raw_value: str, correction_type: str,
                          model: str = MODEL_DEFAULT,
                          effort: str = EFFORT_DEFAULT) -> dict:
    """
    Call the LLM once for a single (raw actor_name, correction_type) pair.
    Returns {harmonised, confidence, explanation}.
    """
    NameResolution = _resolution_schema()
    issue = _ISSUE_DESCRIPTIONS[correction_type]
    user_content = f'Value: "{raw_value}"\nIssue detected: {correction_type} — {issue}'
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        output_config={"effort": effort},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=NameResolution,
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
    spec = importlib.util.spec_from_file_location("monitor_llm_name_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Main pipeline ─────────────────────────────────────────────────────────────

def load_heuristic_rows(heuristic_output_csv: str) -> list[dict]:
    with open(heuristic_output_csv, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def collect_unique_residual_values(rows: list[dict]) -> list[tuple[str, str]]:
    """Distinct (raw actor_name, correction_type) pairs among rows the
    heuristic step left in one of RESOLVABLE_TYPES, in first-seen order
    (deterministic across runs for the same input)."""
    seen: dict[tuple[str, str], None] = {}
    for row in rows:
        correction_type = normalise(row.get("correction_type", ""))
        if correction_type not in RESOLVABLE_TYPES:
            continue
        raw_value = normalise(row.get("actor_name_original", ""))
        key = (raw_value, correction_type)
        if raw_value and key not in seen:
            seen[key] = None
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
    Load the heuristic normaliser's output, resolve the RESOLVABLE_TYPES
    residual via the LLM (cached, deduplicated by (value, correction_type)),
    and write the merged output. `client` is injectable for testing.
    """
    rows = load_heuristic_rows(heuristic_output_csv)
    unique_pairs = collect_unique_residual_values(rows)
    total = len(unique_pairs)

    cache = load_cache(cache_path)
    already_cached = sum(1 for pair in unique_pairs if _cache_key(*pair) in cache)
    print(f"  {total:,} unique residual (value, issue) pairs ({already_cached:,} already cached).")

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during llm_name_normaliser.py execution",
            print_start_message=True,
        )

    if total > already_cached and client is None:
        client = get_client()

    resolved_count = 0
    for i, (raw_value, correction_type) in enumerate(unique_pairs):
        key = _cache_key(raw_value, correction_type)
        if key not in cache:
            cache[key] = resolve_name_with_llm(
                client, raw_value, correction_type, model=model, effort=effort)
            save_cache(cache_path, cache)  # persist incrementally: safe to interrupt/resume
        if cache[key]["harmonised"]:
            resolved_count += 1
        if use_monitor and ((i + 1) % MONITOR_CHECKPOINT_EVERY == 0 or i + 1 == total):
            monitor_state = monitor_module.update_monitor_state(
                state=monitor_state,
                context=f"Resolved pair {i + 1}/{total} ({raw_value!r}, {correction_type})",
                print_console=True,
            )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            out_row = {field: normalise(row.get(field, "")) for field in OUTPUT_FIELDS[:-1]}
            # correction_type is passed through as-is (not normalise()'d):
            # name_normaliser.py uses the literal string "none" as a valid
            # correction_type ("no anomaly detected"), which normalise()'s
            # null-marker set would otherwise silently blank out (it treats
            # "NONE" as a missing-value marker -- correct for actual data
            # fields, wrong for this one).
            out_row["correction_type"] = str(row.get("correction_type", "")).strip()
            out_row["llm_explanation"] = ""
            raw_value = out_row["actor_name_original"]
            correction_type = out_row["correction_type"]
            if correction_type in RESOLVABLE_TYPES:
                key = _cache_key(raw_value, correction_type)
                if key in cache:
                    resolution = cache[key]
                    if resolution["harmonised"]:
                        out_row["actor_name_harmonised"] = resolution["harmonised"]
                        out_row["correction_type"] = "llm_resolved"
                        out_row["confidence"] = resolution["confidence"]
                    out_row["llm_explanation"] = resolution["explanation"]
            writer.writerow(out_row)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actor_name LLM residual run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Resolved {resolved_count:,}/{total:,} unique residual pairs -> {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_name LLM residual normaliser "
                    "(resolves the unresolved_brackets_or_separators / "
                    "unresolved_multiple_values / initials_or_abbreviation_unresolved "
                    "residual left by name_normaliser.py; see module docstring)")
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
