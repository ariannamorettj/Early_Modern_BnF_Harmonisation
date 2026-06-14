"""
language_evaluation.py

Evaluator for the language field of the bnf_edition_data dataset.

Reads the harmonised language data produced by the language_normaliser
(01_harmonisation/language/) and evaluates:
  - Whether the normalised value is a valid ISO 639-2 three-letter code.
  - Whether multi-language expressions were correctly split or handled.
  - Whether dialectal/archaic language values were mapped to a valid code.
  - Whether unknown language values remain unresolved.

The harmonised data schema (from language_normaliser.py):
    edition_uri | language_original | language_harmonised | correction_type | confidence

Output files (in output_reports/):
    language_summary.csv
    language_warnings.csv
    language_errors.csv

[TODO] The evaluate_value() method uses a hard-coded set of known ISO 639-2
       codes as a quick validation check. Replace with a full ISO 639-2 lookup
       once the language_lookup.json dictionary is finalised.
"""

from typing import Optional, Tuple, List, Dict
import re

from .evaluation_base import Evaluation


# Subset of ISO 639-2 bibliographic codes most relevant to BnF data
# [TODO] Replace with full ISO 639-2 table loaded from a JSON file
KNOWN_ISO_639_2 = {
    "fre", "lat", "ita", "spa", "eng", "ger", "dut", "por",
    "grc", "heb", "ara", "rus", "pol", "swe", "dan", "nor",
    "gla", "wel", "bre", "oci", "pro", "fro", "frm",  # Old/Middle French, Occitan
    "cat", "baq", "cor", "glg", "hun", "cze", "slo",
    "und",  # undetermined
    "mul",  # multiple languages
    "zxx",  # no linguistic content
}


class LanguageEvaluation(Evaluation):
    """
    Evaluator for the harmonised language field.

    Validates that each harmonised value is a known ISO 639-2 code and flags
    residual raw strings that were not successfully normalised.
    """

    ISO_CODE_RE = re.compile(r"^[a-z]{3}$")

    def __init__(
        self,
        csv_filepath: str,
        field_name: str = "language_harmonised",
        config_path: Optional[str] = None,
    ):
        if config_path is None:
            config = {
                "field": field_name,
                "warning": [
                    "multi_language_value",
                    "archaic_or_dialectal_language",
                    "low_confidence_mapping",
                ],
                "error": [
                    "not_iso_639_2_format",
                    "unknown_iso_code",
                    "missing_value",
                    "non_parseable_language",
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

        stripped = str(value).strip().lower()

        # Check for multi-language (comma or semicolon separated)
        if ";" in stripped or "," in stripped:
            warnings.append("multi_language_value")
            return warnings, errors

        # Check format: must be exactly 3 lowercase letters
        if not self.ISO_CODE_RE.match(stripped):
            errors["not_iso_639_2_format"] = ""
            return warnings, errors

        # Check against known code set
        if stripped not in KNOWN_ISO_639_2:
            # Could be a valid but uncommon ISO 639-2 code
            warnings.append("low_confidence_mapping")

        # Detect archaic / dialectal codes
        if stripped in {"fro", "frm", "pro", "oci"}:
            warnings.append("archaic_or_dialectal_language")

        return warnings, errors
