import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = PROJECT_ROOT / "04_harmonisation_and_evaluation" / "02_evaluation"


def load_eval_module(name):
    """See test_evaluation_base.py's load_eval_module() for why this
    synthetic-parent-package trick is needed."""
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
    mod = load_eval_module("publication_place_evaluation")
    return mod.PublicationPlaceEvaluation(csv_filepath="unused.csv")


def _row(**overrides):
    base = {
        "place_original": "", "tgn_id": "", "publication_place": "",
        "publication_country": "", "longitude": "", "latitude": "",
    }
    base.update(overrides)
    return base


# ── missing_value vs unmatched_place ─────────────────────────────────────────

def test_truly_empty_row_is_missing_value():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("", row=_row())
    assert errors == {"missing_value": ""}
    assert warnings == []


def test_unresolved_raw_place_is_unmatched_place_warning_not_error():
    """place_original had something, but TGN lookup + country fallback both
    failed -- bnf_place_harmonisation.py's own documented 'unmatched'
    outcome, not a QA defect."""
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("", row=_row(place_original="Nulle part inconnue"))
    assert warnings == ["unmatched_place"]
    assert errors == {}


# ── row-level contract checks: tgn_id / country alongside publication_place ─

def test_resolved_place_without_tgn_id_is_a_contract_violation():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Paris", row=_row(place_original="Paris (France)",
                          publication_place="Paris", publication_country="France"))
    assert "missing_tgn_id" in errors


def test_resolved_place_with_tgn_id_and_country_is_clean():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Paris", row=_row(place_original="Paris (France)", tgn_id="tgn:7008038",
                          publication_place="Paris", publication_country="France",
                          longitude="2.3522", latitude="48.8566"))
    assert errors == {}
    assert warnings == []


def test_resolved_place_without_country_is_a_contract_violation():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Paris", row=_row(place_original="Paris (France)", tgn_id="tgn:7008038",
                          publication_place="Paris"))
    assert "missing_publication_country" in errors


# ── coordinates ───────────────────────────────────────────────────────────────

def test_tgn_matched_without_coordinates_is_a_warning():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Paris", row=_row(place_original="Paris (France)", tgn_id="tgn:7008038",
                          publication_place="Paris", publication_country="France"))
    assert "missing_coordinates" in warnings


def test_coordinates_at_exact_boundary_are_valid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Edge", row=_row(place_original="Edge (Nowhere)", tgn_id="tgn:1",
                          publication_place="Edge", publication_country="Nowhere",
                          longitude="180", latitude="-90"))
    assert "invalid_coordinates" not in errors


def test_coordinates_past_boundary_are_invalid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Edge", row=_row(place_original="Edge (Nowhere)", tgn_id="tgn:1",
                          publication_place="Edge", publication_country="Nowhere",
                          longitude="180.5", latitude="0"))
    assert errors["invalid_coordinates"] == ""


def test_non_numeric_coordinates_are_invalid():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Edge", row=_row(place_original="Edge (Nowhere)", tgn_id="tgn:1",
                          publication_place="Edge", publication_country="Nowhere",
                          longitude="not-a-number", latitude="0"))
    assert errors["invalid_coordinates"] == ""


# ── residual noise left in the harmonised value ──────────────────────────────

def test_residual_bracket_in_harmonised_value():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "[Paris]", row=_row(place_original="[Paris] (France)", tgn_id="tgn:7008038",
                            publication_place="[Paris]", publication_country="France"))
    assert "residual_bracket_in_harmonised" in errors


def test_residual_parenthesis_in_harmonised_value():
    ev = _evaluator()
    warnings, errors = ev.evaluate_value(
        "Paris (?)", row=_row(place_original="Paris (?) (France)", tgn_id="tgn:7008038",
                              publication_place="Paris (?)", publication_country="France"))
    assert "residual_parenthesis_in_harmonised" in errors
    assert "residual_question_mark_in_harmonised" in errors


# ── evaluate_value without row context (single-field fallback) ──────────────

def test_without_row_context_missing_sibling_columns_read_as_empty():
    """No row dict -> row.get(...) for every sibling column reads as "",
    same as an explicitly empty row: a bracket left in the harmonised
    string is always wrong, and with no tgn_id/country evidence either,
    those contract checks fire too (there's nothing to say they're set)."""
    ev = _evaluator()
    warnings, errors = ev.evaluate_value("[Paris]")
    assert errors == {
        "residual_bracket_in_harmonised": "",
        "missing_tgn_id": "",
        "missing_publication_country": "",
    }
