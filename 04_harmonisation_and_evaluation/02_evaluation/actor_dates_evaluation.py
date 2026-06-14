"""
actor_dates_evaluation.py

Evaluator for the actor_birth, actor_death, actor_start, actor_end fields.

Produces a mapping between original raw values and the corrected/harmonised
form output by the dates_normaliser (01_harmonisation/actor_dates/).

Inherits from the Evaluation base class and adapts it to date-specific
validation logic:
  - Verifies that harmonised values conform to EDTF format.
  - Reports which raw values were approximate, uncertain, range-typed, etc.
  - Flags values that remain non-parseable after harmonisation.

Output files (in output_reports/):
    actor_dates_summary.csv     — aggregate statistics per correction category
    actor_dates_warnings.csv    — values that raised warnings (ambiguous dates)
    actor_dates_errors.csv      — original → harmonised mapping for error cases

[TODO] This evaluator is a placeholder. The evaluate_value() method needs
       to be implemented once the dates_normaliser.py output schema is finalised.
"""

from typing import Optional, Tuple, List, Dict
import re

from .evaluation_base import Evaluation


class ActorDatesEvaluation(Evaluation):
    """
    Evaluator for actor date fields (birth, death, start, end).

    Reads a CSV/ZIP containing the output of dates_normaliser.py and evaluates
    whether each harmonised date is a valid EDTF string, flagging residual
    anomalies for further review.
    """

    # EDTF approximate / uncertain markers
    EDTF_MARKERS = re.compile(r"[~?%]")
    # Basic EDTF year pattern: YYYY, YYYY~, YYYY?, YYYY~?, YYYYXX, YYYY/YYYY
    EDTF_YEAR_RE = re.compile(
        r"^-?\d{4}[X~?%]?"              # simple year, possibly with qualifier
        r"(?:/(?:-?\d{4}[X~?%]?))?$"    # optional / range
    )

    def __init__(
        self,
        csv_filepath: str,
        field_name: str = "date_harmonised",
        config_path: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        csv_filepath : str
            Path to the harmonised dates CSV (output of dates_normaliser.py).
        field_name : str
            Column to validate (default: 'date_harmonised').
        config_path : str, optional
            Path to a JSON config file. If None, uses a minimal inline config.
        """
        if config_path is None:
            # Minimal inline config — extend with a full JSON config once
            # the normaliser output schema is finalised.
            config = {
                "field": field_name,
                "warning": [
                    "approximate_date",
                    "uncertain_date",
                    "century_level",
                    "decade_level",
                    "date_range",
                ],
                "error": [
                    "non_edtf_format",
                    "missing_value",
                    "non_parseable",
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
        Validate a single harmonised date value.

        Returns
        -------
        warnings : list of str
            Labels for non-critical issues (approximate, uncertain, range).
        errors : dict { label: substitution_value }
            Labels for critical issues, with the suggested corrected value
            (empty string if no automatic correction is possible).
        """
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        if value is None or str(value).strip() == "":
            errors["missing_value"] = ""
            return warnings, errors

        stripped = str(value).strip()

        # --- Check for EDTF qualifier markers (warnings, not errors) ---
        if "~" in stripped:
            warnings.append("approximate_date")
        if "?" in stripped:
            warnings.append("uncertain_date")
        if "/" in stripped:
            warnings.append("date_range")
        if re.search(r"\bXX\b|X{2}", stripped):
            warnings.append("century_level")

        # --- Check for non-parseable residuals ---
        # [TODO] Implement full EDTF validation once normaliser schema is stable.
        # For now: flag values that don't match the basic EDTF year pattern.
        if not self.EDTF_YEAR_RE.match(stripped):
            errors["non_edtf_format"] = ""

        return warnings, errors
