#!/usr/bin/env python3
"""
name_normaliser.py  [PLACEHOLDER / TODO]

Task: Apply heuristic rule-based normalisation to the actor_name,
      actor_first_name, and actor_last_name fields.

Context (from 03_analysis findings):
--------------------------------------
The name fields exhibit the following categories of anomalies that need
to be resolved before the graph materialisation phase:

  1. Structural noise:
     - Initials only (e.g. "M D", "G.")
     - Dotted initials sequences (e.g. "M. B. L.")
     - Undefined / undeciphered characters (e.g. "Jean ...")

  2. Embedded metadata mixed into the name string:
     - Titles / roles: "Veuve de", "Sieur de", "Abbé", "Chevalier"
     - Roman numerals: "Julien I", "Louis XIV"
     - Alternative names / aliases: "dit le", "detto il", "alias"

  3. Multi-value concatenation:
     - Multiple actors in a single cell separated by conjunctions
       (e.g. "Pietro and Giovanni")
     - Partial multi-values (conjunction at end: "Martinus Et")

  4. Formatting / encoding errors:
     - Wrapping brackets and separators (e.g. "[Dumas]", "(Voltaire)")
     - Non-alphanumeric characters (e.g. "/" as separator)
     - Null markers ("***", "null", "nan")

Implementation Plan:
---------------------
For each row in the input dataset:
  1. Load the raw value from the target column.
  2. Apply rules in priority order (errors first, then normalisation):
     a. Strip null markers → mark as MISSING
     b. Strip wrapping brackets/separators → extract inner value
     c. Split multi-value entries → flag for manual review or split
     d. Remove embedded titles/roles → extract clean name
     e. Handle initials → flag or expand using lookup dict
  3. Write corrected value and correction metadata to output CSV.

TODO:
-----
- Implement the normalisation pipeline (steps 1–5 above).
- Build or load name_correction_dict.json for known corrections.
- Connect to output format expected by 02_evaluation/actor_name_evaluation.py.

Input:
    A CSV or ZIP file containing actor_data with columns:
    actor, actor_name, actor_first_name, actor_last_name

Output (actor_name_harmonised.csv):
    actor_uri | actor_name_original | actor_name_harmonised | correction_type | confidence

Usage (once implemented):
    python name_normaliser.py --input <path_to_actor_data.zip> --output <output_dir>
"""

# TODO: implement normalisation pipeline


def normalise_name(raw_value: str) -> dict:
    """
    [TODO] Apply all heuristic rules to a single name value.

    Returns a dict with keys:
        - harmonised: str (corrected value)
        - correction_type: str (label of applied rule, or 'none')
        - confidence: str ('high', 'medium', 'low')
    """
    raise NotImplementedError("TODO: implement name normalisation rules")


def run(input_path: str, field_name: str, output_dir: str) -> None:
    """
    [TODO] Load the input CSV/ZIP, apply normalise_name() to each row,
    and write the output mapping CSV.
    """
    raise NotImplementedError("TODO: implement run()")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Heuristic-rule name normaliser [TODO]")
    parser.add_argument("--input", required=True, help="Path to actor CSV or ZIP")
    parser.add_argument("--field", default="actor_name", help="Column to normalise")
    parser.add_argument("--output", default=".", help="Output directory")
    args = parser.parse_args()
    run(args.input, args.field, args.output)
