import csv
import importlib.util
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAME_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_name" / "01_heuristic_rules" / "name_normaliser.py"
)


def load_name_normaliser_module():
    spec = importlib.util.spec_from_file_location("name_normaliser", NAME_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_csv(path, rows):
    fieldnames = ["actor", "actor_name", "actor_first_name", "actor_last_name"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── derive_actor_name() ──────────────────────────────────────────────────────

def test_derive_actor_name_passes_through_when_actor_name_present():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Voltaire", "", "")
    assert result == {"harmonised": "Voltaire", "correction_type": "none", "confidence": "high"}


def test_derive_actor_name_from_first_and_last():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "Jean", "Racine")
    assert result["harmonised"] == "Jean Racine"
    assert result["correction_type"] == "derived_from_first_last"
    assert result["confidence"] == "high"


def test_derive_actor_name_from_last_name_only_the_lucretius_case():
    """The colleague's exact case: actor_name and actor_first_name are empty,
    only actor_last_name carries the value."""
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "", "Lucretius")
    assert result["harmonised"] == "Lucretius"
    assert result["correction_type"] == "derived_from_first_last"
    assert result["confidence"] == "high"


def test_derive_actor_name_from_first_name_only():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "Voltaire", "")
    assert result["harmonised"] == "Voltaire"
    assert result["correction_type"] == "derived_from_first_last"


def test_derive_actor_name_unresolved_when_all_empty():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "", "")
    assert result == {"harmonised": "", "correction_type": "unresolved_missing", "confidence": "low"}


# ── collect_unique_actors() ──────────────────────────────────────────────────

def test_collect_unique_actors_deduplicates_by_actor_uri(tmp_path):
    """Mirrors the real raw dataset: the same actor appears on multiple rows
    (one per external-link binding) with identical name fields repeated."""
    nn = load_name_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...other>", "actor_name": "Voltaire"},
    ])

    actors = nn.collect_unique_actors(str(csv_path))

    assert len(actors) == 2
    assert actors["<...cb124434672#about>"] == {
        "actor_name": "", "actor_first_name": "", "actor_last_name": "Nicolas",
    }
    assert actors["<...other>"]["actor_name"] == "Voltaire"


def test_collect_unique_actors_ignores_rows_without_actor_uri(tmp_path):
    nn = load_name_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [{"actor": "", "actor_name": "Nobody"}])

    actors = nn.collect_unique_actors(str(csv_path))
    assert actors == {}


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    nn = load_name_normaliser_module()
    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},
        {"actor": "A2", "actor_name": "Voltaire"},
        {"actor": "A3"},
    ])

    output_dir = tmp_path / "out"
    output_path = nn.run(str(input_path), str(output_dir))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {row["actor_uri"]: row for row in csv.DictReader(f)}

    assert set(rows["A1"].keys()) == {
        "actor_uri", "actor_name_original", "actor_name_harmonised",
        "correction_type", "confidence",
    }
    assert rows["A1"]["actor_name_harmonised"] == "Lucretius"
    assert rows["A1"]["correction_type"] == "derived_from_first_last"

    assert rows["A2"]["actor_name_harmonised"] == "Voltaire"
    assert rows["A2"]["correction_type"] == "none"

    assert rows["A3"]["actor_name_harmonised"] == ""
    assert rows["A3"]["correction_type"] == "unresolved_missing"


def test_run_accepts_zip_input(tmp_path):
    nn = load_name_normaliser_module()
    csv_inner = tmp_path / "actor_data.csv"
    _write_actor_csv(csv_inner, [{"actor": "A1", "actor_last_name": "Lucretius"}])

    zip_path = tmp_path / "actor_data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_inner, arcname="actor_data.csv")

    output_path = nn.run(str(zip_path), str(tmp_path / "out"))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["actor_name_harmonised"] == "Lucretius"


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
    nn = load_name_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(nn, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},
        {"actor": "A2", "actor_name": "Voltaire"},
    ])

    nn.run(str(input_path), str(tmp_path / "out"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per actor + final
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed actor_name harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    nn = load_name_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(nn, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_last_name": "Lucretius"}])

    nn.run(str(input_path), str(tmp_path / "out"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    nn = load_name_normaliser_module()
    monitor = nn.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
