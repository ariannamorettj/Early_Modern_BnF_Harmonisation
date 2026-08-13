import csv
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKIDATA_SCRIPT_PATH = PROJECT_ROOT / "06_mapping" / "02_map_wikidata.py"


def load_wikidata_module():
    spec = importlib.util.spec_from_file_location("map_wikidata", WIKIDATA_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeFetchJson:
    """Stub for map_wikidata.fetch_json that records the SPARQL query instead
    of hitting the live Wikidata Query Service."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, params=None, headers=None, retries=3, sleep=1.0):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return None  # no candidates needed — we only inspect the query text

    @property
    def last_query(self):
        return self.calls[-1]["params"]["query"]


def test_search_wikidata_by_name_filters_by_birth_year_only(monkeypatch):
    wikidata = load_wikidata_module()
    fake_fetch = FakeFetchJson()
    monkeypatch.setattr(wikidata, "fetch_json", fake_fetch)

    wikidata.search_wikidata_by_name("Jean Dupont", "1600", None, sleep=0)

    query = fake_fetch.last_query
    assert "YEAR(?bd) >= 1598" in query
    assert "YEAR(?bd) <= 1602" in query
    assert "YEAR(?dd)" not in query


def test_search_wikidata_by_name_filters_by_death_year_only(monkeypatch):
    """This is the scenario the collega flagged: birth year missing but death
    year available should still constrain the SPARQL search instead of
    falling back to an unfiltered name-only lookup."""
    wikidata = load_wikidata_module()
    fake_fetch = FakeFetchJson()
    monkeypatch.setattr(wikidata, "fetch_json", fake_fetch)

    wikidata.search_wikidata_by_name("Jean Dupont", None, "1650", sleep=0)

    query = fake_fetch.last_query
    assert "YEAR(?dd) >= 1648" in query
    assert "YEAR(?dd) <= 1652" in query
    assert "YEAR(?bd)" not in query


def test_search_wikidata_by_name_filters_by_both_birth_and_death_year(monkeypatch):
    wikidata = load_wikidata_module()
    fake_fetch = FakeFetchJson()
    monkeypatch.setattr(wikidata, "fetch_json", fake_fetch)

    wikidata.search_wikidata_by_name("Jean Dupont", "1600", "1650", sleep=0)

    query = fake_fetch.last_query
    assert "YEAR(?bd) >= 1598" in query
    assert "YEAR(?dd) >= 1648" in query
    assert query.count("FILTER(") == 1  # both conditions combined in one FILTER


def test_search_wikidata_by_name_no_date_filter_when_both_missing(monkeypatch):
    wikidata = load_wikidata_module()
    fake_fetch = FakeFetchJson()
    monkeypatch.setattr(wikidata, "fetch_json", fake_fetch)

    wikidata.search_wikidata_by_name("Jean Dupont", None, None, sleep=0)

    query = fake_fetch.last_query
    assert "FILTER(" not in query


class FakeMonitorModule:
    """Records start/update/stop calls so run_mapping's monitor wiring can be
    verified without touching the real 00_monitor/monitor.py system probes."""

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


def _write_actors_csv(path, rows):
    fieldnames = ["BnF_ID", "actor_name", "actor_first_name", "actor_last_name",
                 "actor_birth", "actor_death", "actor_link_exact", "actor_link_close"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def test_run_mapping_passes_actor_death_to_name_search(monkeypatch, tmp_path):
    wikidata = load_wikidata_module()

    input_path = tmp_path / "actors.csv"
    _write_actors_csv(input_path, [
        {"BnF_ID": "A1", "actor_name": "Jean Dupont", "actor_death": "1650"},
    ])

    captured = {}

    def fake_search(name, birth_year, death_year, sleep):
        captured["birth_year"] = birth_year
        captured["death_year"] = death_year
        return []

    monkeypatch.setattr(wikidata, "search_wikidata_by_name", fake_search)

    wikidata.run_mapping(
        input_path=str(input_path),
        viaf_mapping_path=str(tmp_path / "missing_viaf.csv"),
        output_path=str(tmp_path / "output.csv"),
        report_path=str(tmp_path / "report.json"),
        threshold=0.85,
        sleep=0,
    )

    assert captured["birth_year"] is None
    assert captured["death_year"] == "1650"


def test_run_mapping_writes_monitor_checkpoint_per_actor_and_stops_cleanly(monkeypatch, tmp_path):
    wikidata = load_wikidata_module()

    input_path = tmp_path / "actors.csv"
    _write_actors_csv(input_path, [
        {"BnF_ID": "A1", "actor_name": "Jean Dupont", "actor_death": "1650"},
        {"BnF_ID": "A2", "actor_name": "Marie Curie", "actor_birth": "1867"},
    ])

    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(wikidata, "load_monitor_module", lambda monitor_script: fake_monitor)
    monkeypatch.setattr(wikidata, "search_wikidata_by_name", lambda *a, **kw: [])

    wikidata.run_mapping(
        input_path=str(input_path),
        viaf_mapping_path=str(tmp_path / "missing_viaf.csv"),
        output_path=str(tmp_path / "output.csv"),
        report_path=str(tmp_path / "report.json"),
        threshold=0.85,
        sleep=0,
        use_monitor=True,
    )

    assert len(fake_monitor.start_calls) == 1
    # one checkpoint per actor + one final "run completed" checkpoint
    assert len(fake_monitor.update_calls) == 2 + 1
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed Wikidata mapping run"
    assert fake_monitor.stop_calls == [True]


def test_run_mapping_skips_monitor_when_disabled(monkeypatch, tmp_path):
    wikidata = load_wikidata_module()

    input_path = tmp_path / "actors.csv"
    _write_actors_csv(input_path, [{"BnF_ID": "A1", "actor_name": "Jean Dupont"}])

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(wikidata, "load_monitor_module", fail_if_called)
    monkeypatch.setattr(wikidata, "search_wikidata_by_name", lambda *a, **kw: [])

    wikidata.run_mapping(
        input_path=str(input_path),
        viaf_mapping_path=str(tmp_path / "missing_viaf.csv"),
        output_path=str(tmp_path / "output.csv"),
        report_path=str(tmp_path / "report.json"),
        threshold=0.85,
        sleep=0,
        use_monitor=False,
    )


def test_load_monitor_module_resolves_real_monitor_script():
    """Smoke test for the module-1 monitor integration: the loader must
    resolve 00_monitor/monitor.py relative to the project root (mirroring
    load_monitor_env() in query_agents.R / query_editions.R) and expose the
    reusable embedded-monitoring API."""
    wikidata = load_wikidata_module()

    monitor = wikidata.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
