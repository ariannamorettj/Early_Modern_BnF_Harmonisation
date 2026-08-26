import csv
import importlib.util
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GEN_SUBSET_OPTM_PATH = (
    PROJECT_ROOT / "05_subset_optimisation 2" / "gen_subset_optm.py"
)


def load_gen_subset_optm_module():
    spec = importlib.util.spec_from_file_location("gen_subset_optm", GEN_SUBSET_OPTM_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_zip(zip_path, rows):
    fieldnames = ["actor"] + [
        "actor_name", "actor_first_name", "actor_last_name",
        "actor_birth", "actor_death", "actor_start", "actor_end",
        "first_year", "entity_type", "actor_gender",
        "actor_country", "actor_language",
        "actor_link_exact", "actor_link_close",
    ]
    csv_text_path = zip_path.with_suffix(".csv.tmp")
    with open(csv_text_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_text_path, arcname="actor_data.csv")
    csv_text_path.unlink()


def _write_harmonised_csv(path, rows):
    fieldnames = ["actor_uri", "actor_name_original", "actor_name_harmonised",
                 "correction_type", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── load_actor_name_harmonised() ─────────────────────────────────────────────

def test_load_actor_name_harmonised_keeps_only_derived_rows(tmp_path):
    gso = load_gen_subset_optm_module()
    path = tmp_path / "harmonised.csv"
    _write_harmonised_csv(path, [
        {"actor_uri": "A1", "actor_name_harmonised": "Lucretius",
         "correction_type": "derived_from_first_last"},
        {"actor_uri": "A2", "actor_name_harmonised": "Voltaire",
         "correction_type": "none"},
        {"actor_uri": "A3", "actor_name_harmonised": "",
         "correction_type": "unresolved_missing"},
    ])

    mapping = gso.load_actor_name_harmonised(str(path))

    assert mapping == {"A1": "Lucretius"}


def test_load_actor_name_harmonised_missing_file_returns_empty(tmp_path):
    gso = load_gen_subset_optm_module()
    mapping = gso.load_actor_name_harmonised(str(tmp_path / "does_not_exist.csv"))
    assert mapping == {}


# ── read_actor_data() wiring ─────────────────────────────────────────────────

def test_read_actor_data_fills_empty_actor_name_from_harmonised_mapping(tmp_path):
    gso = load_gen_subset_optm_module()
    zip_path = tmp_path / "actors.zip"
    _write_actor_zip(zip_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},  # actor_name empty
        {"actor": "A2", "actor_name": "Voltaire"},          # already present
    ])

    records, merge_tracking, total_rows, dup_rows, filled, _ = gso.read_actor_data(
        zip_path=str(zip_path),
        roles_mapping={},
        year_filter_active=False,
        actor_name_harmonised={"A1": "Lucretius", "A2": "Should Not Be Used"},
    )

    by_id = {r["BnF_ID"]: r for r in records}
    assert by_id["A1"]["actor_name"] == "Lucretius"
    assert by_id["A2"]["actor_name"] == "Voltaire"  # not overwritten
    assert filled == 1


def test_read_actor_data_leaves_actor_name_empty_without_harmonised_entry(tmp_path):
    gso = load_gen_subset_optm_module()
    zip_path = tmp_path / "actors.zip"
    _write_actor_zip(zip_path, [{"actor": "A1"}])  # nothing filled in at all

    records, _, _, _, filled, _ = gso.read_actor_data(
        zip_path=str(zip_path),
        roles_mapping={},
        year_filter_active=False,
        actor_name_harmonised={},
    )

    assert records[0]["actor_name"] == ""
    assert filled == 0


def test_read_actor_data_without_harmonised_mapping_is_unaffected(tmp_path):
    """actor_name_harmonised=None (the default) must behave exactly like
    before this change."""
    gso = load_gen_subset_optm_module()
    zip_path = tmp_path / "actors.zip"
    _write_actor_zip(zip_path, [{"actor": "A1", "actor_last_name": "Lucretius"}])

    records, _, _, _, filled, _ = gso.read_actor_data(
        zip_path=str(zip_path),
        roles_mapping={},
        year_filter_active=False,
    )

    assert records[0]["actor_name"] == ""
    assert filled == 0


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


def test_read_actor_data_writes_periodic_monitor_checkpoints(tmp_path):
    gso = load_gen_subset_optm_module()
    monkeypatch_every = gso.MONITOR_CHECKPOINT_EVERY
    gso.MONITOR_CHECKPOINT_EVERY = 2  # small cadence so the test stays fast
    try:
        zip_path = tmp_path / "actors.zip"
        _write_actor_zip(zip_path, [
            {"actor": "A1"}, {"actor": "A2"}, {"actor": "A3"}, {"actor": "A4"},
        ])

        fake_monitor = FakeMonitorModule()
        fake_state = fake_monitor.start_monitor_state()

        gso.read_actor_data(
            zip_path=str(zip_path),
            roles_mapping={},
            year_filter_active=False,
            monitor_module=fake_monitor,
            monitor_state=fake_state,
        )

        assert len(fake_monitor.update_calls) == 2  # checkpoints at row 2 and row 4
    finally:
        gso.MONITOR_CHECKPOINT_EVERY = monkeypatch_every


def test_main_starts_and_stops_monitor_by_default(monkeypatch, tmp_path):
    gso = load_gen_subset_optm_module()

    zip_path = tmp_path / "actors.zip"
    _write_actor_zip(zip_path, [{"actor": "A1", "actor_name": "Voltaire"}])

    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(gso, "load_monitor_module", lambda monitor_script: fake_monitor)
    monkeypatch.setattr(gso, "load_actor_name_harmonised", lambda path: {})
    monkeypatch.setattr(gso, "load_roles_mapping", lambda path: {})

    monkeypatch.setattr(sys, "argv", [
        "gen_subset_optm.py",
        "--input-zip", str(zip_path),
        "--output-dir", str(tmp_path / "out"),
        "--report-dir", str(tmp_path / "report"),
    ])

    gso.main()

    assert len(fake_monitor.start_calls) == 1
    assert fake_monitor.update_calls[-1] == "Completed subset-optimisation run"
    assert fake_monitor.stop_calls == [True]


def test_main_skips_monitor_with_no_monitor_flag(monkeypatch, tmp_path):
    gso = load_gen_subset_optm_module()

    zip_path = tmp_path / "actors.zip"
    _write_actor_zip(zip_path, [{"actor": "A1", "actor_name": "Voltaire"}])

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called with --no-monitor")

    monkeypatch.setattr(gso, "load_monitor_module", fail_if_called)
    monkeypatch.setattr(gso, "load_actor_name_harmonised", lambda path: {})
    monkeypatch.setattr(gso, "load_roles_mapping", lambda path: {})

    monkeypatch.setattr(sys, "argv", [
        "gen_subset_optm.py",
        "--input-zip", str(zip_path),
        "--output-dir", str(tmp_path / "out"),
        "--report-dir", str(tmp_path / "report"),
        "--no-monitor",
    ])

    gso.main()


def test_load_monitor_module_resolves_real_monitor_script():
    gso = load_gen_subset_optm_module()
    monitor = gso.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
