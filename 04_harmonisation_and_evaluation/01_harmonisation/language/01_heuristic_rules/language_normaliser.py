#!/usr/bin/env python3
"""
language_normaliser.py  [PLACEHOLDER / TODO]

Task: Harmonise the language field of the bnf_edition_data dataset.

Context (from 03_analysis findings):
--------------------------------------
The language field contains the language of publication of bibliographic
editions. Unlike URI-based fields, this is a string field with variation:

  - Free-text language names in multiple languages:
      "français", "latin", "French", "Latein", "italiano"
      "grec", "greek", "Griechisch"

  - ISO 639 codes (some already present):
      "fre", "lat", "ita", "grc" (ISO 639-2)
      "fr", "la", "it" (ISO 639-1)

  - Mixed expressions:
      "Latin et français", "français et latin"
      "en français et en latin"

  - Unclear or archaic language names:
      "vieux français", "moyen français", "occitan"
      "dialecte provençal", "picard"

  - Encoding errors or placeholders:
      "???", "inconnu", "unknown", empty strings

Target output format: ISO 639-2 three-letter language codes (BnF standard)
  - "français" → "fre"
  - "Latin" → "lat"
  - "greek" → "grc"
  - "vieux français" → "fro" (Old French)
  - "occitan" → "oci"

Implementation Plan:
---------------------
  1. Build a lookup dict mapping raw language strings → ISO 639-2 codes,
     covering the most frequent values (from 03_analysis top-10 profiling).
  2. Apply the lookup (case-insensitive, stripped).
  3. Detect multi-language expressions and split if possible.
  4. Flag non-mappable strings for LLM or manual review.

TODO:
-----
- Build language_lookup.json (raw string → ISO 639-2 code).
- Implement multi-language split detection.
- Handle dialect / archaic form mapping.
- Connect to 02_evaluation/language_evaluation.py.

Input column: language
Output (language_harmonised.csv):
    edition_uri | language_original | language_harmonised | correction_type | confidence
"""

# TODO: implement language normalisation

def normalise_language(raw_value: str) -> dict:
    """
    [TODO] Map raw language string to ISO 639-2 code.
    Returns: { 'harmonised': str, 'correction_type': str, 'confidence': str }
    """
    raise NotImplementedError("TODO: implement language normalisation")

def run(input_path: str, output_dir: str) -> None:
    """[TODO] Run full normalisation on input CSV/ZIP."""
    raise NotImplementedError("TODO: implement run()")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Language normaliser [TODO]")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.input, args.output)
