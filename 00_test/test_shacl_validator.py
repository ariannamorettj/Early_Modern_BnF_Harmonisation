from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pyshacl")

# BnF: the package lives in 07_graph_materialisation/shacl_validation/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "07_graph_materialisation"))

from shacl_validation.validator import validate_graph


def _write_ontology(path: Path) -> None:
    path.write_text(
        '''
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix dc: <http://purl.org/dc/elements/1.1/> .
        @prefix ex: <http://example.org/> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Thing a owl:Class ;
          dc:description """The properties that can be used with this class are:
* ex:name -[1]-> rdfs:Literal""" .
        ''',
        encoding="utf-8",
    )


def test_validation_succeeds_for_conforming_graph() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ontology = Path(tmp_dir) / "ontology.ttl"
        data = Path(tmp_dir) / "data.ttl"
        _write_ontology(ontology)
        data.write_text(
            '''
            @prefix ex: <http://example.org/> .
            ex:item a ex:Thing ;
              ex:name "valid" .
            ''',
            encoding="utf-8",
        )

        result = validate_graph(data_source=data, ontology_source=ontology)
        assert result.conforms is True


def test_validation_fails_for_non_conforming_graph() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ontology = Path(tmp_dir) / "ontology.ttl"
        data = Path(tmp_dir) / "data.ttl"
        _write_ontology(ontology)
        data.write_text(
            '''
            @prefix ex: <http://example.org/> .
            ex:item a ex:Thing .
            ''',
            encoding="utf-8",
        )

        result = validate_graph(data_source=data, ontology_source=ontology)
        assert result.conforms is False
        assert "Constraint Violation" in result.results_text
