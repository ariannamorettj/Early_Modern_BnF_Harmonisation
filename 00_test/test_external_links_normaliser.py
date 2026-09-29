import csv
import importlib.util
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_LINKS_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "external_links" / "01_heuristic_rules" / "external_links_normaliser.py"
)


def load_external_links_normaliser_module():
    spec = importlib.util.spec_from_file_location(
        "external_links_normaliser", EXTERNAL_LINKS_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_csv(path, rows):
    fieldnames = ["actor", "actor_link_close", "actor_link_exact"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── strip_wrapping() ─────────────────────────────────────────────────────────

def test_strip_wrapping_removes_angle_brackets():
    eln = load_external_links_normaliser_module()
    assert eln.strip_wrapping("<http://viaf.org/viaf/123/>") == "http://viaf.org/viaf/123/"


def test_strip_wrapping_leaves_unwrapped_value_unchanged():
    eln = load_external_links_normaliser_module()
    assert eln.strip_wrapping("http://viaf.org/viaf/123/") == "http://viaf.org/viaf/123/"


# ── normalise_link() ─────────────────────────────────────────────────────────

def test_normalise_link_missing():
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("")
    assert result["correction_type"] == "missing"
    assert result["confidence"] == "low"
    assert result["harmonised"] == ""


def test_normalise_link_malformed_empty_scheme_and_host():
    # Real pattern found in the raw dataset: "<://43102>"
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("<://43102>")
    assert result["correction_type"] == "malformed"
    assert result["confidence"] == "low"
    assert result["harmonised"] == ""


def test_normalise_link_passthrough_known_authority():
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("<http://viaf.org/viaf/23356192/>")
    assert result["correction_type"] == "passthrough"
    assert result["confidence"] == "high"
    assert result["authority"] == "VIAF"
    assert result["harmonised"] == "http://viaf.org/viaf/23356192/"


def test_normalise_link_scheme_upgraded_for_evidenced_domain():
    # imslp.org is directly observed with both http and https in the raw
    # dataset -> evidence-backed upgrade.
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("<http://imslp.org/wiki/Category:Mersenne%2C_Marin>")
    assert result["correction_type"] == "scheme_upgraded_https"
    assert result["confidence"] == "high"
    assert result["harmonised"].startswith("https://imslp.org/")


def test_normalise_link_does_not_upgrade_scheme_for_single_scheme_domain():
    # viaf.org is only ever observed as http in the raw dataset -- no
    # evidence-backed https upgrade (see module docstring's "don't invent
    # digits" principle).
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("<http://viaf.org/viaf/23356192/>")
    assert result["harmonised"].startswith("http://")


def test_normalise_link_unknown_authority():
    eln = load_external_links_normaliser_module()
    result = eln.normalise_link("<http://example.org/some/path>")
    assert result["correction_type"] == "unknown_authority"
    assert result["confidence"] == "medium"
    assert result["authority"] == ""


# ── collect_actor_links() ────────────────────────────────────────────────────

def test_collect_actor_links_gathers_distinct_values_per_field(tmp_path):
    eln = load_external_links_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"},
        {"actor": "A1", "actor_link_exact": "<http://wikidata.org/entity/Q1>"},
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"},  # duplicate
        {"actor": "A2", "actor_link_close": "<http://isni.org/isni/1/>"},
    ])

    actors = eln.collect_actor_links(str(csv_path))

    assert len(actors) == 2
    assert actors["A1"]["actor_link_exact"] == {
        "<http://viaf.org/viaf/1/>", "<http://wikidata.org/entity/Q1>",
    }
    assert actors["A1"]["actor_link_close"] == set()
    assert actors["A2"]["actor_link_close"] == {"<http://isni.org/isni/1/>"}


def test_collect_actor_links_ignores_rows_without_actor_uri(tmp_path):
    eln = load_external_links_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [{"actor": "", "actor_link_exact": "<http://viaf.org/viaf/1/>"}])

    actors = eln.collect_actor_links(str(csv_path))
    assert actors == {}


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    eln = load_external_links_normaliser_module()
    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"},
        {"actor": "A1", "actor_link_close": "<://999>"},
        {"actor": "A2"},
    ])

    output_dir = tmp_path / "out"
    output_path = eln.run(str(input_path), str(output_dir))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert set(rows[0].keys()) == {
        "actor_uri", "field", "link_original", "link_harmonised",
        "authority", "correction_type", "confidence",
    }
    # A1 has one exact + one close link; A2 has none -> 2 rows total, not a
    # placeholder row per missing field (see module docstring).
    assert len(rows) == 2

    by_key = {(r["actor_uri"], r["field"]): r for r in rows}
    assert by_key[("A1", "actor_link_exact")]["link_harmonised"] == "http://viaf.org/viaf/1/"
    assert by_key[("A1", "actor_link_close")]["correction_type"] == "malformed"


def test_run_accepts_zip_input(tmp_path):
    eln = load_external_links_normaliser_module()
    csv_inner = tmp_path / "actor_data.csv"
    _write_actor_csv(csv_inner, [{"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"}])

    zip_path = tmp_path / "actor_data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_inner, arcname="actor_data.csv")

    output_path = eln.run(str(zip_path), str(tmp_path / "out"))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["link_harmonised"] == "http://viaf.org/viaf/1/"


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
    eln = load_external_links_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(eln, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"},
        {"actor": "A2", "actor_link_close": "<http://isni.org/isni/1/>"},
    ])

    eln.run(str(input_path), str(tmp_path / "out"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per actor + final
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed external_links harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    eln = load_external_links_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(eln, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1/>"}])

    eln.run(str(input_path), str(tmp_path / "out"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    eln = load_external_links_normaliser_module()
    monitor = eln.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
