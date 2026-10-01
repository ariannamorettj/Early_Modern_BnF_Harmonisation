from __future__ import annotations

import sys
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

# BnF: the package lives in 07_graph_materialisation/shacl_validation/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "07_graph_materialisation"))

from shacl_validation.report_analysis import summarize_independent_issues

SH = Namespace("http://www.w3.org/ns/shacl#")
EX = Namespace("http://example.org/")


def _build_report_graph() -> Graph:
    g = Graph()
    report = BNode()
    r1 = BNode()
    r2 = BNode()
    d1 = BNode()
    d2 = BNode()
    r3 = BNode()

    g.add((report, RDF.type, SH.ValidationReport))
    g.add((report, SH.conforms, Literal(False, datatype=XSD.boolean)))
    g.add((report, SH.result, r1))
    g.add((report, SH.result, r2))
    g.add((report, SH.result, r3))

    for result_node, focus, value, detail in [
        (r1, EX.parent1, EX.activity1, d1),
        (r2, EX.parent2, EX.activity2, d2),
    ]:
        g.add((result_node, SH.sourceConstraintComponent, SH.NodeConstraintComponent))
        g.add((result_node, SH.resultPath, EX.consistsOf))
        g.add((result_node, SH.sourceShape, EX.ParentShape))
        g.add((result_node, SH.focusNode, focus))
        g.add((result_node, SH.value, value))
        g.add((result_node, SH.resultMessage, Literal("Value does not conform to Shape ex:ActivityShape")))
        g.add((result_node, SH.detail, detail))

    for detail_node, focus in [(d1, EX.activity1), (d2, EX.activity2)]:
        g.add((detail_node, SH.sourceConstraintComponent, SH.MinCountConstraintComponent))
        g.add((detail_node, SH.resultPath, EX.carriedOutBy))
        g.add((detail_node, SH.sourceShape, EX.ActivityShapeP14))
        g.add((detail_node, SH.focusNode, focus))
        g.add((detail_node, SH.resultMessage, Literal("Less than 1 values on ex:activity->ex:carriedOutBy")))
        g.add((detail_node, SH.resultSeverity, SH.Violation))

    g.add((r3, SH.sourceConstraintComponent, SH.MaxCountConstraintComponent))
    g.add((r3, SH.resultPath, EX.symbolicContent))
    g.add((r3, SH.sourceShape, EX.AppellationShapeP190))
    g.add((r3, SH.focusNode, EX.name1))
    g.add((r3, SH.resultMessage, Literal("More than 1 values on ex:name->ex:symbolicContent")))
    g.add((r3, SH.resultSeverity, SH.Violation))

    return g


def test_independent_issue_summary_deduplicates_leaf_problems() -> None:
    summary = summarize_independent_issues(_build_report_graph())

    assert summary.conforms is False
    assert summary.top_level_result_count == 3
    assert summary.leaf_result_count == 3
    assert summary.independent_issue_count == 2

    first, second = summary.issues
    assert first.count == 2
    assert first.result_path == str(EX.carriedOutBy)
    assert first.source_constraint_component == str(SH.MinCountConstraintComponent)
    assert first.example.focus_node == str(EX.activity1)

    assert second.count == 1
    assert second.result_path == str(EX.symbolicContent)
    assert second.source_constraint_component == str(SH.MaxCountConstraintComponent)
    assert second.example.focus_node == str(EX.name1)
