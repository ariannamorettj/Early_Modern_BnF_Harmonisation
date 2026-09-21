# actor_name — Heuristic-Rules Approach

This folder implements rule-based harmonisation for the `actor_name`, `actor_first_name`, and `actor_last_name` fields of the `actor_data` dataset.

## Context

The analysis phase (`03_analysis`) identified that name fields contain a wide variety of anomalies:
- Initials only (e.g., `M D`, `G.`)
- Abbreviations (e.g., `Th.`)
- Titles and roles embedded in the name string (e.g., `Veuve de`, `Sieur de`)
- Alternative names / aliases (e.g., `alias`, `dit le`, `detto il`)
- Multiple values concatenated in a single cell
- Non-alphanumeric characters (brackets, separators)
- Missing values / null markers (`***`, `null`)

## Approach

Heuristic rules based on:
1. **Regex patterns** for detecting structural anomalies (initials, dots, numbers, brackets)
2. **Token-level analysis** for multi-value detection and particle/conjunction disambiguation
3. **Lookup tables** (JSON dictionaries) for known substitutions and corrections
4. **Character-match and substitution** logic for cleaning detected errors

## Files

| File | Description |
|------|-------------|
| `actors_name_matching.py` | Groups actor rows by normalised `actor_name`, identifying actors appearing with multiple name variants. Pre-existing file. |
| `actors_id_matching.py` | Groups actor rows by BnF `actor` URI, identifying actors appearing with multiple metadata values. Pre-existing file. |
| `actors_deduplication.py` | Identity-resolution across distinct BnF actor URIs that share the same normalised `actor_name`: two records are merged when they also share an external link (`actor_link_exact`/`actor_link_close`) or identical `actor_birth`+`actor_death` values; same-name pairs with no such evidence are flagged `ambiguous_name_only` and left unmerged for manual review. See its module docstring for the full algorithm. |
| `name_normaliser.py` | **[IN PROGRESS]** Only the `derive_from_first_last` rule is implemented: fills `actor_name` from `actor_first_name`/`actor_last_name` when `actor_name` is empty (e.g. "Lucretius", stored only in `actor_last_name`). Regex cleaning, particle handling, bracket stripping, and alias detection are still **[TODO]**. |
| `name_correction_dict.json` | **[TODO]** JSON lookup dictionary mapping known erroneous name strings to their corrected form. |

## Expected Output

A CSV with columns:
- `actor_uri` — original BnF actor URI
- `actor_name_original` — original raw value
- `actor_name_harmonised` — corrected value after rule application
- `correction_type` — label of the rule that triggered the correction (e.g., `strip_brackets`, `remove_title`, `alias_split`)
- `confidence` — `high` / `medium` / `low` depending on rule certainty

## Deduplication output (`actors_deduplication.py`)

Input: the actors-ready dataset (`04_harmonisation_and_evaluation/output/bnf_actors_ready.csv`,
id column `actor`) **or** module 5's optimised subset
(`05_subset_optimisation 2/output/bnf_actors_optimised.csv`, id column
`BnF_ID`) — both id-column schemas are auto-detected (`get_actor_id()`).

`output/actor_dedup_mapping.csv` — one row per actor URI that shares its
normalised name with at least one other actor URI:
- `actor_uri`, `cluster_id`, `canonical_actor_uri`, `is_canonical`
- `match_type` — `shared_external_link` / `matching_dates` /
  `shared_external_link+matching_dates` (merged, high confidence),
  `ambiguous_name_only` (same name, no corroborating evidence — NOT merged),
  `group_too_large_to_compare` (name-group exceeded `--max-pairwise-group-size`,
  default 200 — NOT compared, for performance)
- `confidence` — `high` or `low`

`report/actor_dedup_report.json` — `merged_clusters`, `ambiguous_groups`,
`oversized_groups`, and summary `stats`, for manual review of the cases that
were not auto-resolved.

`report/actor_dedup_report.txt` — a plain-language rendering of the same
`stats` (template-filled, not LLM-generated) written automatically on every
run, so the outcome can be checked without parsing JSON.

**Not yet wired downstream**: unlike `actor_name_harmonised.csv` (below),
this mapping is not currently consumed by `assemble_actors_ready.py` or
`gen_subset_optm.py` — it is a standalone diagnostic/resolution step.
Applying it (e.g. collapsing each cluster onto its `canonical_actor_uri`
before subset optimisation) is future work.

## Consumers

The `actor_name_harmonised.csv` output of `name_normaliser.py` is read by
`04_harmonisation_and_evaluation/03_ready_dataset_assembly/assemble_actors_ready.py`
(`--actor-name-harmonised`) to fill `actor_name` when empty in the
actors-ready dataset (`bnf_actors_ready.csv`), which module 5's
`gen_subset_optm.py` then reads in turn.

## Monitoring

`name_normaliser.py` and `actors_deduplication.py` use the same "embedded
state-based monitoring" mechanism as module 1 (`query_agents.R` /
`query_editions.R`) and the `06_mapping` scripts — see
`00_monitor/README.md`. `name_normaliser.py` writes one checkpoint per
processed actor; `actors_deduplication.py` writes one checkpoint per
processed name-group (only groups with more than one actor). Both write a
final checkpoint on completion, on by default from the CLI (`--no-monitor`
to disable). Reports land in
`00_monitor/report/name_normaliser_<timestamp>_py.txt` and
`00_monitor/report/actors_deduplication_<timestamp>_py.txt` respectively.
