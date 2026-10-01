from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from rdflib import Namespace, URIRef
from rdflib.namespace import RDF

# BnF: the package lives in 07_graph_materialisation/shacl_validation/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "07_graph_materialisation"))

from shacl_validation.aliases import ConstraintAliases
from shacl_validation.config import DEFAULT_SHAPES_BASE
from shacl_validation.extractor import create_shacl_shapes

SH = Namespace("http://www.w3.org/ns/shacl#")


def test_basic_single_file_shape_creation() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ontology = Path(tmp_dir) / "test.ttl"
        ontology.write_text(
            '''
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix dc: <http://purl.org/dc/elements/1.1/> .
            @prefix ex: <http://example.org/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            ex:Thing a owl:Class ;
              dc:description """The properties that can be used with this class are:
* ex:name -[1]-> rdfs:Literal
* ex:related -[0..N]-> ex:OtherThing""" .

            ex:OtherThing a owl:Class ;
              dc:description """The properties that can be used with this class are:
* ex:code -[1]-> rdfs:Literal""" .
            ''',
            encoding="utf-8",
        )
        shacl_graph = create_shacl_shapes(ontology)

        thing_shape = URIRef("http://example.org/shapes/ThingShape")
        assert (thing_shape, RDF.type, SH.NodeShape) in shacl_graph


def test_modular_shape_creation_preserves_root_behavior() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir) / "ontology"
        agent = base / "agent"
        agent.mkdir(parents=True)
        (agent / "skg-o.ttl").write_text(
            '''
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix dc: <http://purl.org/dc/elements/1.1/> .
            @prefix foaf: <http://xmlns.com/foaf/0.1/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            foaf:Agent a owl:Class ;
              dc:description """The properties that can be used with this class are:
* foaf:name -[0..1]-> rdfs:Literal""" .
            ''',
            encoding="utf-8",
        )

        shacl_graph = create_shacl_shapes(base)
        shape_uri = URIRef(DEFAULT_SHAPES_BASE + "agent/AgentShape")
        assert (shape_uri, RDF.type, SH.NodeShape) in shacl_graph
        assert any(
            obj == URIRef("http://xmlns.com/foaf/0.1/Agent")
            for obj in shacl_graph.objects(shape_uri, SH.targetClass)
        )


def test_aliases_can_correct_documentation_typos() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ontology = Path(tmp_dir) / "chadish.ttl"
        ontology.write_text(
            '''
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix dc: <http://purl.org/dc/elements/1.1/> .
            @prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
            @prefix lrmoo: <http://iflastandards.info/ns/lrm/lrmoo/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            lrmoo:F28_Expression_Creation a owl:Class ;
              dc:description """The properties that can be used with this class are:
* crm:R32_used_general_technique -[0..N]-> crm:E55_Type
* lrmoo:R19_created_a_realisation_of -[1]-> lrmoo:F1_Item""" .

            crm:E55_Type a owl:Class .
            lrmoo:F1_Work a owl:Class ;
              dc:description """The properties that can be used with this class are:
* rdfs:label -[0..1]-> rdfs:Literal""" .
            ''',
            encoding="utf-8",
        )
        aliases = ConstraintAliases(
            property_aliases={"crm:R32_used_general_technique": "crm:P32_used_general_technique"},
            target_aliases={"lrmoo:F1_Item": "lrmoo:F1_Work"},
        )

        shacl_graph = create_shacl_shapes(ontology, aliases=aliases)
        creation_shape = URIRef("http://example.org/shapes/F28_Expression_CreationShape")
        property_shapes = list(shacl_graph.objects(creation_shape, SH.property))
        paths = {shacl_graph.value(prop_shape, SH.path) for prop_shape in property_shapes}
        assert URIRef("http://www.cidoc-crm.org/cidoc-crm/P32_used_general_technique") in paths
        assert any(
            shacl_graph.value(prop_shape, SH.node)
            == URIRef("http://example.org/shapes/F1_WorkShape")
            for prop_shape in property_shapes
        )


def test_shapes_for_an_ontology_iri_ending_in_a_number_can_be_parsed_back() -> None:
    # BnF: ".../development/14" used to give the invalid Turtle prefix "14_sh".
    from rdflib import Graph

    with tempfile.TemporaryDirectory() as tmp_dir:
        ontology = Path(tmp_dir) / "dev14.ttl"
        ontology.write_text(
            '''
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix dc: <http://purl.org/dc/elements/1.1/> .
            @prefix ex: <http://example.org/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            <http://example.org/development/14> a owl:Ontology .
            ex:Thing a owl:Class ;
              dc:description """The properties that can be used with this class are:
* ex:name -[1]-> rdfs:Literal""" .
            ''',
            encoding="utf-8",
        )
        turtle = create_shacl_shapes(ontology).serialize(format="turtle")
        assert len(Graph().parse(data=turtle, format="turtle")) > 0
