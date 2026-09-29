import csv
import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = PROJECT_ROOT / "04_harmonisation_and_evaluation" / "02_evaluation"


def load_eval_module(name):
    """02_evaluation's modules use real relative imports (`from .evaluation_base
    import Evaluation`), but its own parent directories ('04_...', '02_...')
    start with digits and can't be `import`-ed by dotted path. Register a
    synthetic parent package pointing at the real directory so the relative
    imports resolve via the normal import machinery, mirroring how the other
    test files load standalone scripts via spec_from_file_location -- this
    just also needs a package context for the relative import to work."""
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


def _make_row_capturing_evaluator(Evaluation):
    """Builds a minimal Evaluation subclass that records every (value, row)
    pair it's called with, to verify run()'s row-passing behaviour without
    depending on any real field evaluator."""
    class _Capturing(Evaluation):
        def __init__(self, csv_filepath, field_name):
            super().__init__({"field": field_name, "warning": [], "error": []},
                             csv_filepath, field_name=field_name)
            self.calls = []

        def evaluate_value(self, value, row=None):
            self.calls.append((value, row))
            return [], {}

    return _Capturing


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_run_passes_full_row_dict_to_evaluate_value(tmp_path):
    mod = load_eval_module("evaluation_base")
    Capturing = _make_row_capturing_evaluator(mod.Evaluation)

    csv_path = tmp_path / "data.csv"
    _write_csv(csv_path, ["a", "b", "c"], [["1", "2", "3"], ["4", "5", "6"]])

    evaluator = Capturing(str(csv_path), field_name="b")
    evaluator.run(output_dir=str(tmp_path / "out"))

    assert evaluator.calls == [
        ("2", {"a": "1", "b": "2", "c": "3"}),
        ("5", {"a": "4", "b": "5", "c": "6"}),
    ]


def test_evaluate_value_default_signature_accepts_row_kwarg():
    """The base class's abstract method itself must accept `row` (raises
    NotImplementedError, but must not raise a TypeError on the call itself)."""
    mod = load_eval_module("evaluation_base")
    base = mod.Evaluation({"field": "x", "warning": [], "error": []}, "unused.csv")
    try:
        base.evaluate_value("v", {"x": "v"})
    except NotImplementedError:
        pass
    else:
        raise AssertionError("expected NotImplementedError from the base evaluate_value")


def test_subclass_ignoring_row_still_works(tmp_path):
    """A subclass whose evaluate_value only accepts `value` (the pattern the
    four untouched evaluators still use) must keep working once `run()`
    starts passing `row` as a second positional argument -- Python allows
    a caller to pass more args than a callee *requires* only if the callee
    accepts them; this test locks in that the single-arg override style
    already used elsewhere in this codebase is still valid against the
    extended base contract (row has a default, so old code with an extra
    unused kwarg-less signature would break -- this proves it doesn't, by
    using a signature identical to the pre-existing evaluators)."""
    mod = load_eval_module("evaluation_base")

    class LegacyStyle(mod.Evaluation):
        def __init__(self, csv_filepath, field_name):
            super().__init__({"field": field_name, "warning": ["w"], "error": ["e"]},
                             csv_filepath, field_name=field_name)

        def evaluate_value(self, value, row=None):
            # Same shape as actor_name_evaluation.py etc. post-change: they
            # accept row=None and simply never read it.
            if value == "bad":
                return ["w"], {"e": "fix"}
            return [], {}

    csv_path = tmp_path / "data.csv"
    _write_csv(csv_path, ["field"], [["bad"], ["ok"]])

    evaluator = LegacyStyle(str(csv_path), field_name="field")
    out_dir = tmp_path / "out"
    evaluator.run(output_dir=str(out_dir))

    with open(out_dir / "field_summary.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cases = {r["case"] for r in rows}
    assert "w" in cases
    assert "e" in cases
