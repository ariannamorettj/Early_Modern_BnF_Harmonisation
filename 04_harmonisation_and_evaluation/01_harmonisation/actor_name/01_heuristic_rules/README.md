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
| `actors_deduplication.py` | **[PLACEHOLDER]** Implements deduplication logic: merges rows referring to the same actor based on ID and name matching results. |
| `name_normaliser.py` | **[TODO]** Main normalisation script: applies regex cleaning, particle handling, bracket stripping, and alias detection to produce a corrected `actor_name` value. |
| `name_correction_dict.json` | **[TODO]** JSON lookup dictionary mapping known erroneous name strings to their corrected form. |

## Expected Output

A CSV with columns:
- `actor_uri` — original BnF actor URI
- `actor_name_original` — original raw value
- `actor_name_harmonised` — corrected value after rule application
- `correction_type` — label of the rule that triggered the correction (e.g., `strip_brackets`, `remove_title`, `alias_split`)
- `confidence` — `high` / `medium` / `low` depending on rule certainty
