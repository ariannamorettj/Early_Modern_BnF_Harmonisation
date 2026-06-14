"""
publisher_evaluation.py

Evaluator for the publisher_1 field of the bnf_edition_data dataset.

Reads the harmonised publisher data produced by the publisher_normaliser
(01_harmonisation/publisher/) and evaluates:
  - Whether the normalised publisher name is a valid non-empty string.
  - Whether the value was classified as 'sine nomine' (no publisher).
  - Whether abbreviations were successfully expanded.
  - Whether multi-publisher cells were correctly split.
  - Whether embedded location information was stripped.

The harmonised data schema (from publisher_normaliser.py):
    edition_uri | publisher_original | publisher_harmonised | correction_type | confidence

Output files (in output_reports/):
    publisher_summary.csv
    publisher_warnings.csv
    publisher_errors.csv

[TODO] The evaluate_value() method is a skeleton. Full validation requires
       the publisher_normaliser.py to be implemented and the lookup
       dictionaries to be built.
"""

from typing import Optional, Tuple, List, Dict
import re

from .evaluation_base import Evaluation


# Patterns indicating 'sine nomine' (anonymous/no-publisher records)
SINE_NOMINE_PATTERNS = re.compile(
    r"\b(s\.?\s?n\.?|sine\s+nomine|sans\s+nom|ohne\s+verlag|senza\s+nome|without\s+publisher)\b",
    re.IGNORECASE,
)

# Abbreviation patterns that should have been expanded
ABBREVIATION_RE = re.compile(r"\b(Impr\.|Lib\.|Éd\.|Ed\.)\b")


class PublisherEvaluation(Evaluation):
    """
    Evaluator for the harmonised publisher_1 field.
    """

    def __init__(
        self,
        csv_filepath: str,
        field_name: str = "publisher_harmonised",
        config_path: Optional[str] = None,
    ):
        if config_path is None:
            config = {
                "field": field_name,
                "warning": [
                    "sine_nomine",
                    "residual_abbreviation",
                    "residual_location_in_name",
                    "low_confidence_correction",
                ],
                "error": [
                    "missing_value",
                    "multi_value_not_split",
                    "non_alphanumeric_noise",
                ],
            }
        else:
            import json
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

        super().__init__(config, csv_filepath, field_name=field_name)

    def evaluate_value(
        self, value: Optional[str]
    ) -> Tuple[List[str], Dict[str, str]]:
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        if value is None or str(value).strip() == "":
            errors["missing_value"] = ""
            return warnings, errors

        stripped = str(value).strip()

        # Check for sine nomine
        if SINE_NOMINE_PATTERNS.search(stripped):
            warnings.append("sine_nomine")

        # Check for residual unexpanded abbreviations
        if ABBREVIATION_RE.search(stripped):
            warnings.append("residual_abbreviation")

        # Check for residual location information in parentheses
        if re.search(r"\([A-Z][a-z]+\)", stripped):
            warnings.append("residual_location_in_name")

        # Check for multi-value not split (semicolon or 'et'/'and' patterns)
        if ";" in stripped:
            errors["multi_value_not_split"] = ""

        # Check for non-alphanumeric noise (excluding common punctuation)
        if re.search(r"[^\w\s\.\,\-\'\(\)&]", stripped):
            errors["non_alphanumeric_noise"] = ""

        return warnings, errors
