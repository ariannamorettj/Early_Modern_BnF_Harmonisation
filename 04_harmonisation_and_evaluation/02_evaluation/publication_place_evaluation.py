"""
publication_place_evaluation.py

Evaluator for the publication_place field (and related place_original field)
of the bnf_edition_data dataset.

Reads the harmonised publication place data produced by the TGN-lookup approach
(01_harmonisation/publication_place/02_tgn_lookup/) and evaluates:
  - Whether a TGN ID was successfully assigned.
  - Whether the normalised city and country names are non-empty.
  - Whether uncertainty markers (brackets, question marks, parentheses) were
    correctly preserved in the boolean columns.
  - Whether coordinates (longitude, latitude) are within valid geographic ranges.

The harmonised data schema (from the existing Readme.MD in places/):
    edition | place_original | tgn_id | publication_place | publication_country
    | longitude | latitude | uncertainty_expressions_brackets
    | uncertainty_expressions_question_mark | uncertainty_expressions_parentheses

Output files (in output_reports/):
    publication_place_summary.csv
    publication_place_warnings.csv
    publication_place_errors.csv

[TODO] The evaluate_value() method is partially implemented. Full validation
       requires the final harmonised CSV to be loaded and cross-validated
       against the TGN dataset.
"""

from typing import Optional, Tuple, List, Dict
import re

from .evaluation_base import Evaluation


class PublicationPlaceEvaluation(Evaluation):
    """
    Evaluator for the harmonised publication_place field.

    Validates the output of bnf_place_harmonisation.py / .R against the
    expected schema and flags missing TGN IDs, empty normalised values,
    and coordinate range violations.
    """

    # Valid longitude range: -180 to 180
    # Valid latitude range: -90 to 90
    LON_RE = re.compile(r"^-?(1[0-7]\d|\d{1,2})(\.\d+)?$")
    LAT_RE = re.compile(r"^-?([0-8]\d|\d)(\.\d+)?$")

    def __init__(
        self,
        csv_filepath: str,
        field_name: str = "publication_place",
        config_path: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        csv_filepath : str
            Path to the harmonised publication place CSV (bnf_publication_place.csv).
        field_name : str
            Primary field to evaluate (default: 'publication_place').
        config_path : str, optional
            Path to a JSON config. If None, uses minimal inline config.
        """
        if config_path is None:
            config = {
                "field": field_name,
                "warning": [
                    "uncertainty_bracket",
                    "uncertainty_question_mark",
                    "uncertainty_parentheses",
                    "missing_coordinates",
                ],
                "error": [
                    "missing_tgn_id",
                    "missing_publication_place",
                    "missing_publication_country",
                    "missing_value",
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
        """
        Evaluate a single harmonised publication_place value.

        Note: For full row-level validation (checking tgn_id, country,
        coordinates alongside the city name), override run() to pass
        additional columns to evaluate_value(). This basic implementation
        validates only the field value itself.
        """
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        if value is None or str(value).strip() == "":
            errors["missing_publication_place"] = ""
            return warnings, errors

        stripped = str(value).strip()

        # Detect residual uncertainty markers in the harmonised name
        # (these should have been extracted to boolean columns by the harmoniser)
        if "[" in stripped or "]" in stripped:
            warnings.append("uncertainty_bracket")
        if "?" in stripped:
            warnings.append("uncertainty_question_mark")
        if "(" in stripped or ")" in stripped:
            warnings.append("uncertainty_parentheses")

        return warnings, errors
