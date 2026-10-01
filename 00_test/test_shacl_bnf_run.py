"""BnF additions to the SHACL validator: N-Triples input, timestamped reports,
class coverage and the namespace guard (07_graph_materialisation/shacl_validation/)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyshacl")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "07_graph_materialisation"))

from shacl_validation import bnf_run  # noqa: E402
from shacl_validation.config import BNF_CHAD_AP_NAMESPACE, DEFAULT_PUBLIC_GRAPH_URL  # noqa: E402
from shacl_validation.validator import load_rdf_graph  # noqa: E402

OBJ = BNF_CHAD_AP_NAMESPACE
LRMOO_F3 = "http://iflastandards.info/ns/lrm/lrmoo/F3_Manifestation"

# A two-class schema in the BnF CHAD-AP namespace, documented the way the
# extractor expects (dc:description listing each class's properties).
ONTOLOGY = f'''
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obj: <{OBJ}> .

<https://w3id.org/dharc/ontology/chad-ap/object/development/14> a owl:Ontology ;
  owl:versionInfo "test" .

obj:Person a owl:Class ;
  dc:description """The properties that can be used with this class are:
* obj:isIdentifiedBy -[1..N]-> obj:Appellation""" .

obj:Appellation a owl:Class ;
  dc:description """The properties that can be used with this class are:
* obj:hasSymbolicContent -[1]-> rdfs:Literal""" .
'''

# N-Triples, like module 07's output: one valid person, one without a name,
# one appellation with two contents, and an edition the schema does not cover.
DATA = f'''<http://data.bnf.fr/ark:/12148/cbP1#about> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{OBJ}Person> .
<http://data.bnf.fr/ark:/12148/cbP1#about> <{OBJ}isIdentifiedBy> <http://data.bnf.fr/ark:/12148/cbP1#app> .
<http://data.bnf.fr/ark:/12148/cbP1#app> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{OBJ}Appellation> .
<http://data.bnf.fr/ark:/12148/cbP1#app> <{OBJ}hasSymbolicContent> "Henry Isaacson" .
<http://data.bnf.fr/ark:/12148/cbP2#about> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{OBJ}Person> .
<http://data.bnf.fr/ark:/12148/cbP3#about> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{OBJ}Person> .
<http://data.bnf.fr/ark:/12148/cbP3#about> <{OBJ}isIdentifiedBy> <http://data.bnf.fr/ark:/12148/cbP3#app> .
<http://data.bnf.fr/ark:/12148/cbP3#app> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{OBJ}Appellation> .
<http://data.bnf.fr/ark:/12148/cbP3#app> <{OBJ}hasSymbolicContent> "Gregory" .
<http://data.bnf.fr/ark:/12148/cbP3#app> <{OBJ}hasSymbolicContent> "G. Gregory" .
<http://data.bnf.fr/ark:/12148/cbE1#about> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{LRMOO_F3}> .
'''


@pytest.fixture
def example(tmp_path):
    ontology = tmp_path / "chad_ap_test.ttl"
    data = tmp_path / "graph.nt"
    ontology.write_text(ONTOLOGY, encoding="utf-8")
    data.write_text(DATA, encoding="utf-8")
    return ontology, data, tmp_path / "report" / "shacl"


def test_default_data_source_is_the_merged_sample_graph():
    assert DEFAULT_PUBLIC_GRAPH_URL.replace("\\", "/").endswith(
        "07_graph_materialisation/output/sample/knowledge-graph_merged.nt")


def test_load_rdf_graph_reads_n_triples(example):
    _, data, _ = example
    assert len(load_rdf_graph(data)) == 11


def test_run_validation_writes_timestamped_reports_and_coverage(example):
    ontology, data, report_dir = example
    summary = bnf_run.run_validation(data_source=data, ontology_source=ontology,
                                     report_dir=report_dir, timestamp="20261001T120000")

    assert summary["triples_validated"] == 11
    assert summary["conforms"] is False
    assert summary["version_info"] == "test"
    # P2 has no name (minCount), P3's appellation has two contents (maxCount).
    assert summary["leaf_result_count"] == 2
    assert summary["independent_issue_count"] == 2
    problems = {family["problem"] for family in summary["top_issue_families"]}
    assert problems == {"Missing required value", "Too many values"}

    status = {row["class"]: row["status"] for row in summary["coverage"]["classes"]}
    assert status == {
        OBJ + "Person": "targeted",
        OBJ + "Appellation": "reachable_via_sh_node",
        LRMOO_F3: "not_covered",
    }

    names = sorted(p.name for p in report_dir.iterdir())
    assert names == [f"shacl_20261001T120000_{n}" for n in
                     ("coverage.txt", "issues.json", "issues.txt", "report.txt", "shapes.ttl", "summary.json")]
    saved = json.loads((report_dir / "shacl_20261001T120000_summary.json").read_text(encoding="utf-8"))
    assert saved["conforms"] is False and saved["coverage"]["by_status"]["not_covered"] == 1


def test_run_validation_refuses_an_ontology_without_the_data_namespace(example, tmp_path):
    _, data, report_dir = example
    other = tmp_path / "other.ttl"
    other.write_text(ONTOLOGY.replace(OBJ, "https://example.org/another-version/"), encoding="utf-8")
    with pytest.raises(bnf_run.OntologyMismatchError):
        bnf_run.run_validation(data_source=data, ontology_source=other, report_dir=report_dir)
    assert not report_dir.exists()  # nothing written


def test_cli_exit_codes(example, tmp_path):
    ontology, data, report_dir = example
    args = ["--data-source", str(data), "--report-dir", str(report_dir)]
    assert bnf_run.main(args + ["--ontology-source", str(ontology)]) == 1  # does not conform
    assert bnf_run.main(args + ["--ontology-source", str(tmp_path / "missing.ttl")]) == 2
