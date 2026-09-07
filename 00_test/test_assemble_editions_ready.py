import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "03_ready_dataset_assembly"
    / "assemble_editions_ready.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("assemble_editions_ready", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_raw_editions_csv(path, rows):
    fieldnames = ["edition", "bnf_id", "title", "year_first", "year_range",
                 "description", "place", "publisher", "work",
                 "digital_copy_link", "subject_topic", "expression", "language",
                 "record_type", "author", "editor", "translator",
                 "publisher_2", "illustrator"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _write_place_overlay_csv(path, rows):
    fieldnames = ["edition", "place_original", "place_uncertainty_brackets",
                 "place_uncertainty_parentheses", "place_uncertainty_question_marks",
                 "tgn_id", "publication_place", "publication_country",
                 "longitude", "latitude"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def test_run_aggregates_duplicate_rows_per_edition(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [
        {"edition": "E1", "title": "Les Fables", "author": "La Fontaine"},
        {"edition": "E1", "title": "Les Fables", "author": "Barbin"},  # 2nd author URI
    ])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["title"] == "Les Fables"
    assert rows[0]["author"] == "Barbin; La Fontaine"  # sorted, "; "-joined


def test_run_overlays_publication_place(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [
        {"edition": "E1", "place": "Paris (France)"},
    ])
    overlay_path = tmp_path / "place.csv"
    _write_place_overlay_csv(overlay_path, [
        {"edition": "E1", "place_original": "Paris (France)",
         "tgn_id": "tgn:paris", "publication_place": "Paris",
         "publication_country": "France"},
    ])

    mod.run(str(input_path), str(overlay_path),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["place"] == "Paris (France)"  # raw field kept
    assert row["publication_place"] == "Paris"  # new harmonised column added
    assert row["publication_country"] == "France"


def test_run_leaves_place_columns_empty_when_overlay_missing(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [{"edition": "E1", "place": "Paris (France)"}])

    mod.run(str(input_path), str(tmp_path / "does_not_exist.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert row["publication_place"] == ""


def test_run_writes_report_with_field_status(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [{"edition": "E1", "place": "Paris (France)"}])
    overlay_path = tmp_path / "place.csv"
    _write_place_overlay_csv(overlay_path, [
        {"edition": "E1", "publication_place": "Paris", "publication_country": "France"},
    ])

    mod.run(str(input_path), str(overlay_path),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "report.json", encoding="utf-8") as f:
        report = json.load(f)

    assert report["unique_editions"] == 1
    assert report["harmonised_fields"]["publication_place"]["editions_with_value"] == 1
    assert "language" in report["raw_fields_pending_harmonisation"]


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


def test_run_writes_periodic_monitor_checkpoints_and_stops_cleanly(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "MONITOR_CHECKPOINT_EVERY", 1)
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(mod, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [
        {"edition": "E1"}, {"edition": "E2"},
    ])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per row + final
    assert fake_monitor.update_calls[-1] == "Completed editions-ready assembly run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    mod = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(mod, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "raw.csv"
    _write_raw_editions_csv(input_path, [{"edition": "E1"}])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    mod = load_module()
    monitor = mod.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
