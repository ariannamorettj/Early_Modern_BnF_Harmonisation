import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = PROJECT_ROOT / "04_harmonisation_and_evaluation" / "02_evaluation"


def load_eval_module(name):
    """See test_evaluation_base.py's load_eval_module() for why this
    synthetic-parent-package trick is needed (02_evaluation's modules use
    real relative imports, but its directory names start with digits)."""
    pkg_name = "_bnf_eval_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(EVAL_DIR)]
        sys.modules[pkg_name] = pkg
    full_name = f"{pkg_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, EVAL_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def _evaluator():
    mod = load_eval_module("actor_dates_evaluation")
    return mod.ActorDatesEvaluation(csv_filepath="unused.csv")


# ── The four real shapes dates_normaliser.py produces ────────────────────────

def test_exact_year_is_valid_no_findings():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1750")
    assert warnings == []
    assert errors == {}


def test_exact_year_bce_is_valid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("-0043")
    assert warnings == []
    assert errors == {}


def test_exact_date_is_valid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1594-06-14")
    assert warnings == []
    assert errors == {}


def test_year_month_is_valid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1564-04")
    assert warnings == []
    assert errors == {}


# ── masked_precision + the three precision-level warnings (the TODO) ────────

def test_decade_level_one_x():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("175X")
    assert warnings == ["decade_level"]
    assert errors == {}


def test_century_level_two_x():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("17XX")
    assert warnings == ["century_level"]
    assert errors == {}


def test_millennium_level_three_x():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1XXX")
    assert warnings == ["millennium_level"]
    assert errors == {}


def test_masked_precision_bce():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("-17XX")
    assert warnings == ["century_level"]
    assert errors == {}


# ── non_edtf_format: a value matching none of the four real shapes ──────────

def test_malformed_value_is_non_edtf_format():
    ev = _evaluator()
    # A genuinely malformed value the normaliser should never emit.
    warnings, errors = ev.evaluate_value("175.-07-27")
    assert errors == {"non_edtf_format": ""}


def test_five_digit_year_is_non_edtf_format():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("17500")
    assert errors == {"non_edtf_format": ""}


# ── empty value: interpreted via row['date_format_detected'] ────────────────

def test_empty_value_with_missing_format_is_not_an_error():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("", row={"date_format_detected": "missing"})
    assert warnings == []
    assert errors == {}


def test_empty_value_with_non_parseable_format_is_a_warning_not_error():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("", row={"date_format_detected": "non_parseable"})
    assert warnings == ["unresolved_residual"]
    assert errors == {}


def test_empty_value_without_row_context_is_missing_value_error():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("")
    assert errors == {"missing_value": ""}


def test_empty_value_with_unexpected_format_is_missing_value_error():
    ev = _evaluator()
    # date_format_detected says the heuristic resolved it to *something*,
    # yet date_harmonised is empty -- a real contract violation.
    warnings, errors = ev.evaluate_value("", row={"date_format_detected": "exact_year"})
    assert errors == {"missing_value": ""}


# ── defensive/forward-compatible EDTF qualifier checks ───────────────────────

def test_approximate_and_uncertain_markers_are_warnings_not_errors():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1750~")
    assert "approximate_date" in warnings
    warnings, errors = ev.evaluate_value("1750?")
    assert "uncertain_date" in warnings


def test_date_range_is_a_warning():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("1750/1760")
    assert "date_range" in warnings
