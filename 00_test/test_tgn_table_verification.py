import csv
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TGN_DIR = PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation" / "publication_place" / "02_tgn_lookup"
TGN = "http://vocab.getty.edu/tgn/"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TGN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BORDEAUX_ENTRY = {"publication_place": "Bordeaux", "publication_country": "France",
                  "tgn_id": TGN + "7659881", "latitude": "48.677158", "longitude": "1.09928"}
HAMLET = {"label": "Bordeaux", "type": "inhabited places",
          "parent": "Centre-Val de Loire, France, Europe, World", "lat": "48.677158", "long": "1.09928"}
HOMONYMS = [
    {"p": TGN + "7659881", **{k: HAMLET[k] for k in ("type", "parent", "lat", "long")}},
    {"p": TGN + "7008161", "type": "inhabited places",
     "parent": "Nouvelle-Aquitaine, France, Europe, World", "lat": "44.840439", "long": "-0.5805"},
    {"p": TGN + "2061983", "type": "transport points",
     "parent": "Dawes, Nebraska, United States, North and Central America, World", "lat": "42.7", "long": "-102.8"},
]


def test_assess_proposes_the_core_settlement_for_a_minor_homonym():
    v = load("verify_tgn_table")
    result = v.assess(BORDEAUX_ENTRY, HAMLET, HOMONYMS)
    assert result["flags"] == "core_homonym"
    assert result["proposed_tgn_id"] == TGN + "7008161"
    assert "Nebraska" not in result["same_country_homonyms"]


def test_assess_ignores_core_records_that_are_not_settlements():
    """Halle: the core-range record is a 'national districts' entry."""
    v = load("verify_tgn_table")
    entry = {"publication_place": "Halle", "publication_country": "Germany",
             "tgn_id": TGN + "1036898", "latitude": "51.5", "longitude": "12"}
    record = {"label": "Halle", "type": "inhabited places",
              "parent": "Saxony-Anhalt, Germany, Europe, World", "lat": "51.5", "long": "12.0"}
    homonyms = [{"p": TGN + "1036898", **{k: record[k] for k in ("type", "parent", "lat", "long")}},
                {"p": TGN + "7017168", "type": "national districts",
                 "parent": "Saxony-Anhalt, Germany, Europe, World", "lat": "52.45", "long": "6.9167"}]
    assert v.assess(entry, record, homonyms)["flags"] == ""


def test_lucene_term_avoids_query_syntax():
    v = load("verify_tgn_table")
    assert v.lucene_term("'s-Hertogenbosch") == "Hertogenbosch"
    assert v.lucene_term("La Rochelle") == "Rochelle"


def _write_table(path, rows):
    header = '"city_harmonised","tgn_id","publication_place","publication_country","longitude","latitude"'
    path.write_text(header + "\r\n" + "".join(r + "\r\n" for r in rows), encoding="utf-8", newline="")


def test_fix_rewrites_only_corrected_lines_and_is_idempotent(tmp_path):
    f = load("fix_tgn_table")
    table = tmp_path / "table.csv"
    untouched = '"Alençon","<http://vocab.getty.edu/tgn/7008621>","Alençon","France",.093111,48.434758'
    _write_table(table, [
        '"Burdigalae","<http://vocab.getty.edu/tgn/7659881>","Bordeaux","France",1.09928,48.677158',
        untouched,
        '"Philadelphie","<http://vocab.getty.edu/tgn/7014406>","Philadelphia","United States",39.95,-75.15',
        '"Allemagne",NA,NA,"Germany",NA,NA',
    ])
    verification = tmp_path / "verification.csv"
    fields = ["publication_place", "publication_country", "tgn_id", "flags", "tgn_lat", "tgn_long",
              "table_lat", "table_long", "proposed_tgn_id", "proposed_lat", "proposed_long"]
    with open(verification, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerow({"publication_place": "Bordeaux", "publication_country": "France",
                    "tgn_id": TGN + "7659881", "flags": "core_homonym", "tgn_lat": "48.677158",
                    "tgn_long": "1.09928", "table_lat": "48.677158", "table_long": "1.09928",
                    "proposed_tgn_id": TGN + "7008161", "proposed_lat": "44.840439",
                    "proposed_long": "-0.5805"})
        w.writerow({"publication_place": "Philadelphia", "publication_country": "United States",
                    "tgn_id": TGN + "7014406", "flags": "coords_mismatch", "tgn_lat": "39.95",
                    "tgn_long": "-75.15", "table_lat": "-75.15", "table_long": "39.95",
                    "proposed_tgn_id": "", "proposed_lat": "", "proposed_long": ""})

    log = f.run(table, verification, tmp_path / "log.csv")
    assert [r["correction"] for r in log] == ["core_homonym", "swapped_coordinates"]
    lines = table.read_bytes().decode("utf-8").split("\r\n")
    assert lines[1] == '"Burdigalae","<http://vocab.getty.edu/tgn/7008161>","Bordeaux","France",-0.5805,44.840439'
    assert lines[2] == untouched
    assert lines[3].endswith("-75.15,39.95")
    assert lines[4] == '"Allemagne",NA,NA,"Germany",NA,NA'

    before = table.read_bytes()
    assert f.run(table, verification, tmp_path / "log.csv") == []
    assert table.read_bytes() == before


def test_assess_makes_no_proposal_when_several_core_settlements_share_the_name():
    """Beauvais: two core-range settlements (Essonne, Hauts-de-France)."""
    v = load("verify_tgn_table")
    entry = {"publication_place": "Beauvais", "publication_country": "France",
             "tgn_id": TGN + "7663579", "latitude": "48.716609", "longitude": "0.898201"}
    record = {"label": "Beauvais", "type": "inhabited places",
              "parent": "Normandie, France, Europe, World", "lat": "48.716609", "long": "0.898201"}
    homonyms = [{"p": TGN + "7008979", "type": "inhabited places",
                 "parent": "Île-de-France, France, Europe, World", "lat": "48.53", "long": "2.05"},
                {"p": TGN + "7010570", "type": "inhabited places",
                 "parent": "Hauts-de-France, France, Europe, World", "lat": "49.43", "long": "2.08"}]
    result = v.assess(entry, record, homonyms)
    assert result["flags"] == "core_homonym_ambiguous"
    assert result["proposed_tgn_id"] == ""


def test_manual_override_wins_and_is_idempotent(tmp_path):
    f = load("fix_tgn_table")
    table = tmp_path / "table.csv"
    _write_table(table, ['"Beauvais","<http://vocab.getty.edu/tgn/7008979>","Beauvais","France",2.050736,48.536206'])
    verification = tmp_path / "verification.csv"
    verification.write_text("publication_place,publication_country,tgn_id,flags,tgn_lat,tgn_long,"
                            "table_lat,table_long,proposed_tgn_id,proposed_lat,proposed_long\n",
                            encoding="utf-8")
    overrides = tmp_path / "overrides.csv"
    overrides.write_text("publication_place,publication_country,tgn_id,longitude,latitude,reason\n"
                         "Beauvais,France,http://vocab.getty.edu/tgn/7010570,2.083333,49.433333,city\n",
                         encoding="utf-8")
    log = f.run(table, verification, tmp_path / "log.csv", overrides)
    assert [r["correction"] for r in log] == ["manual_override"]
    assert table.read_text(encoding="utf-8").splitlines()[1].endswith('7010570>","Beauvais","France",2.083333,49.433333')
    assert f.run(table, verification, tmp_path / "log.csv", overrides) == []
