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


# ── load_viaf_mapping() / match_actor() enrichment ───────────────────────────

def test_load_viaf_mapping_reads_bnf_id_to_viaf_id(tmp_path):
    m = load_module()
    path = tmp_path / "viaf_mapping.csv"
    _write_csv(path, ["BnF_ID", "viaf_id", "match_type"], [
        {"BnF_ID": "A1", "viaf_id": "67750325", "match_type": "name"},
    ])
    assert m.load_viaf_mapping(str(path)) == {"A1": "67750325"}


def test_load_viaf_mapping_missing_file_returns_empty(tmp_path):
    m = load_module()
    assert m.load_viaf_mapping(str(tmp_path / "nope.csv")) == {}


def test_match_actor_uses_supplementary_viaf_id_from_mapping():
    """The BnF row itself carries no VIAF link, but 01_map_viaf.py found one
    by name — that supplementary ID should still bridge to the ESTC actor."""
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Someone Else"}  # no VIAF link on the row
    estc_actors = [{
        "actor_id": "viaf_67750325", "viaf_link": "https://viaf.org/viaf/67750325",
        "name_unified": "Charles I", "is_organization": "FALSE",
    }]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2,
                           viaf_mapping={"A1": "67750325"})
    assert result["match_type"] == "viaf_id"
    assert result["estc_actor_id"] == "viaf_67750325"


def test_match_actor_ignores_viaf_mapping_for_other_actors():
    m = load_module()
    bnf_row = {"actor": "A1", "actor_name": "Nobody Matching"}
    estc_actors = [{"actor_id": "e1", "name_unified": "Someone Unrelated", "is_organization": "FALSE"}]
    viaf_index, name_index = m.build_estc_indexes(estc_actors)
    result = m.match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window=2,
                           viaf_mapping={"A2": "99999"})  # keyed to a different actor
    assert result["match_type"] == "unmatched"


# ── load_dedup_mapping() / collapse_by_canonical() ───────────────────────────

def test_load_dedup_mapping_reads_actor_to_canonical(tmp_path):
    m = load_module()
    path = tmp_path / "dedup.csv"
    _write_csv(path, ["actor_uri", "canonical_actor_uri"], [
        {"actor_uri": "A1", "canonical_actor_uri": "A1"},
        {"actor_uri": "A2", "canonical_actor_uri": "A1"},
    ])
    assert m.load_dedup_mapping(str(path)) == {"A1": "A1", "A2": "A1"}


def test_load_dedup_mapping_missing_file_returns_empty(tmp_path):
    m = load_module()
    assert m.load_dedup_mapping(str(tmp_path / "nope.csv")) == {}


def test_collapse_by_canonical_keeps_highest_confidence_match():
    m = load_module()
    results = [
        {"BnF_ID": "A1", "match_type": "unmatched", "confidence": 0.0, "notes": ""},
        {"BnF_ID": "A2", "match_type": "viaf_id", "confidence": 1.0, "notes": ""},
    ]
    collapsed = m.collapse_by_canonical(results, {"A1": "A1", "A2": "A1"})
    assert len(collapsed) == 1
    assert collapsed[0]["BnF_ID"] == "A1"
    assert collapsed[0]["match_type"] == "viaf_id"
    assert "A2" in collapsed[0]["notes"]


def test_collapse_by_canonical_prefers_higher_confidence_within_same_match_type():
    m = load_module()
    results = [
        {"BnF_ID": "A1", "match_type": "ambiguous_name_and_dates", "confidence": 0.5, "notes": ""},
        {"BnF_ID": "A2", "match_type": "ambiguous_name_and_dates", "confidence": 0.9, "notes": ""},
    ]
    collapsed = m.collapse_by_canonical(results, {"A1": "A1", "A2": "A1"})
    assert collapsed[0]["confidence"] == 0.9


def test_collapse_by_canonical_is_noop_when_mapping_empty():
    m = load_module()
    results = [{"BnF_ID": "A1", "match_type": "unmatched", "confidence": 0.0, "notes": ""}]
    assert m.collapse_by_canonical(results, {}) == results


def test_collapse_by_canonical_leaves_unmapped_actors_untouched():
    m = load_module()
    results = [{"BnF_ID": "A9", "match_type": "unmatched", "confidence": 0.0, "notes": ""}]
    collapsed = m.collapse_by_canonical(results, {"A1": "A0"})  # A9 absent from mapping
    assert collapsed == results


# ── split_by_confidence() ─────────────────────────────────────────────────────

def test_split_by_confidence_buckets_correctly():
    m = load_module()
    results = [
        {"BnF_ID": "A1", "match_type": "viaf_id"},
        {"BnF_ID": "A2", "match_type": "name_and_dates"},
        {"BnF_ID": "A3", "match_type": "ambiguous_name_only"},
        {"BnF_ID": "A4", "match_type": "ambiguous_name_and_dates"},
        {"BnF_ID": "A5", "match_type": "unmatched"},
    ]
    confident, review = m.split_by_confidence(results)
    assert [r["BnF_ID"] for r in confident] == ["A1", "A2"]
    assert [r["BnF_ID"] for r in review] == ["A3", "A4"]


def test_split_by_confidence_excludes_unmatched_from_both():
    m = load_module()
    results = [{"BnF_ID": "A1", "match_type": "unmatched"}]
    confident, review = m.split_by_confidence(results)
    assert confident == []
    assert review == []


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

    full_path = tmp_path / "private" / "full.csv"
    output_path, report_path = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out" / "mapping.csv"),
        str(tmp_path / "report" / "report.json"), full_output_path=str(full_path),
    )

    # Published file: only the match columns, no unmatched rows.
    with open(output_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = {r["BnF_ID"]: r for r in reader}
    assert reader.fieldnames == m.PUBLIC_FIELDS
    assert "estc_viaf_link" not in reader.fieldnames and "notes" not in reader.fieldnames
    assert list(rows) == ["A1"]
    assert rows["A1"]["match_type"] == "name_and_dates"
    assert rows["A1"]["estc_actor_name"] == "Warner, Joseph"
    assert rows["A1"]["estc_birth_year"] == "1717"

    # Full mapping (kept out of git): every actor, every column.
    with open(full_path, newline="", encoding="utf-8") as f:
        full = {r["BnF_ID"]: r for r in csv.DictReader(f)}
    assert set(full["A1"].keys()) == set(m.OUTPUT_FIELDS)
    assert full["A2"]["match_type"] == "unmatched"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["total_bnf_actor_records"] == 2
    assert report["distinct_actors_after_dedup"] == 2
    assert report["duplicates_collapsed"] == 0
    assert report["by_match_type"]["name_and_dates"] == 1
    assert report["by_match_type"]["unmatched"] == 1


def test_run_mapping_writes_confident_and_review_subset_files(tmp_path):
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner",
         "actor_birth": "1717", "actor_death": "1801"},  # -> name_and_dates
        {"BnF_ID": "A2", "actor_name": "Jean Petit"},     # -> ambiguous_name_only
        {"BnF_ID": "A3", "actor_name": "Nobody Matching"},  # -> unmatched
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [
        {"actor_id": "e1", "name_unified": "Warner, Joseph", "is_organization": "FALSE",
         "year_birth": "1717", "year_death": "1801"},
        {"actor_id": "e2", "name_unified": "Petit, Jean", "is_organization": "FALSE"},
    ])

    full_path = tmp_path / "private" / "full.csv"
    output_path, _ = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out" / "mapping.csv"),
        str(tmp_path / "report" / "report.json"), full_output_path=str(full_path),
    )

    confident_path = m._with_suffix(output_path, "_confident")
    review_path = m._with_suffix(output_path, "_review")

    with open(confident_path, newline="", encoding="utf-8") as f:
        confident_rows = list(csv.DictReader(f))
    assert [r["BnF_ID"] for r in confident_rows] == ["A1"]

    with open(review_path, newline="", encoding="utf-8") as f:
        review_rows = list(csv.DictReader(f))
    assert [r["BnF_ID"] for r in review_rows] == ["A2"]

    with open(output_path, newline="", encoding="utf-8") as f:
        published = [r["BnF_ID"] for r in csv.DictReader(f)]
    assert published == ["A1", "A2"]  # matched + ambiguous, no unmatched A3
    with open(full_path, newline="", encoding="utf-8") as f:
        full_rows = list(csv.DictReader(f))
    assert len(full_rows) == 3  # unmatched A3 still present in the full mapping


def test_run_mapping_with_dedup_mapping_collapses_duplicate_bnf_actors(tmp_path):
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        # A1 and A2 are the same real person under two BnF URIs: A1 alone
        # has no dates to match on, A2 does.
        {"BnF_ID": "A1", "actor_name": "Joseph Warner"},
        {"BnF_ID": "A2", "actor_name": "Joseph Warner",
         "actor_birth": "1717", "actor_death": "1801"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [
        {"actor_id": "e1", "name_unified": "Warner, Joseph", "is_organization": "FALSE",
         "year_birth": "1717", "year_death": "1801"},
    ])
    dedup_path = tmp_path / "dedup.csv"
    _write_csv(dedup_path, ["actor_uri", "canonical_actor_uri"], [
        {"actor_uri": "A1", "canonical_actor_uri": "A1"},
        {"actor_uri": "A2", "canonical_actor_uri": "A1"},
    ])

    output_path, report_path = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"),
        dedup_mapping_path=str(dedup_path),
    )

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["BnF_ID"] == "A1"
    assert rows[0]["match_type"] == "name_and_dates"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["total_bnf_actor_records"] == 2
    assert report["distinct_actors_after_dedup"] == 1
    assert report["duplicates_collapsed"] == 1


def test_run_mapping_without_dedup_mapping_path_keeps_duplicates_separate(tmp_path):
    """dedup_mapping_path defaults to None programmatically (matching this
    module's monitoring convention) — duplicates are not collapsed unless a
    path is explicitly given."""
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner"},
        {"BnF_ID": "A2", "actor_name": "Joseph Warner",
         "actor_birth": "1717", "actor_death": "1801"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [])

    full_path = tmp_path / "full.csv"
    m.run_mapping(str(bnf_path), str(estc_path), str(tmp_path / "out.csv"),
                  str(tmp_path / "report.json"), full_output_path=str(full_path))
    with open(full_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_run_mapping_with_viaf_mapping_finds_matches_bnf_data_alone_would_miss(tmp_path):
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Someone Else"},  # no VIAF link on the raw row
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [
        {"actor_id": "viaf_67750325", "viaf_link": "https://viaf.org/viaf/67750325",
         "name_unified": "Charles I", "is_organization": "FALSE"},
    ])
    viaf_path = tmp_path / "viaf_mapping.csv"
    _write_csv(viaf_path, ["BnF_ID", "viaf_id"], [{"BnF_ID": "A1", "viaf_id": "67750325"}])

    output_path, _ = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"),
        viaf_mapping_path=str(viaf_path),
    )
    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["match_type"] == "viaf_id"


# ── format_human_report() ────────────────────────────────────────────────────

def test_format_human_report_contains_key_numbers():
    m = load_module()
    stats = {
        "unmatched": 81994, "viaf_id": 5291,
        "ambiguous_name_only": 5193, "name_and_dates": 282,
        "ambiguous_name_and_dates": 20,
    }
    text = m.format_human_report(stats, total=92780)
    assert "92,780" in text
    assert "5,291" in text
    assert "81,994" in text
    assert "6.01%" in text  # (5291+282)/92780 confident


def test_format_human_report_handles_zero_total():
    m = load_module()
    text = m.format_human_report({}, total=0)
    assert "0.00%" in text


def test_run_mapping_writes_human_readable_txt_report_alongside_json(tmp_path):
    m = load_module()
    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner",
         "actor_birth": "1717", "actor_death": "1801"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [
        {"actor_id": "e1", "name_unified": "Warner, Joseph", "is_organization": "FALSE",
         "year_birth": "1717", "year_death": "1801"},
    ])

    _, report_path = m.run_mapping(
        str(bnf_path), str(estc_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"),
    )

    txt_path = report_path[:-len(".json")] + ".txt"
    assert Path(txt_path).exists()
    text = Path(txt_path).read_text(encoding="utf-8")
    assert "ESTC ACTOR-AUTHORITY MATCHING REPORT" in text


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


def test_run_mapping_writes_monitor_checkpoint_periodically_and_at_end(monkeypatch, tmp_path):
    """Checkpoints fire every MONITOR_CHECKPOINT_EVERY actors, not one per
    actor (that was the previous, much slower behaviour) — verified here by
    lowering the cadence to 2 so a 3-actor run produces exactly two
    progress checkpoints (at record 2, and at the final record 3) plus the
    completion checkpoint."""
    m = load_module()
    monkeypatch.setattr(m, "MONITOR_CHECKPOINT_EVERY", 2)
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(m, "load_monitor_module", lambda monitor_script: fake_monitor)

    bnf_path = tmp_path / "bnf.csv"
    _write_csv(bnf_path, BNF_FIELDS, [
        {"BnF_ID": "A1", "actor_name": "Voltaire"},
        {"BnF_ID": "A2", "actor_name": "Nobody"},
        {"BnF_ID": "A3", "actor_name": "Someone Else"},
    ])
    estc_path = tmp_path / "estc_actors.csv"
    _write_csv(estc_path, ESTC_FIELDS, [])

    m.run_mapping(str(bnf_path), str(estc_path), str(tmp_path / "out.csv"),
                 str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # record 2, record 3 (final), completion
    assert "A2" in fake_monitor.update_calls[0]
    assert "A3" in fake_monitor.update_calls[1]
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
