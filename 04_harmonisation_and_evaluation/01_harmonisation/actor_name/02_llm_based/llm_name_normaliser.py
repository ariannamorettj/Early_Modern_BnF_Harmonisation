#!/usr/bin/env python3
"""
llm_name_normaliser.py  [PLACEHOLDER / TODO]

Task: Use an LLM to harmonise actor_name, actor_first_name, actor_last_name
      for rows that the heuristic approach could not confidently resolve.

Context:
---------
After running 01_heuristic_rules/name_normaliser.py and the corresponding
evaluator (02_evaluation/actor_name_evaluation.py), a subset of rows will
remain with:
  - confidence = 'low' (heuristic rule fired but result is uncertain)
  - correction_type = 'flagged_for_review' (no rule matched)

This script targets those residual rows.

Approach:
---------
  1. Load the harmonisation output from the heuristic stage.
  2. Filter rows with confidence != 'high'.
  3. Build a structured prompt for each row (see prompt_templates.py).
  4. Call the configured LLM API (OpenAI / Anthropic / local).
  5. Parse the JSON response: { "harmonised": str, "confidence": str, "explanation": str }
  6. Post-validate the LLM output with a lightweight check.
  7. Write the final output CSV.

TODO:
-----
- Choose and configure LLM client (OpenAI, Anthropic, Ollama, etc.)
- Implement prompt construction in prompt_templates.py
- Implement response parser and post-validator
- Implement response caching in llm_responses_cache/
- Handle rate limits and retry logic

Output (actor_name_harmonised_llm.csv):
    actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence | llm_explanation
"""

# TODO: implement LLM-based normalisation


def call_llm(prompt: str) -> dict:
    """
    [TODO] Call the LLM API with the given prompt and return a parsed response dict.
    Expected response format: { "harmonised": str, "confidence": str, "explanation": str }
    """
    raise NotImplementedError("TODO: implement LLM API call")


def run(heuristic_output_csv: str, output_dir: str) -> None:
    """
    [TODO] Load heuristic output, filter low-confidence rows,
    apply LLM corrections, and write the merged output.
    """
    raise NotImplementedError("TODO: implement LLM normalisation run()")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-based name normaliser [TODO]")
    parser.add_argument("--heuristic-output", required=True,
                        help="Path to CSV output from the heuristic normaliser")
    parser.add_argument("--output", default=".", help="Output directory")
    args = parser.parse_args()
    run(args.heuristic_output, args.output)
