import csv
import importlib.util
import json
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "03_ready_dataset_assembly"
    / "assemble_actors_ready.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("assemble_actors_ready", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_raw_actors_csv(path, rows):
    fieldnames = ["actor", "actor_birth", "actor_name", "actor_first_name",
                 "actor_last_name", "entity_type", "first_year", "actor_country",
                 "actor_language", "actor_gender", "actor_profession",
                 "actor_death", "actor_start", "actor_end",
                 "actor_link_exact", "actor_link_close"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _write_name_overlay_csv(path, rows):
    fieldnames = ["actor_uri", "actor_name_original", "actor_name_harmonised",
                 "correction_type", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def test_run_preserves_raw_row_granularity_no_deduplication(tmp_path):
    """Unlike editions, this script must NOT collapse duplicate rows per
    actor — that stays module 5's job."""
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_actors_csv(input_path, [
        {"actor": "A1", "actor_name": "Voltaire", "actor_link_exact": "<uri1>"},
        {"actor": "A1", "actor_name": "Voltaire", "actor_link_exact": "<uri2>"},
    ])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # both raw rows kept, not aggregated


def test_run_fills_empty_actor_name_from_overlay(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_actors_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},  # actor_name empty
        {"actor": "A2", "actor_name": "Voltaire"},          # already present
    ])
    overlay_path = tmp_path / "overlay.csv"
    _write_name_overlay_csv(overlay_path, [
        {"actor_uri": "A1", "actor_name_harmonised": "Lucretius",
         "correction_type": "derived_from_first_last"},
        {"actor_uri": "A2", "actor_name_harmonised": "Should Not Be Used",
         "correction_type": "derived_from_first_last"},
    ])

    mod.run(str(input_path), str(overlay_path),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = {r["actor"]: r for r in csv.DictReader(f)}

    assert rows["A1"]["actor_name"] == "Lucretius"
    assert rows["A2"]["actor_name"] == "Voltaire"  # not overwritten


def test_run_accepts_zip_input(tmp_path):
    mod = load_module()
    csv_inner = tmp_path / "actor_data.csv"
    _write_raw_actors_csv(csv_inner, [{"actor": "A1", "actor_last_name": "Lucretius"}])
    zip_path = tmp_path / "actor_data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_inner, arcname="actor_data.csv")

    mod.run(str(zip_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_run_writes_report(tmp_path):
    mod = load_module()
    input_path = tmp_path / "raw.csv"
    _write_raw_actors_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},
        {"actor": "A2", "actor_name": "Voltaire"},
    ])
    overlay_path = tmp_path / "overlay.csv"
    _write_name_overlay_csv(overlay_path, [
        {"actor_uri": "A1", "actor_name_harmonised": "Lucretius",
         "correction_type": "derived_from_first_last"},
    ])

    mod.run(str(input_path), str(overlay_path),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)

    with open(tmp_path / "report.json", encoding="utf-8") as f:
        report = json.load(f)

    assert report["total_raw_rows"] == 2
    assert report["unique_actors"] == 2
    assert report["harmonised_fields"]["actor_name"]["rows_filled"] == 1
    assert "actor_birth" in report["raw_fields_pending_harmonisation"]


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
    _write_raw_actors_csv(input_path, [{"actor": "A1"}, {"actor": "A2"}])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1
    assert fake_monitor.update_calls[-1] == "Completed actors-ready assembly run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    mod = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(mod, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "raw.csv"
    _write_raw_actors_csv(input_path, [{"actor": "A1"}])

    mod.run(str(input_path), str(tmp_path / "no_overlay.csv"),
           str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    mod = load_module()
    monitor = mod.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
