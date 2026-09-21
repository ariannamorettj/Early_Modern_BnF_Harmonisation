import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEDUP_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_name" / "01_heuristic_rules" / "actors_deduplication.py"
)

CORE_FIELDNAMES = [
    "actor", "actor_name", "actor_first_name", "actor_last_name",
    "actor_birth", "actor_death", "actor_start", "actor_end",
    "actor_country", "actor_language", "actor_gender", "actor_profession",
    "actor_link_exact", "actor_link_close",
]


def load_dedup_module():
    spec = importlib.util.spec_from_file_location("actors_deduplication", DEDUP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CORE_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in CORE_FIELDNAMES}, **row})


# ── normalise_name() ─────────────────────────────────────────────────────────

def test_normalise_name_collapses_whitespace_and_punctuation():
    dd = load_dedup_module()
    assert dd.normalise_name("  Jean   Racine, ") == dd.normalise_name("jean.racine")


def test_normalise_name_empty_for_blank():
    dd = load_dedup_module()
    assert dd.normalise_name("") == ""
    assert dd.normalise_name("N/A") == ""


# ── load_actors() / get_actor_id() ───────────────────────────────────────────

def test_get_actor_id_prefers_actor_column():
    dd = load_dedup_module()
    assert dd.get_actor_id({"actor": "A1", "BnF_ID": "B1"}) == "A1"


def test_get_actor_id_falls_back_to_bnf_id_column():
    """Regression test: the module-5 optimised-subset schema (gen_subset_optm.py
    output) uses 'BnF_ID', not 'actor'. Silently returning no rows for this
    schema (as an earlier version of this script did) produces a mapping with
    zero collisions on a real ~93k-actor subset without raising any error."""
    dd = load_dedup_module()
    assert dd.get_actor_id({"BnF_ID": "B1"}) == "B1"


def test_get_actor_id_empty_when_neither_column_present():
    dd = load_dedup_module()
    assert dd.get_actor_id({"actor_name": "Voltaire"}) == ""


def test_load_actors_accepts_bnf_id_schema(tmp_path):
    dd = load_dedup_module()
    csv_path = tmp_path / "bnf_actors_optimised.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["BnF_ID", "actor_name"])
        writer.writeheader()
        writer.writerow({"BnF_ID": "B1", "actor_name": "Moliere"})

    actors = dd.load_actors(str(csv_path))
    assert len(actors) == 1
    assert actors[0]["actor"] == "B1"


# ── build_name_groups() ──────────────────────────────────────────────────────

def test_build_name_groups_drops_unique_names():
    dd = load_dedup_module()
    actors = [
        {"actor": "A1", "actor_name": "Voltaire"},
        {"actor": "A2", "actor_name": "Jean Racine"},
    ]
    groups = dd.build_name_groups(actors)
    assert groups == {}


def test_build_name_groups_keeps_collisions():
    dd = load_dedup_module()
    actors = [
        {"actor": "A1", "actor_name": "Jean Racine"},
        {"actor": "A2", "actor_name": "jean racine"},
        {"actor": "A3", "actor_name": "Voltaire"},
    ]
    groups = dd.build_name_groups(actors)
    assert list(groups.keys()) == ["JEAN RACINE"]
    assert len(groups["JEAN RACINE"]) == 2


# ── compute_evidence() ───────────────────────────────────────────────────────

def test_compute_evidence_shared_external_link():
    dd = load_dedup_module()
    a = {"actor_link_exact": "<http://viaf.org/viaf/1>", "actor_link_close": ""}
    b = {"actor_link_exact": "", "actor_link_close": "<http://viaf.org/viaf/1>"}
    assert dd.compute_evidence(a, b) == {"shared_external_link"}


def test_compute_evidence_matching_dates():
    dd = load_dedup_module()
    a = {"actor_birth": "1622-01-15", "actor_death": "1673-02-17"}
    b = {"actor_birth": "1622-01-15", "actor_death": "1673-02-17"}
    assert dd.compute_evidence(a, b) == {"matching_dates"}


def test_compute_evidence_none_when_dates_partial():
    dd = load_dedup_module()
    a = {"actor_birth": "1622-01-15", "actor_death": ""}
    b = {"actor_birth": "1622-01-15", "actor_death": ""}
    assert dd.compute_evidence(a, b) == set()


def test_compute_evidence_empty_when_nothing_shared():
    dd = load_dedup_module()
    a = {"actor_birth": "1622-01-15", "actor_death": "1673-02-17", "actor_link_exact": "<X>"}
    b = {"actor_birth": "1600-01-01", "actor_death": "1650-01-01", "actor_link_exact": "<Y>"}
    assert dd.compute_evidence(a, b) == set()


# ── dedup_group() ─────────────────────────────────────────────────────────────

def test_dedup_group_merges_on_shared_link():
    dd = load_dedup_module()
    rows = [
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1>"},
        {"actor": "A2", "actor_link_close": "<http://viaf.org/viaf/1>"},
    ]
    result = dd.dedup_group("MOLIERE", rows, max_pairwise_group_size=200)
    assert not result["oversized"]
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["match_type"] == "shared_external_link"
    assert result["clusters"][0]["confidence"] == "high"
    assert result["ambiguous"] == []


def test_dedup_group_merges_on_matching_dates():
    dd = load_dedup_module()
    rows = [
        {"actor": "A1", "actor_birth": "1622-01-15", "actor_death": "1673-02-17"},
        {"actor": "A2", "actor_birth": "1622-01-15", "actor_death": "1673-02-17"},
    ]
    result = dd.dedup_group("MOLIERE", rows, max_pairwise_group_size=200)
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["match_type"] == "matching_dates"


def test_dedup_group_leaves_ambiguous_pairs_unmerged():
    dd = load_dedup_module()
    rows = [
        {"actor": "A1"},
        {"actor": "A2"},
    ]
    result = dd.dedup_group("JEAN PETIT", rows, max_pairwise_group_size=200)
    assert result["clusters"] == []
    assert sorted(result["ambiguous"]) == ["A1", "A2"]


def test_dedup_group_reports_oversized_group_without_comparing():
    dd = load_dedup_module()
    rows = [{"actor": f"A{i}"} for i in range(5)]
    result = dd.dedup_group("COMMON NAME", rows, max_pairwise_group_size=3)
    assert result["oversized"] is True
    assert result["clusters"] == []
    assert sorted(result["ambiguous"]) == [f"A{i}" for i in range(5)]


def test_dedup_group_partial_merge_leaves_third_member_ambiguous():
    dd = load_dedup_module()
    rows = [
        {"actor": "A1", "actor_link_exact": "<http://viaf.org/viaf/1>"},
        {"actor": "A2", "actor_link_exact": "<http://viaf.org/viaf/1>"},
        {"actor": "A3"},
    ]
    result = dd.dedup_group("SAME NAME", rows, max_pairwise_group_size=200)
    assert len(result["clusters"]) == 1
    assert sorted(result["clusters"][0]["members"], key=lambda r: r["actor"])[0]["actor"] == "A1"
    assert result["ambiguous"] == ["A3"]


# ── _pick_canonical() ─────────────────────────────────────────────────────────

def test_pick_canonical_prefers_richest_record():
    dd = load_dedup_module()
    members = [
        {"actor": "Z1", "actor_name": "Moliere"},
        {"actor": "A1", "actor_name": "Moliere", "actor_birth": "1622-01-15",
         "actor_death": "1673-02-17"},
    ]
    assert dd._pick_canonical(members) == "A1"


def test_pick_canonical_tie_breaks_lexicographically():
    dd = load_dedup_module()
    members = [{"actor": "Z1"}, {"actor": "A1"}]
    assert dd._pick_canonical(members) == "A1"


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_mapping_and_report_with_expected_schema(tmp_path):
    dd = load_dedup_module()
    input_path = tmp_path / "actors_ready.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_name": "Moliere", "actor_link_exact": "<http://viaf.org/viaf/1>"},
        {"actor": "A2", "actor_name": "Moliere", "actor_link_close": "<http://viaf.org/viaf/1>"},
        {"actor": "A3", "actor_name": "Jean Petit"},
        {"actor": "A4", "actor_name": "Jean Petit"},
        {"actor": "A5", "actor_name": "Voltaire"},
    ])

    output_path, report_path = dd.run(
        str(input_path), str(tmp_path / "out"), report_dir=str(tmp_path / "report"),
    )

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {row["actor_uri"]: row for row in csv.DictReader(f)}

    assert set(rows.keys()) == {"A1", "A2", "A3", "A4"}
    assert set(rows["A1"].keys()) == {
        "actor_uri", "cluster_id", "canonical_actor_uri", "is_canonical",
        "match_type", "confidence", "normalised_name",
    }
    assert rows["A1"]["match_type"] == "shared_external_link"
    assert rows["A1"]["canonical_actor_uri"] == rows["A2"]["canonical_actor_uri"]
    assert rows["A3"]["match_type"] == "ambiguous_name_only"
    assert rows["A4"]["match_type"] == "ambiguous_name_only"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["stats"]["clusters_merged"] == 1
    assert report["stats"]["actors_merged"] == 2
    assert report["stats"]["actors_ambiguous"] == 2
    assert "JEAN PETIT" in report["ambiguous_groups"]


def test_run_respects_max_pairwise_group_size(tmp_path):
    dd = load_dedup_module()
    input_path = tmp_path / "actors_ready.csv"
    _write_actor_csv(input_path, [
        {"actor": f"A{i}", "actor_name": "Common Name"} for i in range(5)
    ])

    output_path, report_path = dd.run(
        str(input_path), str(tmp_path / "out"), report_dir=str(tmp_path / "report"),
        max_pairwise_group_size=3,
    )

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["oversized_groups"] == {"COMMON NAME": 5}

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(r["match_type"] == "group_too_large_to_compare" for r in rows)


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


def test_run_writes_monitor_checkpoint_per_name_group_and_stops_cleanly(monkeypatch, tmp_path):
    dd = load_dedup_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(dd, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "actors_ready.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_name": "Moliere", "actor_link_exact": "<http://viaf.org/viaf/1>"},
        {"actor": "A2", "actor_name": "Moliere", "actor_link_close": "<http://viaf.org/viaf/1>"},
        {"actor": "A3", "actor_name": "Voltaire (unique)"},
    ])

    dd.run(str(input_path), str(tmp_path / "out"), report_dir=str(tmp_path / "report"),
           use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 1 + 1  # one name-group with a collision + final
    assert "MOLIERE" in fake_monitor.update_calls[0]
    assert fake_monitor.update_calls[-1] == "Completed actors_deduplication run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    dd = load_dedup_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(dd, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "actors_ready.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_name": "Voltaire"}])

    dd.run(str(input_path), str(tmp_path / "out"), report_dir=str(tmp_path / "report"),
           use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    dd = load_dedup_module()
    monitor = dd.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
