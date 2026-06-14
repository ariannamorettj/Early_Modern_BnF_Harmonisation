#!/usr/bin/env python3
"""
publisher_normaliser.py  [PLACEHOLDER / TODO]

Task: Harmonise the publisher_1 field of the bnf_edition_data dataset.

Context (from 03_analysis findings):
--------------------------------------
publisher_1 is a free-text field containing the name of the publisher as it
appears in the bibliographic record. Unlike publisher_2 (which is a clean URI),
publisher_1 is a raw string with significant variation:

  - Orthographic variants of the same publisher name:
      "Imprimerie royale", "Impr. royale", "Impr. Royale"
      "Baudouin frères", "Baudouin Frères", "Baudouin et frères"

  - Abbreviations and partial names:
      "Impr.", "Lib.", "s.n." (sine nomine — no publisher identified)

  - Embedded location information:
      "Chaignieau aîné (Paris)", "Renard, Bordeaux"

  - Period / century spans embedded:
      "J. Smith [1750-1780]"

  - Multiple publishers concatenated:
      "Baudouin et Renard", "Smith ; Jones"

  - Non-publisher content (notes, printing descriptions)

Implementation Plan:
---------------------
  1. Detect and normalise known abbreviations via lookup dict.
  2. Strip embedded location information (city/country in parentheses).
  3. Detect and flag multi-publisher cells for splitting.
  4. Identify "sine nomine" and other null-equivalent patterns.
  5. Apply fuzzy string matching (e.g. RapidFuzz) to cluster orthographic
     variants into canonical publisher names.
  6. Produce a canonical publisher name and a confidence score.

TODO:
-----
- Build publisher_abbreviations.json (e.g. "Impr." → "Imprimerie").
- Build publisher_canonical_names.json (known variant → canonical form).
- Implement fuzzy clustering step.
- Connect to 02_evaluation/publisher_evaluation.py.

Input column: publisher_1
Output (publisher_harmonised.csv):
    edition_uri | publisher_original | publisher_harmonised | correction_type | confidence
"""

# TODO: implement publisher normalisation

def normalise_publisher(raw_value: str) -> dict:
    """
    [TODO] Apply normalisation rules to a single publisher string.
    Returns: { 'harmonised': str, 'correction_type': str, 'confidence': str }
    """
    raise NotImplementedError("TODO: implement publisher normalisation")

def run(input_path: str, output_dir: str) -> None:
    """[TODO] Run full normalisation on input CSV/ZIP."""
    raise NotImplementedError("TODO: implement run()")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Publisher normaliser [TODO]")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.input, args.output)
