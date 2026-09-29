"""
actor_dates_evaluation.py

Evaluator for the actor_birth, actor_death, actor_start, actor_end fields.

Produces a mapping between original raw values and the corrected/harmonised
form output by dates_normaliser.py (01_harmonisation/actor_dates/01_heuristic_rules/),
optionally merged with llm_dates_normaliser.py's residual resolution.

IMPORTANT — this supersedes the placeholder EDTF check originally here. That
check (a single optional qualifier character after a bare 4-digit year) does
not match the *actual* shapes dates_normaliser.py produces — verified against
that script's own module docstring and OUTPUT_FIELDS this session:

    actor_uri | field | date_original | date_harmonised | date_format_detected | confidence

`date_harmonised` is always one of exactly four shapes, or empty:
    exact_year        "1750", "-0043"            (4-digit year, optional BCE '-')
    exact_date         "1594-06-14"                (year-month-day)
    year_month          "1564-04"                    (year-month)
    masked_precision    "17XX", "1XXX", "175X"       (1-3 known digits + 1-3 'X',
                                                      always summing to 4)
The previous regex matched NONE of exact_date/year_month, and only matched
masked_precision when exactly one 'X' trails a *4-digit* prefix — i.e. it
would have misclassified the large majority of real harmonised values as
non_edtf_format errors. See dates_normaliser.py's own module docstring for
the full category breakdown and the BCE-sign design decision (no
astronomical-year offset; kept here identically).

This evaluator also uses `row` (the full CSV row, see evaluation_base.py's
`Evaluation.evaluate_value` contract) to distinguish an EXPECTED empty
date_harmonised (date_format_detected == 'missing': the source had nothing
to convert, not a defect) from one that still needs attention
(date_format_detected == 'non_parseable': the heuristic step deliberately
left it unresolved — see dates_normaliser.py's module docstring — surfaced
here as a warning, not an error, since it is documented pending-review
behaviour, not a bug) from one that is genuinely wrong (empty for any other
reason).

Output files (in output_reports/):
    actor_dates_summary.csv     — aggregate statistics per correction category
    actor_dates_warnings.csv    — values that raised warnings (ambiguous dates)
    actor_dates_errors.csv      — original → harmonised mapping for error cases
"""

from typing import Optional, Tuple, List, Dict
import re

from .evaluation_base import Evaluation


class ActorDatesEvaluation(Evaluation):
    """
    Evaluator for actor date fields (birth, death, start, end).

    Reads a CSV/ZIP containing the output of dates_normaliser.py and evaluates
    whether each harmonised date matches one of the real EDTF shapes that
    normaliser produces, flagging residual anomalies for further review.
    """

    # The four shapes dates_normaliser.py actually emits (module docstring,
    # verified against a full-dataset run: 99.98% exact_year/exact_date/
    # year_month/masked_precision, the rest 'missing' or 'non_parseable').
    _SIGN = r"-?"
    EXACT_YEAR_RE = re.compile(rf"^{_SIGN}\d{{4}}$")
    EXACT_DATE_RE = re.compile(rf"^{_SIGN}\d{{4}}-\d{{2}}-\d{{2}}$")
    YEAR_MONTH_RE = re.compile(rf"^{_SIGN}\d{{4}}-\d{{2}}$")
    # 1-3 known digits + 1-3 'X' — validated to sum to 4 in _masked_precision_x_count().
    MASKED_PRECISION_RE = re.compile(rf"^{_SIGN}(\d{{1,3}})(X{{1,3}})$")

    # EDTF qualifiers this project's normaliser deliberately never emits (see
    # dates_normaliser.py's module docstring: masked precision maps to 'X',
    # not '~'/'?', and no range logic exists). Kept as defensive/forward-
    # compatible warnings -- seeing one on real data would flag a likely
    # regression, not a currently-expected case.
    RANGE_RE = re.compile(r"/")

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
            config = {
                "field": field_name,
                "warning": [
                    "approximate_date",
                    "uncertain_date",
                    "date_range",
                    "decade_level",
                    "century_level",
                    "millennium_level",
                    "unresolved_residual",
                ],
                "error": [
                    "non_edtf_format",
                    "missing_value",
                ],
            }
        else:
            import json
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

        super().__init__(config, csv_filepath, field_name=field_name)

    @classmethod
    def _masked_precision_x_count(cls, value: str) -> Optional[int]:
        """Number of trailing 'X' characters if `value` is a valid
        masked_precision shape (known digits + X's summing to 4), else None."""
        m = cls.MASKED_PRECISION_RE.match(value)
        if not m or len(m.group(1)) + len(m.group(2)) != 4:
            return None
        return len(m.group(2))

    def evaluate_value(
        self, value: Optional[str], row: Optional[Dict[str, str]] = None
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Validate a single harmonised date value, using `row` (when available)
        to interpret an empty value correctly against date_format_detected.

        Returns
        -------
        warnings : list of str
        errors : dict { label: substitution_value }
        """
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        stripped = str(value).strip() if value is not None else ""
        source_format = (row or {}).get("date_format_detected", "")

        if not stripped:
            if source_format == "missing":
                # Expected: the source had no value at all -- nothing to flag.
                return warnings, errors
            if source_format == "non_parseable":
                # Expected-for-now: the heuristic step deliberately left this
                # residual unresolved (see dates_normaliser.py docstring) --
                # a real gap, but a documented one, not a defect in THIS run.
                warnings.append("unresolved_residual")
                return warnings, errors
            # Empty for any other reason (or row context unavailable) is
            # unexpected -- the normaliser's contract is "always one of the
            # four real shapes, or empty only for missing/non_parseable".
            errors["missing_value"] = ""
            return warnings, errors

        # --- EDTF qualifiers this project never emits by design (defensive) ---
        if "~" in stripped:
            warnings.append("approximate_date")
        if "?" in stripped:
            warnings.append("uncertain_date")
        if self.RANGE_RE.search(stripped):
            warnings.append("date_range")

        # --- Classify against the four real shapes ---
        x_count = self._masked_precision_x_count(stripped)
        if x_count is not None:
            warnings.append({1: "decade_level", 2: "century_level", 3: "millennium_level"}[x_count])
            return warnings, errors

        if (self.EXACT_YEAR_RE.match(stripped)
                or self.EXACT_DATE_RE.match(stripped)
                or self.YEAR_MONTH_RE.match(stripped)):
            return warnings, errors

        # Matches none of the four real shapes -> genuine contract violation.
        errors["non_edtf_format"] = ""
        return warnings, errors
