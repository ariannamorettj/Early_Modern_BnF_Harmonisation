#!/usr/bin/env python3
"""
llm_publisher_normaliser.py  [PLACEHOLDER / TODO]

Task: Use an LLM to resolve ambiguous publisher names that the heuristic
      approach could not confidently normalise.

Context:
---------
After running the heuristic publisher_normaliser.py, a subset of publishers
will remain unresolved due to:
  - Highly abbreviated names with no known expansion in the lookup dict.
  - Complex concatenated entries (multiple publishers, notes mixed in).
  - Very rare publisher names not covered by the canonical name dictionary.

An LLM is used to:
  1. Identify the publisher name(s) in the raw string.
  2. Suggest the canonical or expanded form.
  3. Flag cases that cannot be resolved (e.g. truly anonymous publications).

TODO:
-----
- Design prompt template for publisher name resolution.
- Implement LLM API call with response parsing.
- Implement caching in llm_responses_cache/.
- Merge with heuristic output.

Output: publisher_harmonised_llm.csv
    edition_uri | publisher_original | publisher_harmonised | correction_type | confidence | llm_explanation
"""

# TODO: implement LLM publisher normalisation

def run(heuristic_output_csv: str, output_dir: str) -> None:
    """[TODO]"""
    raise NotImplementedError("TODO: implement LLM publisher run()")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM publisher normaliser [TODO]")
    parser.add_argument("--heuristic-output", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.heuristic_output, args.output)
