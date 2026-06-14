# actor_name — LLM-Based Approach

This folder implements a large-language-model-assisted harmonisation approach for the `actor_name`, `actor_first_name`, and `actor_last_name` fields.

## Rationale

Some name anomalies are too ambiguous for deterministic rule-based resolution:
- Distinguishing between a personal alias and a genuine alternate name entry
- Expanding abbreviated names when context is required
- Splitting multi-value cells when conjunction-based splitting is insufficient
- Resolving unclear cases where titles and name components are intertwined

For these cases, an LLM (e.g. GPT-4o, Claude) can be queried to produce a corrected value with an explanation, which is then post-validated.

## Approach

1. **Pre-filter**: Run the heuristic evaluation (`02_evaluation/actor_name_evaluation.py`) to identify rows flagged as `medium` or `low` confidence corrections, or rows where no rule could fire.
2. **Prompt construction**: For each ambiguous row, build a structured prompt including the raw value, detected warning/error labels, and surrounding context (actor URI, dataset year).
3. **LLM inference**: Call the LLM API and parse the structured JSON response.
4. **Post-validation**: Apply a lightweight regex check on the LLM output to catch obvious failures.
5. **Output**: Same output schema as the heuristic approach (`actor_name_harmonised.csv`).

## Files

| File | Description |
|------|-------------|
| `llm_name_normaliser.py` | **[TODO]** Main script: filters ambiguous rows, calls LLM, writes corrected output. |
| `prompt_templates.py` | **[TODO]** Prompt templates for each name field (`actor_name`, `actor_first_name`, `actor_last_name`). |
| `llm_responses_cache/` | **[TODO]** Directory to cache raw LLM responses (JSON) to avoid re-querying. |

## Expected Output

Same schema as `01_heuristic_rules`:
- `actor_uri`
- `actor_name_original`
- `actor_name_harmonised`
- `correction_type` → will be `llm_correction`
- `confidence` → derived from LLM self-reported confidence or manual review flag
- `llm_explanation` — additional column with the LLM's textual justification
