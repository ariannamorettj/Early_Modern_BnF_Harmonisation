import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LANGUAGE_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "language" / "01_heuristic_rules" / "language_normaliser.py"
)


def load_language_normaliser_module():
    spec = importlib.util.spec_from_file_location("language_normaliser", LANGUAGE_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_edition_csv(path, rows):
    fieldnames = ["edition", "language"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── detect_language_format() ─────────────────────────────────────────────────

def test_detect_language_format_missing():
    ln = load_language_normaliser_module()
    assert ln.detect_language_format("") == "missing"


def test_detect_language_format_iso_code_uri():
    ln = load_language_normaliser_module()
    assert ln.detect_language_format("<http://id.loc.gov/vocabulary/iso639-2/fre>") == "iso_code_uri"
    assert ln.detect_language_format("<http://id.loc.gov/vocabulary/iso639-2/mul>") == "iso_code_uri"


def test_detect_language_format_non_parseable():
    ln = load_language_normaliser_module()
    for value in ("fre", "<http://id.loc.gov/vocabulary/iso639-2/FRE>",
                  "francais", "<http://id.loc.gov/vocabulary/iso639-2/fr>"):
        assert ln.detect_language_format(value) == "non_parseable"


# ── normalise_language() ─────────────────────────────────────────────────────

def test_normalise_language_extracts_code():
    ln = load_language_normaliser_module()
    result = ln.normalise_language("<http://id.loc.gov/vocabulary/iso639-2/lat>")
    assert result == {"harmonised": "lat", "correction_type": "iso_code_uri", "confidence": "high"}


def test_normalise_language_missing_is_low_confidence():
    ln = load_language_normaliser_module()
    result = ln.normalise_language("")
    assert result == {"harmonised": "", "correction_type": "missing", "confidence": "low"}


def test_normalise_language_non_parseable_is_low_confidence_and_empty():
    ln = load_language_normaliser_module()
    result = ln.normalise_language("francais")
    assert result["harmonised"] == ""
    assert result["correction_type"] == "non_parseable"
    assert result["confidence"] == "low"


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    ln = load_language_normaliser_module()
    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [
        {"edition": "E1", "language": "<http://id.loc.gov/vocabulary/iso639-2/fre>"},
        {"edition": "E1", "language": "<http://id.loc.gov/vocabulary/iso639-2/fre>"},  # duplicate row
        {"edition": "E2", "language": ""},
    ])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    ln.run(str(input_path), str(output_path), str(report_path))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert set(rows[0].keys()) == {
        "edition", "language_original", "language_harmonised", "correction_type", "confidence",
    }
    assert len(rows) == 2  # deduped to one row per edition

    by_edition = {r["edition"]: r for r in rows}
    assert by_edition["E1"]["language_harmonised"] == "fre"
    assert by_edition["E2"]["correction_type"] == "missing"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["total_editions"] == 2
    assert report["iso_code_uri"] == 1
    assert report["missing"] == 1


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


def test_run_stops_monitor_cleanly_when_enabled(monkeypatch, tmp_path):
    ln = load_language_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(ln, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [
        {"edition": "E1", "language": "<http://id.loc.gov/vocabulary/iso639-2/fre>"},
    ])

    ln.run(str(input_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert fake_monitor.update_calls[-1] == "Completed language harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    ln = load_language_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(ln, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [
        {"edition": "E1", "language": "<http://id.loc.gov/vocabulary/iso639-2/fre>"},
    ])

    ln.run(str(input_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    ln = load_language_normaliser_module()
    monitor = ln.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
