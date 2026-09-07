import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLACE_SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "publication_place" / "02_tgn_lookup" / "bnf_place_harmonisation.py"
)


def load_place_module():
    spec = importlib.util.spec_from_file_location("bnf_place_harmonisation", PLACE_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_editions_csv(path, rows):
    fieldnames = ["edition", "place"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _write_place_table(path, rows):
    fieldnames = ["city_harmonised", "tgn_id", "publication_place",
                 "publication_country", "longitude", "latitude"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _write_country_table(path, rows):
    fieldnames = ["country", "n", "country_harmonised"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── str_after_last_parentheses() ─────────────────────────────────────────────

def test_single_parentheses():
    place = load_place_module()
    assert place.str_after_last_parentheses("Paris (France)") == ["Paris", "France"]


def test_nested_parentheses_splits_on_last_group():
    place = load_place_module()
    result = place.str_after_last_parentheses("London (England) (UK)")
    assert result == ["London (England)", "UK"]


def test_no_parentheses():
    place = load_place_module()
    assert place.str_after_last_parentheses("Berlin") == ["Berlin", ""]


def test_empty_string():
    place = load_place_module()
    assert place.str_after_last_parentheses("") == ["", ""]


def test_none_value():
    place = load_place_module()
    assert place.str_after_last_parentheses(None) == ["", ""]


def test_whitespace_handling():
    place = load_place_module()
    result = place.str_after_last_parentheses("  Amsterdam  ( Netherlands )  ")
    assert result == ["Amsterdam", "Netherlands"]


def test_special_characters():
    place = load_place_module()
    result = place.str_after_last_parentheses("Saint-Étienne (France)")
    assert result == ["Saint-Étienne", "France"]


# ── harmonise_city_string() ───────────────────────────────────────────────────

def test_harmonise_city_string_strips_brackets_and_question_marks():
    place = load_place_module()
    assert place.harmonise_city_string("[Paris?]") == "Paris"


def test_harmonise_city_string_strips_leading_particles():
    place = load_place_module()
    assert place.harmonise_city_string("A Paris") == "Paris"
    assert place.harmonise_city_string("In London") == "London"


def test_harmonise_city_string_strips_commas():
    place = load_place_module()
    assert place.harmonise_city_string("Paris, France") == "Paris France"


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_splits_city_and_country_and_matches_tgn(tmp_path):
    place = load_place_module()

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [
        {"edition": "E1", "place": "Paris (France)"},
        {"edition": "E2", "place": "London (England)"},
    ])

    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [
        {"city_harmonised": "Paris", "tgn_id": "tgn:paris",
         "publication_place": "Paris", "publication_country": "France",
         "longitude": "2.35", "latitude": "48.85"},
    ])
    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(output_path), str(report_path), use_monitor=False)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["edition"]: r for r in csv.DictReader(f)}

    assert rows["E1"]["place_original"] == "Paris (France)"
    assert rows["E1"]["tgn_id"] == "tgn:paris"
    assert rows["E1"]["publication_place"] == "Paris"
    assert rows["E1"]["publication_country"] == "France"

    # London has no TGN match and no country-table entry -> unmatched, but
    # the raw place is still recorded.
    assert rows["E2"]["place_original"] == "London (England)"
    assert rows["E2"]["tgn_id"] == ""

    with open(report_path, encoding="utf-8") as f:
        stats = json.load(f)
    assert stats["total_editions"] == 2
    assert stats["tgn_matched"] == 1
    assert stats["unmatched"] == 1


def test_run_falls_back_to_country_table_when_tgn_has_no_country(tmp_path):
    """The colleague's split-place-into-city/country request: when the TGN
    lookup doesn't resolve, fall back to the country-only harmonisation
    table using the raw parenthetical text."""
    place = load_place_module()

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [
        {"edition": "E1", "place": "Lyon (Allemagne avant 1945)"},
    ])

    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [])  # no TGN match at all

    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [
        {"country": "Allemagne avant 1945", "n": "10", "country_harmonised": "France"},
    ])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(output_path), str(report_path), use_monitor=False)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["publication_country"] == "France"
    assert rows[0]["tgn_id"] == ""

    with open(report_path, encoding="utf-8") as f:
        stats = json.load(f)
    assert stats["country_fallback_used"] == 1
    assert stats["unmatched"] == 0


def test_run_sets_uncertainty_flags(tmp_path):
    place = load_place_module()

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [
        {"edition": "E1", "place": "[Paris?] (France)"},
    ])
    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [])
    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(output_path), str(report_path), use_monitor=False)

    with open(output_path, newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["place_uncertainty_brackets"] == "True"
    assert row["place_uncertainty_question_marks"] == "True"


def test_run_takes_first_place_seen_per_edition(tmp_path):
    place = load_place_module()

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [
        {"edition": "E1", "place": "Paris (France)"},
        {"edition": "E1", "place": "Lyon (France)"},  # duplicate edition row, ignored
    ])
    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [])
    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(output_path), str(report_path), use_monitor=False)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["place_original"] == "Paris (France)"


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


def test_run_writes_monitor_checkpoints_and_stops_cleanly(monkeypatch, tmp_path):
    place = load_place_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(place, "load_monitor_module", lambda monitor_script: fake_monitor)
    monkeypatch.setattr(place, "MONITOR_CHECKPOINT_EVERY", 1)

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [
        {"edition": "E1", "place": "Paris (France)"},
        {"edition": "E2", "place": "London (England)"},
    ])
    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [])
    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [])

    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(tmp_path / "out.csv"), str(tmp_path / "report.json"),
             use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    # one checkpoint per distinct place string (2) + one final checkpoint
    assert len(fake_monitor.update_calls) == 2 + 1
    assert fake_monitor.update_calls[-1] == "Completed publication-place harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    place = load_place_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(place, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "editions.csv"
    _write_editions_csv(input_path, [{"edition": "E1", "place": "Paris (France)"}])
    place_table_path = tmp_path / "place_table.csv"
    _write_place_table(place_table_path, [])
    country_table_path = tmp_path / "country_table.csv"
    _write_country_table(country_table_path, [])

    place.run(str(input_path), str(place_table_path), str(country_table_path),
             str(tmp_path / "out.csv"), str(tmp_path / "report.json"),
             use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    place = load_place_module()
    monitor = place.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
