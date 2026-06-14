#!/usr/bin/env python3
"""
external_links_normaliser.py  [PLACEHOLDER / TODO]

Task: Harmonise the actor_link_close and actor_link_exact fields of the
      actor_data dataset.

Context (from 03_analysis findings):
--------------------------------------
External link fields contain URIs pointing to external authority records
(VIAF, Wikidata, DBpedia, ISNI, LC Name Authority, etc.).
Anomalies may include:

  - Mixed URI formats for the same authority:
      "http://viaf.org/viaf/12345" vs "https://viaf.org/viaf/12345"
      "http://www.viaf.org/viaf/12345" vs "http://viaf.org/viaf/12345"

  - Non-URI strings (free-text, local identifiers, partial paths)

  - Deprecated or redirect URIs (e.g. old VIAF clusters that have been merged)

  - Domain inconsistencies (www vs no-www, http vs https)

  - Multiple URIs concatenated in a single cell (semicolon or pipe separated)

Implementation Plan:
---------------------
  1. Parse each cell as a URI (using urllib.parse).
  2. Normalise scheme (http → https for known authorities).
  3. Normalise www-prefix variants (remove www. if authority is known).
  4. Detect and split multi-value cells.
  5. Flag non-URI values for manual review.
  6. Resolve known deprecated URI patterns via lookup table.

TODO:
-----
- Build lookup table of known URI pattern normalisations per authority.
- Implement URI parser and normaliser.
- Implement multi-value splitter.
- Connect to 02_evaluation/external_links_evaluation.py.

Input columns: actor_link_close, actor_link_exact
Output (external_links_harmonised.csv):
    actor_uri | field | link_original | link_harmonised | authority | correction_type | confidence
"""

# TODO: implement external links normalisation

def normalise_link(raw_value: str) -> dict:
    """
    [TODO] Normalise a single external link value.
    Returns: { 'harmonised': str, 'authority': str, 'correction_type': str, 'confidence': str }
    """
    raise NotImplementedError("TODO: implement link normalisation")

def run(input_path: str, output_dir: str) -> None:
    """[TODO] Run full normalisation on input CSV/ZIP."""
    raise NotImplementedError("TODO: implement run()")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="External links normaliser [TODO]")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=".")
    args = parser.parse_args()
    run(args.input, args.output)
