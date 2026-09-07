import csv
import importlib.util
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATES_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_dates" / "01_heuristic_rules" / "dates_normaliser.py"
)


def load_dates_normaliser_module():
    spec = importlib.util.spec_from_file_location("dates_normaliser", DATES_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_csv(path, rows):
    fieldnames = ["actor", "actor_birth", "actor_death", "actor_start", "actor_end"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── detect_date_format() ─────────────────────────────────────────────────────

def test_detect_date_format_missing():
    dn = load_dates_normaliser_module()
    assert dn.detect_date_format("") == "missing"


def test_detect_date_format_exact_year_various_widths():
    dn = load_dates_normaliser_module()
    for value in ("1750", "882", "43", "3"):
        assert dn.detect_date_format(value) == "exact_year"


def test_detect_date_format_exact_date():
    dn = load_dates_normaliser_module()
    assert dn.detect_date_format("1594-06-14") == "exact_date"


def test_detect_date_format_year_month():
    dn = load_dates_normaliser_module()
    assert dn.detect_date_format("1564-04") == "year_month"


def test_detect_date_format_masked_precision_dot_and_x():
    dn = load_dates_normaliser_module()
    assert dn.detect_date_format("17..") == "masked_precision"
    assert dn.detect_date_format("1...") == "masked_precision"
    assert dn.detect_date_format("17XX") == "masked_precision"


def test_detect_date_format_bce_variants():
    dn = load_dates_normaliser_module()
    # both "-43" (no space) and "- 43" (space) occur in the raw dataset
    assert dn.detect_date_format("-43") == "exact_year"
    assert dn.detect_date_format("- 43") == "exact_year"
    assert dn.detect_date_format("- 04..") == "masked_precision"
    assert dn.detect_date_format("- 431-06-14") == "exact_date"


def test_detect_date_format_non_parseable_edge_cases():
    dn = load_dates_normaliser_module()
    # masked digit inside a full date, or a "?" mask char: real but rare
    # (~0.02%) forms found in the raw dataset that the heuristic rule does
    # not attempt to resolve.
    for value in ("150.-02-20", "1799-03-2.", "14??", "18 ."):
        assert dn.detect_date_format(value) == "non_parseable"


# ── normalise_date() ─────────────────────────────────────────────────────────

def test_normalise_date_exact_year_zero_padded():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("43")
    assert result == {"harmonised": "0043", "format_detected": "exact_year", "confidence": "high"}


def test_normalise_date_exact_date_passthrough():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("1594-06-14")
    assert result["harmonised"] == "1594-06-14"
    assert result["format_detected"] == "exact_date"
    assert result["confidence"] == "high"


def test_normalise_date_year_month():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("1564-04")
    assert result == {"harmonised": "1564-04", "format_detected": "year_month", "confidence": "high"}


def test_normalise_date_masked_precision_dot_converts_to_x():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("17..")
    assert result == {"harmonised": "17XX", "format_detected": "masked_precision", "confidence": "high"}


def test_normalise_date_masked_precision_millennium_level():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("1...")
    assert result["harmonised"] == "1XXX"


def test_normalise_date_missing_and_non_parseable_are_low_confidence():
    dn = load_dates_normaliser_module()
    for value in ("", "150.-02-20"):
        result = dn.normalise_date(value)
        assert result["harmonised"] == ""
        assert result["confidence"] == "low"


def test_normalise_date_bce_no_astronomical_offset_aristotle_case():
    """Empirically verified against the raw dataset: one actor has
    actor_birth="- 384", actor_death="- 322" -- Aristotle's well-known BCE
    dates (384-322 BCE), matching the digits exactly with no shift. Strict
    ISO/EDTF astronomical year numbering would require "-0383"/"-0321"
    instead -- confirming the source already uses ordinary historical BCE
    counting, so no offset is applied here (see module docstring)."""
    dn = load_dates_normaliser_module()
    birth = dn.normalise_date("- 384")
    death = dn.normalise_date("- 322")
    assert birth["harmonised"] == "-0384"
    assert death["harmonised"] == "-0322"


def test_normalise_date_bce_exact_date():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("- 431-06-14")
    assert result["harmonised"] == "-0431-06-14"


def test_normalise_date_bce_masked_precision():
    dn = load_dates_normaliser_module()
    result = dn.normalise_date("- 04..")
    assert result["harmonised"] == "-04XX"


# ── collect_unique_actor_dates() ─────────────────────────────────────────────

def test_collect_unique_actor_dates_deduplicates_by_actor_uri():
    dn = load_dates_normaliser_module()
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "actors.csv")
        _write_actor_csv(csv_path, [
            {"actor": "A1", "actor_birth": "1750"},
            {"actor": "A1", "actor_birth": "1750"},
            {"actor": "A2", "actor_death": "1800"},
        ])
        actors = dn.collect_unique_actor_dates(csv_path)

    assert len(actors) == 2
    assert actors["A1"]["actor_birth"] == "1750"
    assert actors["A1"]["actor_death"] == ""
    assert actors["A2"]["actor_death"] == "1800"


def test_collect_unique_actor_dates_ignores_rows_without_actor_uri(tmp_path):
    dn = load_dates_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [{"actor": "", "actor_birth": "1750"}])

    actors = dn.collect_unique_actor_dates(str(csv_path))
    assert actors == {}


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    dn = load_dates_normaliser_module()
    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_birth": "1750", "actor_death": "- 43"},
        {"actor": "A2"},
    ])

    output_dir = tmp_path / "out"
    output_path = dn.run(str(input_path), str(output_dir))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert set(rows[0].keys()) == {
        "actor_uri", "field", "date_original", "date_harmonised",
        "date_format_detected", "confidence",
    }
    # 2 actors x 4 date fields each
    assert len(rows) == 8

    by_field = {(r["actor_uri"], r["field"]): r for r in rows}
    assert by_field[("A1", "actor_birth")]["date_harmonised"] == "1750"
    assert by_field[("A1", "actor_death")]["date_harmonised"] == "-0043"
    assert by_field[("A2", "actor_birth")]["date_format_detected"] == "missing"
    assert by_field[("A2", "actor_birth")]["confidence"] == "low"


def test_run_accepts_zip_input(tmp_path):
    dn = load_dates_normaliser_module()
    csv_inner = tmp_path / "actor_data.csv"
    _write_actor_csv(csv_inner, [{"actor": "A1", "actor_birth": "1750"}])

    zip_path = tmp_path / "actor_data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_inner, arcname="actor_data.csv")

    output_path = dn.run(str(zip_path), str(tmp_path / "out"))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4  # one actor x 4 fields
    birth_row = next(r for r in rows if r["field"] == "actor_birth")
    assert birth_row["date_harmonised"] == "1750"


# ── Monitor integration ──────────────────────────────────────────────────────

class FakeMonitorModule:
    def __init__(self):
        self.start_calls = []
        self.update_calls = []
        self.stop_calls = []

    def start_monitor_state(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"report_path": "fake_report.txt", "closed": False}

    def update_monitor_state(self, state, context=None, print_console=True):
        self.update_calls.append(context)
        return state

    def stop_monitor_state(self, state, print_stop_message=True):
        self.stop_calls.append(print_stop_message)
        state["closed"] = True
        return state


def test_run_writes_monitor_checkpoint_per_actor_and_stops_cleanly(monkeypatch, tmp_path):
    dn = load_dates_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(dn, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_birth": "1750"},
        {"actor": "A2", "actor_death": "1800"},
    ])

    dn.run(str(input_path), str(tmp_path / "out"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per actor + final
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed actor_dates harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    dn = load_dates_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(dn, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_birth": "1750"}])

    dn.run(str(input_path), str(tmp_path / "out"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    dn = load_dates_normaliser_module()
    monitor = dn.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")


def test_load_llm_module_resolves_real_llm_script():
    dn = load_dates_normaliser_module()
    llm_module = dn.load_llm_module()

    assert hasattr(llm_module, "run")
    assert hasattr(llm_module, "CACHE_PATH_DEFAULT")


# ── main() orchestration: LLM step wiring ────────────────────────────────────

class FakeLLMModule:
    def __init__(self):
        self.run_calls = []
        self.CACHE_PATH_DEFAULT = "fake/cache/path.json"

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def test_main_runs_llm_step_by_default(monkeypatch, tmp_path):
    dn = load_dates_normaliser_module()
    fake_llm = FakeLLMModule()
    monkeypatch.setattr(dn, "load_llm_module", lambda: fake_llm)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_birth": "1750"}])
    output_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "dates_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_dir),
        "--no-monitor",
    ])
    dn.main()

    assert len(fake_llm.run_calls) == 1
    call = fake_llm.run_calls[0]
    expected_output = str(output_dir / dn.OUTPUT_FILENAME_DEFAULT)
    assert call["heuristic_output_csv"] == expected_output
    assert call["output_path"] == expected_output
    assert call["cache_path"] == fake_llm.CACHE_PATH_DEFAULT
    assert call["model"] == "claude-opus-5"
    assert call["effort"] == "low"
    assert call["use_monitor"] is False


def test_main_no_llm_flag_skips_llm_step(monkeypatch, tmp_path):
    dn = load_dates_normaliser_module()

    def fail_if_called():
        raise AssertionError("load_llm_module should not be called when --no-llm is passed")

    monkeypatch.setattr(dn, "load_llm_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_birth": "1750"}])
    output_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "dates_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_dir),
        "--no-monitor",
        "--no-llm",
    ])
    dn.main()  # must not raise -> load_llm_module was never called

    assert (output_dir / dn.OUTPUT_FILENAME_DEFAULT).exists()
