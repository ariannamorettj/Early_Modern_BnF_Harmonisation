import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "06_mapping" / "05_map_estc_actors.py"

BNF_FIELDS = [
    "BnF_ID", "actor_name", "actor_first_name", "actor_last_name",
    "actor_birth", "actor_death", "actor_link_exact", "actor_link_close",
]
ESTC_FIELDS = [
    "actor_id", "actor_id_type", "viaf_link", "is_organization",
    "name_unified", "name_first", "name_last", "year_birth", "year_death",
]


def load_module():
    spec = importlib.util.spec_from_file_location("map_estc_actors", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── name_tokens() / order-invariance ─────────────────────────────────────────

def test_name_tokens_is_order_invariant_across_naming_conventions():
    m = load_module()
    assert m.name_tokens("Joseph Warner") == m.name_tokens("Warner, Joseph")


def test_name_tokens_empty_for_blank():
    m = load_module()
    assert m.name_tokens("") == frozenset()
    assert m.name_tokens("N/A") == frozenset()


# ── extract_viaf_id() ─────────────────────────────────────────────────────────

def test_extract_viaf_id_from_uri():
    m = load_module()
    assert m.extract_viaf_id("https://viaf.org/viaf/67750325") == "67750325"
    assert m.extract_viaf_id("<http://viaf.org/viaf/41141574/>") == "41141574"


def test_extract_viaf_id_none_when_absent():
    m = load_module()
    assert m.extract_viaf_id("<http://www.idref.fr/156722380>") is None


def test_estc_viaf_id_falls_back_to_actor_id_when_link_missing():
    m = load_module()
    row = {"actor_id": "viaf_67750325", "actor_id_type": "viaf", "viaf_link": ""}
    assert m.estc_viaf_id(row) == "67750325"


# ── dates_compatible() ────────────────────────────────────────────────────────

def test_dates_compatible_true_within_window():
    m = load_module()
    assert m.dates_compatible(1622, 1673, 1622, 1674, window=2) is True


def test_dates_compatible_false_outside_window():
    m = load_module()
    assert m.dates_compatible(1622, 1673, 1500, 1550, window=2) is False


def test_dates_compatible_none_when_incomparable():
    m = load_module()
    assert m.dates_compatible(None, None, 1622, 1673, window=2) is None


# ── match_actor() ─────────────────────────────────────────────────────────────

def test_match_actor_viaf_id_bridge_takes_priority():
    m = load_module()
    bnf_row = {
        "actor": "A1", "actor_name": "Someone Else",
        "actor_link_exact": "<https://viaf.org/viaf/67750325>",
    }
    estc_actors = [{
        "actor_id": "viaf_67750325", "viaf_link": "https://viaf.org/viaf/67750325",
        "name_unified": "Charles I", "is_organization": "FALSE",
        "year_birth": "1600", "year_death": "1649",
    }]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "viaf_id"
    assert result["confidence"] == 1.0
    assert result["estc_actor_id"] == "viaf_67750325"


def test_match_actor_name_and_dates_single_candidate():
    m = load_module()
    bnf_row = {
        "actor": "A1", "actor_name": "Joseph Warner",
        "actor_birth": "1717", "actor_death": "1801",
    }
    estc_actors = [{
        "actor_id": "viaf_101037334", "name_unified": "Warner, Joseph",
        "name_first": "Joseph", "name_last": "Warner", "is_organization": "FALSE",
        "year_birth": "1717", "year_death": "1801",
    }]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "name_and_dates"
    assert result["estc_actor_id"] == "viaf_101037334"


def test_match_actor_conflicting_dates_are_discarded_not_matched():
    """Same name, clearly different lifespans -> not the same person."""
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Jean Petit", "actor_birth": "1622", "actor_death": "1673"}
    estc_actors = [{
        "actor_id": "e1", "name_unified": "Petit, Jean", "is_organization": "FALSE",
        "year_birth": "1400", "year_death": "1450",
    }]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "unmatched"


def test_match_actor_ambiguous_when_no_date_evidence():
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Jean Petit"}
    estc_actors = [{
        "actor_id": "e1", "name_unified": "Petit, Jean", "is_organization": "FALSE",
    }]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "ambiguous_name_only"


def test_match_actor_ambiguous_when_multiple_candidates_pass_dates():
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Jean Petit", "actor_birth": "1622", "actor_death": "1673"}
    estc_actors = [
        {"actor_id": "e1", "name_unified": "Petit, Jean", "is_organization": "FALSE",
         "year_birth": "1622", "year_death": "1673"},
        {"actor_id": "e2", "name_unified": "Petit, Jean", "is_organization": "FALSE",
         "year_birth": "1623", "year_death": "1673"},
    ]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "ambiguous_name_and_dates"
    assert "e1" in result["notes"] and "e2" in result["notes"]


def test_match_actor_unmatched_when_no_name_overlap():
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Voltaire"}
    estc_actors = [{"actor_id": "e1", "name_unified": "Petit, Jean", "is_organization": "FALSE"}]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2)
    assert result["match_type"] == "unmatched"


# ── load_bnf_actors() dual-schema support ────────────────────────────────────

def test_load_bnf_actors_accepts_both_id_schemas(tmp_path):
    m = load_module()
    path = tmp_path / "mixed.csv"
    _write_csv(path, ["actor", "BnF_ID", "actor_name"], [
        {"actor": "A1", "actor_name": "Voltaire"},
    ])
    rows = m.load_bnf_actors(str(path))
    assert rows[0]["actor"] == "A1"

    path2 = tmp_path / "optimised.csv"
    _write_csv(path2, ["BnF_ID", "actor_name"], [{"BnF_ID": "B1", "actor_name": "Voltaire"}])
    rows2 = m.load_bnf_actors(str(path2))
    assert rows2[0]["actor"] == "B1"


# ── load_estc_actors() excludes organisations ────────────────────────────────

def test_load_estc_actors_excludes_organisations(tmp_path):
    m = load_module()
    path = tmp_path / "estc_actors.csv"
    _write_csv(path, ESTC_FIELDS, [
        {"actor_id": "e1", "name_unified": "A Person", "is_organization": "FALSE"},
        {"actor_id": "e2", "name_unified": "A Company", "is_organization": "TRUE"},
    ])
    rows = m.load_estc_actors(str(path))
    assert [r["actor_id"] for r in rows] == ["e1"]


# ── run_mapping() end-to-end ──────────────────────────────────────────────────

def test_run_mapping_writes_csv_and_report_with_expected_schema(tmp_path):
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner",
         "actor_birth": "1717", "actor_death": "1801"},
        {"BnF_ID": "A2", "actor_name": "Nobody Matching"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [
        {"actor_id": "e1", "name_unified": "Warner, Joseph", "is_organization": "FALSE",
         "year_birth": "1717", "year_death": "1801"},
    ])

    output_path, report_path = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out" / "mapping.csv"),
        str(tmp_path / "report" / "report.json"),
    )

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["BnF_ID"]: r for r in csv.DictReader(f)}
    assert set(rows["A1"].keys()) == set(m.OUTPUT_FIELDS)
    assert rows["A1"]["match_type"] == "name_and_dates"
    assert rows["A2"]["match_type"] == "unmatched"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["total_bnf_actors"] == 2
    assert report["by_match_type"]["name_and_dates"] == 1
    assert report["by_match_type"]["unmatched"] == 1


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


def test_run_mapping_writes_monitor_checkpoint_per_actor_and_stops_cleanly(monkeypatch, tmp_path):
    m = load_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(m, "load_monitor_module", lambda monitor_script: fake_monitor)

    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Voltaire"},
        {"BnF_ID": "A2", "actor_name": "Nobody"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [])

    m.run_mapping(str(bnf_path), str(estc_path), str(tmp_path / "out.csv"),
                 str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed ESTC actor mapping run"
    assert fake_monitor.stop_calls == [True]


def test_run_mapping_skips_monitor_when_disabled(monkeypatch, tmp_path):
    m = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(m, "load_monitor_module", fail_if_called)

    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [{"BnF_ID": "A1", "actor_name": "Voltaire"}])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [])

    m.run_mapping(str(bnf_path), str(estc_path), str(tmp_path / "out.csv"),
                 str(tmp_path / "report.json"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    m = load_module()
    monitor = m.load_monitor_module()
    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
