import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "06_mapping" / "04_merge_mappings.py"


def load_module():
    spec = importlib.util.spec_from_file_location("merge_mappings", SCRIPT_PATH)
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


def test_run_merge_adds_estc_actor_columns_and_tracks_coverage(tmp_path):
    m = load_module()

    actors_path = tmp_path / "actors.csv"
    _write_csv(actors_path, ["BnF_ID", "actor_name"], [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner"},
        {"BnF_ID": "A2", "actor_name": "Nobody"},
    ])

    estc_actors_path = tmp_path / "estc_actor_mapping.csv"
    _write_csv(estc_actors_path,
              ["BnF_ID", "estc_actor_id", "match_type", "confidence", "estc_actor_name"], [
        {"BnF_ID": "A1", "estc_actor_id": "viaf_101037334",
         "match_type": "viaf_id", "confidence": "1.0", "estc_actor_name": "Warner, Joseph"},
    ])

    viaf_path = tmp_path / "viaf_mapping.csv"
    _write_csv(viaf_path, ["BnF_ID", "viaf_id"], [])
    wikidata_path = tmp_path / "wikidata_mapping.csv"
    _write_csv(wikidata_path, ["BnF_ID", "qid"], [])
    editions_path = tmp_path / "editions.csv"
    _write_csv(editions_path, ["bnf_id"], [])
    estc_editions_path = tmp_path / "estc_mapping.csv"
    _write_csv(estc_editions_path, ["BnF_edition_id"], [])

    out_actors = tmp_path / "out_actors.csv"
    out_editions = tmp_path / "out_editions.csv"
    report_path = tmp_path / "report.json"

    m.run_merge(
        str(actors_path), str(viaf_path), str(wikidata_path),
        str(editions_path), str(estc_editions_path),
        str(out_actors), str(out_editions), str(report_path),
        estc_actors_path=str(estc_actors_path),
    )

    with open(out_actors, newline="", encoding="utf-8") as f:
        rows = {r["BnF_ID"]: r for r in csv.DictReader(f)}

    assert rows["A1"]["estc_actor_id"] == "viaf_101037334"
    assert rows["A1"]["estc_actor_match_type"] == "viaf_id"
    assert rows["A1"]["estc_actor_name"] == "Warner, Joseph"
    assert rows["A2"]["estc_actor_id"] == ""

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["actors"]["estc_actor_matched"] == 1
    assert report["actors"]["total"] == 2


def test_run_merge_keeps_ambiguous_estc_candidate_out_of_matched_id(tmp_path):
    """An ambiguous_* row carries a candidate estc_actor_id from
    05_map_estc_actors.py; it must land in the candidate columns, not in
    estc_actor_id, and must not be counted as matched."""
    m = load_module()

    actors_path = tmp_path / "actors.csv"
    _write_csv(actors_path, ["BnF_ID", "actor_name"], [
        {"BnF_ID": "A1", "actor_name": "Joseph Warner"},
        {"BnF_ID": "A2", "actor_name": "John Smith"},
    ])
    estc_actors_path = tmp_path / "estc_actor_mapping.csv"
    _write_csv(estc_actors_path,
              ["BnF_ID", "estc_actor_id", "match_type", "confidence", "estc_actor_name"], [
        {"BnF_ID": "A1", "estc_actor_id": "viaf_101037334",
         "match_type": "name_and_dates", "confidence": "0.9", "estc_actor_name": "Warner, Joseph"},
        {"BnF_ID": "A2", "estc_actor_id": "viaf_55",
         "match_type": "ambiguous_name_and_dates", "confidence": "0.5", "estc_actor_name": "Smith, John"},
    ])
    editions_path = tmp_path / "editions.csv"
    _write_csv(editions_path, ["bnf_id"], [])

    out_actors = tmp_path / "out_actors.csv"
    report_path = tmp_path / "report.json"
    m.run_merge(
        str(actors_path), str(tmp_path / "no_viaf.csv"), str(tmp_path / "no_wikidata.csv"),
        str(editions_path), str(tmp_path / "no_estc.csv"),
        str(out_actors), str(tmp_path / "out_editions.csv"), str(report_path),
        estc_actors_path=str(estc_actors_path),
    )

    with open(out_actors, newline="", encoding="utf-8") as f:
        rows = {r["BnF_ID"]: r for r in csv.DictReader(f)}
    assert rows["A1"]["estc_actor_id"] == "viaf_101037334"
    assert rows["A1"]["estc_actor_candidate_id"] == ""
    assert rows["A2"]["estc_actor_id"] == ""
    assert rows["A2"]["estc_actor_name"] == ""
    assert rows["A2"]["estc_actor_candidate_id"] == "viaf_55"
    assert rows["A2"]["estc_actor_candidate_name"] == "Smith, John"
    assert rows["A2"]["estc_actor_match_type"] == "ambiguous_name_and_dates"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["actors"]["estc_actor_matched"] == 1
    assert report["actors"]["estc_actor_ambiguous"] == 1


def test_run_merge_handles_missing_estc_actor_mapping_gracefully(tmp_path):
    """A merge run before 05_map_estc_actors.py has ever been run (no
    output file yet) must not fail — same as the existing VIAF/Wikidata
    behaviour when their files are absent."""
    m = load_module()

    actors_path = tmp_path / "actors.csv"
    _write_csv(actors_path, ["BnF_ID", "actor_name"], [{"BnF_ID": "A1", "actor_name": "Voltaire"}])

    editions_path = tmp_path / "editions.csv"
    _write_csv(editions_path, ["bnf_id"], [])

    out_actors = tmp_path / "out_actors.csv"
    out_editions = tmp_path / "out_editions.csv"
    report_path = tmp_path / "report.json"

    m.run_merge(
        str(actors_path), str(tmp_path / "no_viaf.csv"), str(tmp_path / "no_wikidata.csv"),
        str(editions_path), str(tmp_path / "no_estc.csv"),
        str(out_actors), str(out_editions), str(report_path),
        estc_actors_path=str(tmp_path / "no_estc_actors.csv"),
    )

    with open(out_actors, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["estc_actor_id"] == ""
