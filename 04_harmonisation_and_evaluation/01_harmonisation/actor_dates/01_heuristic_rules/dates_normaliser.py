#!/usr/bin/env python3
"""
dates_normaliser.py  [PLACEHOLDER / TODO]

Task: Harmonise the actor_birth, actor_death, actor_start, actor_end fields
      of the actor_data dataset.

Context (from 03_analysis findings):
--------------------------------------
Date fields in the actor dataset exhibit high variation, unlike the edition
date fields (year_first, year_range) which are already normalised.
Actor date fields may contain:

  - Approximate dates with qualifiers:
      "ca. 1750", "vers 1720", "around 1800", "circa 1650"
      "ante 1700", "post 1800", "avant 1600", "après 1700"

  - Century-level expressions:
      "18th century", "XVIIIe siècle", "18. Jahrhundert"
      "début XIXe", "fin XVIIe"

  - Decade-level expressions:
      "1750s", "années 1750"

  - Uncertain / qualified:
      "1750?", "[1750]", "(1750)", "1750 environ"

  - Ranges:
      "1750-1800", "1750/1800"

  - Non-parseable or missing:
      "actif au XVIIIe", "flourished c.1700", "***", empty strings

Target output format: ISO 8601 extended / EDTF (Extended Date/Time Format)
  - "1750" → exact year
  - "1750~" → approximate year (EDTF)
  - "1750?" → uncertain year (EDTF)
  - "1700/1800" → range
  - "17XX" → decade/century expressed as partial date

Implementation Plan:
---------------------
  1. Apply regex patterns to detect and classify the date format.
  2. Extract the numeric year(s) from each format.
  3. Map qualifiers (ca., vers, ante, post, ?) to EDTF modifiers.
  4. Produce a normalised EDTF string.
  5. For cases that cannot be parsed deterministically → flag for LLM review.

TODO:
-----
- Implement regex detection patterns for each date format category.
- Build EDTF converter for each category.
- Decide on handling of entirely non-parseable strings (discard / LLM / flag).
- Connect output to 02_evaluation/actor_dates_evaluation.py.

Input columns: actor_birth, actor_death, actor_start, actor_end
Output (actor_dates_harmonised.csv):
    actor_uri | field | date_original | date_harmonised | date_format_detected | confidence
"""

# TODO: implement date normalisation pipeline


def detect_date_format(raw_value: str) -> str:
    """
    [TODO] Classify the raw date string into a format category.
    Returns one of: 'exact_year', 'approximate', 'uncertain', 'century',
                    'decade', 'range', 'qualified_activity', 'non_parseable'
    """
    raise NotImplementedError("TODO: implement date format detection")


def normalise_date(raw_value: str) -> dict:
    """
    [TODO] Convert raw date string to EDTF format.
    Returns: { 'harmonised': str, 'format_detected': str, 'confidence': str }
    """
    raise NotImplementedError("TODO: implement date normalisation")


def run(input_path: str, output_dir: str) -> None:
    """[TODO] Run full normalisation on input CSV/ZIP."""
    raise NotImplementedError("TODO: implement run()")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Heuristic date normaliser [TODO]")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.input, args.output)
