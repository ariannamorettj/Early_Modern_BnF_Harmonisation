#!/usr/bin/env python3
"""
llm_dates_normaliser.py  [PLACEHOLDER / TODO]

Task: Use an LLM to harmonise actor date fields for rows that the heuristic
      approach classified as 'non_parseable' or 'low' confidence.

Context:
---------
Some actor date values are expressed in free-text natural language
(e.g. "actif dans la seconde moitié du XVIIIe siècle", "flourished c.1650-1700")
and cannot be reliably mapped to EDTF by deterministic rules alone.

For these residual cases, an LLM is asked to:
  1. Identify the type of date expression.
  2. Extract the numeric year(s) or century.
  3. Apply EDTF modifiers for approximation/uncertainty.
  4. Return a structured JSON response.

TODO:
-----
- Implement prompt templates for date normalisation in prompt_templates.py.
- Implement call_llm() with chosen API client.
- Implement output merging with heuristic results.

Output: actor_dates_harmonised_llm.csv
    actor_uri | field | date_original | date_harmonised | date_format_detected | confidence | llm_explanation
"""

# TODO: implement LLM date normalisation

def run(heuristic_output_csv: str, output_dir: str) -> None:
    """[TODO]"""
    raise NotImplementedError("TODO: implement LLM dates run()")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM date normaliser [TODO]")
    parser.add_argument("--heuristic-output", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.heuristic_output, args.output)
