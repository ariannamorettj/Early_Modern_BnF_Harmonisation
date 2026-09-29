"""
publication_place_evaluation.py

Evaluator for the publication_place field (and related columns) produced by
bnf_place_harmonisation.py (01_harmonisation/publication_place/02_tgn_lookup/).

IMPORTANT — this supersedes the placeholder single-field check originally
here. That check validated `publication_place` in isolation and referenced
column names (`uncertainty_expressions_brackets` etc.) that do not match the
real harmoniser's output — verified against bnf_place_harmonisation.py's own
OUTPUT_FIELDS this session:

    edition | place_original | place_uncertainty_brackets
    | place_uncertainty_parentheses | place_uncertainty_question_marks
    | tgn_id | publication_place | publication_country | longitude | latitude

This evaluator now uses `row` (the full CSV row, see evaluation_base.py's
`Evaluation.evaluate_value` contract) to validate the row AS A WHOLE — tgn_id,
coordinates, city and country together, as the module's own architectural
note originally asked for — rather than the harmonised city name alone:

  - a record with NO raw place at all is not an anomaly (missing_value,
    informational only, not really "wrong")
  - a record whose raw place resolved to NOTHING is the harmoniser's own
    documented "unmatched" outcome (unmatched_place, a warning -- expected
    to happen, worth surfacing, not a defect)
  - publication_place set without a tgn_id, or without a publication_country,
    is a genuine CONTRACT VIOLATION: bnf_place_harmonisation.py's own logic
    always sets city/tgn_id/country together from the same TGN-table lookup
    (see that script's `run()`), so this combination should never occur on
    a correctly-behaving harmoniser run -- these are true integrity checks,
    not speculative ones.
  - coordinates, when present, must be valid latitude/longitude numbers.

Known, accepted limitation: the uncertainty boolean columns
(place_uncertainty_brackets/parentheses/question_marks) are computed by
bnf_place_harmonisation.py from the CITY portion only, AFTER
str_after_last_parentheses() has already split off the country -- re-deriving
that split here to fully cross-validate the flag columns against the raw
place_original would mean duplicating that parsing logic. Not attempted here;
what IS checked is simpler and still real: a literal bracket/parenthesis/
question-mark character surviving INSIDE the harmonised publication_place
string is always a defect (harmonise_city_string() should have stripped it),
independent of what the flag columns say.

Output files (in output_reports/):
    publication_place_summary.csv
    publication_place_warnings.csv
    publication_place_errors.csv
"""

from typing import Optional, Tuple, List, Dict

from .evaluation_base import Evaluation


def _parse_in_range(value: str, lo: float, hi: float) -> Optional[bool]:
    """None if `value` isn't parseable as a float; else whether lo <= value <= hi."""
    try:
        return lo <= float(value) <= hi
    except (TypeError, ValueError):
        return None


class PublicationPlaceEvaluation(Evaluation):
    """
    Evaluator for the harmonised publication_place field and its sibling
    columns (tgn_id, publication_country, longitude, latitude, uncertainty
    flags), validated together as one row.
    """

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
                    "unmatched_place",
                    "missing_coordinates",
                ],
                "error": [
                    "missing_value",
                    "missing_tgn_id",
                    "missing_publication_country",
                    "invalid_coordinates",
                    "residual_bracket_in_harmonised",
                    "residual_parenthesis_in_harmonised",
                    "residual_question_mark_in_harmonised",
                ],
            }
        else:
            import json
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

        super().__init__(config, csv_filepath, field_name=field_name)

    def evaluate_value(
        self, value: Optional[str], row: Optional[Dict[str, str]] = None
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Evaluate one harmonised publication_place row as a whole. `value` is
        `publication_place` (per evaluation_base.py's single-column
        extraction); `row` carries the sibling columns this check needs.

        Without `row` (e.g. a caller evaluating publication_place in
        isolation), falls back to the residual-character checks only --
        the tgn_id/coordinates/country cross-checks need the full row.
        """
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        place = (value or "").strip()
        row = row or {}
        place_original = row.get("place_original", "").strip()
        tgn_id = row.get("tgn_id", "").strip()
        country = row.get("publication_country", "").strip()
        longitude = row.get("longitude", "").strip()
        latitude = row.get("latitude", "").strip()

        if not place and not country:
            if place_original:
                # Raw value existed; TGN lookup and country fallback both
                # failed -- bnf_place_harmonisation.py's own "unmatched"
                # outcome (see its report.json stats), not a QA defect.
                warnings.append("unmatched_place")
            else:
                errors["missing_value"] = ""
            return warnings, errors

        if place:
            if not tgn_id:
                errors["missing_tgn_id"] = ""
            if not country:
                errors["missing_publication_country"] = ""

            if "[" in place or "]" in place:
                errors["residual_bracket_in_harmonised"] = ""
            if "(" in place or ")" in place:
                errors["residual_parenthesis_in_harmonised"] = ""
            if "?" in place:
                errors["residual_question_mark_in_harmonised"] = ""

        if tgn_id:
            if not longitude or not latitude:
                warnings.append("missing_coordinates")
            else:
                lon_ok = _parse_in_range(longitude, -180.0, 180.0)
                lat_ok = _parse_in_range(latitude, -90.0, 90.0)
                if lon_ok is False or lon_ok is None or lat_ok is False or lat_ok is None:
                    errors["invalid_coordinates"] = ""

        return warnings, errors
