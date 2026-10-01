import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "06_mapping"))

import resumable  # noqa: E402


def load_module():
    spec = importlib.util.spec_from_file_location("map_viaf", PROJECT_ROOT / "06_mapping" / "01_map_viaf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Trimmed from the live record https://viaf.org/viaf/sourceID/BNF|10017347
CLUSTER = {"ns1:VIAFCluster": {
    "ns1:viafID": 17211219,
    "ns1:birthDate": "0", "ns1:deathDate": "1726",
    "ns1:mainHeadings": {"ns1:data": [
        {"ns1:sources": {"ns1:s": "ISNI"}, "ns1:text": "Gentil, François O.Cart"},
        {"ns1:sources": {"ns1:s": ["NUKAT", "BNF"]}, "ns1:text": "Le Gentil, François (16..-1726)"},
    ]},
    "ns1:sources": {"ns1:source": [
        {"nsid": "http://catalogue.bnf.fr/ark:/12148/cb10017347j", "content": "BNF|10017347"},
        {"nsid": 145626717, "content": "SUDOC|145626717"},
        {"nsid": "Q112420240", "content": "WKP|Q112420240"},
        {"nsid": "n  80126267", "content": "LC|n  80126267"},
        {"nsid": "0000000080959991", "content": "ISNI|0000000080959991"},
    ]},
}}


def test_bnf_source_id_from_ark():
    m = load_module()
    assert m.bnf_source_id("<http://data.bnf.fr/ark:/12148/cb10017347j#about>") == "10017347"
    assert m.bnf_source_id("http://data.bnf.fr/ark:/12148/cb11928669x") == "11928669"
    assert m.bnf_source_id("not an ark") is None


def test_parse_cluster_prefers_the_bnf_heading_and_collects_links():
    m = load_module()
    c = m.parse_cluster(CLUSTER)
    assert c["viaf_id"] == "17211219"
    assert c["viaf_name"] == "Le Gentil, François (16..-1726)"
    assert c["birth_date"] == "" and c["death_date"] == "1726"
    assert c["wikidata_id"] == "Q112420240"
    assert c["idref_id"] == "145626717"
    assert c["isni"] == "0000000080959991"
    assert c["lc_id"] == "n80126267"


def test_similarity_is_order_invariant():
    m = load_module()
    assert m.similarity("François Le Gentil", "Le Gentil, François (16..-1726)") == 1.0
    assert m.similarity("Voltaire", "Rousseau, Jean-Jacques") < 0.85


def _fake_fetch(responses):
    """fetch_json stand-in: URL substring -> response (dict, None, or Exception)."""
    calls = []

    def fetch(url, sleep):
        calls.append(url)
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return None
    return fetch, calls


def test_map_actor_tries_bnf_source_id_first(monkeypatch):
    m = load_module()
    fetch, calls = _fake_fetch({"sourceID/BNF%7C10017347": CLUSTER})
    monkeypatch.setattr(m, "fetch_json", fetch)
    rec = m.map_actor({"BnF_ID": "<http://data.bnf.fr/ark:/12148/cb10017347j#about>",
                       "actor_link_exact": "<http://viaf.org/viaf/999/>"}, 0.85, 0)
    assert rec["match_type"] == "bnf_source_id" and rec["viaf_id"] == "17211219"
    assert len(calls) == 1


def test_map_actor_falls_back_to_existing_viaf_link(monkeypatch):
    m = load_module()
    fetch, _ = _fake_fetch({"viaf/17211219": CLUSTER})
    monkeypatch.setattr(m, "fetch_json", fetch)
    rec = m.map_actor({"BnF_ID": "<http://data.bnf.fr/ark:/12148/cb99999999j#about>",
                       "actor_link_close": "<http://viaf.org/viaf/17211219/>"}, 0.85, 0)
    assert rec["match_type"] == "viaf_link"


def _write_actors(path, ids):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["BnF_ID", "actor_name"])
        w.writeheader()
        for i in ids:
            w.writerow({"BnF_ID": f"<http://data.bnf.fr/ark:/12148/cb{i}j#about>", "actor_name": ""})


def test_run_defers_transient_errors_and_resumes(monkeypatch, tmp_path):
    """A network failure leaves the actor out of the file (not a false
    'unmatched'); the next run processes only what is missing."""
    m = load_module()
    inp, out, rep = tmp_path / "in.csv", tmp_path / "out.csv", tmp_path / "rep.json"
    _write_actors(inp, ["10000001", "10000002", "10000003"])

    fetch, _ = _fake_fetch({"BNF%7C10000001": CLUSTER,
                            "BNF%7C10000002": m.TransientError("HTTP 503")})
    monkeypatch.setattr(m, "fetch_json", fetch)
    stats = m.run_mapping(str(inp), str(out), str(rep), 0.85, 0)
    assert stats["written"] == 2 and stats["deferred_this_run"] == 1
    assert stats["bnf_source_id"] == 1 and stats["unmatched"] == 1

    fetch2, calls2 = _fake_fetch({"BNF%7C10000002": CLUSTER})
    monkeypatch.setattr(m, "fetch_json", fetch2)
    stats = m.run_mapping(str(inp), str(out), str(rep), 0.85, 0)
    assert all("10000002" in c for c in calls2)  # only the deferred actor is queried
    assert stats["written"] == 3 and stats["bnf_source_id"] == 2
    assert json.loads(rep.read_text())["written"] == 3


def test_resumable_writer_drops_a_half_written_last_line(tmp_path):
    path = tmp_path / "out.csv"
    path.write_bytes(b"BnF_ID,viaf_id\r\nA1,1\r\nA2,2\r\nA3,")  # power cut mid-row
    with resumable.ResumableCsvWriter(str(path), ["BnF_ID", "viaf_id"], "BnF_ID") as w:
        assert w.done_keys == {"A1", "A2"}
        w.write({"BnF_ID": "A3", "viaf_id": "3"})
    rows = resumable.read_rows(str(path))
    assert [r["BnF_ID"] for r in rows] == ["A1", "A2", "A3"]


def test_resumable_writer_refuses_a_file_with_other_columns(tmp_path):
    path = tmp_path / "out.csv"
    path.write_text("BnF_ID,old_column\nA1,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        resumable.ResumableCsvWriter(str(path), ["BnF_ID", "viaf_id"], "BnF_ID")
    w = resumable.ResumableCsvWriter(str(path), ["BnF_ID", "viaf_id"], "BnF_ID", restart=True)
    assert w.done_keys == set()
    w.close()
