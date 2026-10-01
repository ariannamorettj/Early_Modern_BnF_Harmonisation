from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Namespace
from rdflib.namespace import RDF
from rdflib.term import Identifier

_SH = Namespace("http://www.w3.org/ns/shacl#")


@dataclass(frozen=True)
class IndependentIssueExample:
    focus_node: str | None
    value_node: str | None
    result_path: str | None
    source_shape: str | None
    source_constraint_component: str | None
    result_message: str | None
    result_severity: str | None


@dataclass(frozen=True)
class IndependentIssue:
    issue_id: str
    count: int
    result_path: str | None
    source_shape: str | None
    source_constraint_component: str | None
    result_message: str | None
    result_severity: str | None
    example: IndependentIssueExample


@dataclass(frozen=True)
class IndependentIssueSummary:
    conforms: bool
    top_level_result_count: int
    leaf_result_count: int
    independent_issue_count: int
    issues: list[IndependentIssue]


@dataclass(frozen=True)
class _LeafResult:
    node: str
    focus_node: str | None
    value_node: str | None
    result_path: str | None
    source_shape: str | None
    source_constraint_component: str | None
    result_message: str | None
    result_severity: str | None


def _term_to_str(term: Identifier | None) -> str | None:
    return None if term is None else str(term)


def _result_nodes(report_graph: Graph) -> list[Identifier]:
    nodes: list[Identifier] = []
    for report in report_graph.subjects(RDF.type, _SH.ValidationReport):
        nodes.extend(report_graph.objects(report, _SH.result))
    return nodes


def _result_details(report_graph: Graph, result_node: Identifier) -> list[Identifier]:
    return list(report_graph.objects(result_node, _SH.detail))


def _leaf_results(report_graph: Graph, result_node: Identifier) -> Iterable[_LeafResult]:
    details = _result_details(report_graph, result_node)
    if details:
        for detail in details:
            yield from _leaf_results(report_graph, detail)
        return

    yield _LeafResult(
        node=str(result_node),
        focus_node=_term_to_str(report_graph.value(result_node, _SH.focusNode)),
        value_node=_term_to_str(report_graph.value(result_node, _SH.value)),
        result_path=_term_to_str(report_graph.value(result_node, _SH.resultPath)),
        source_shape=_term_to_str(report_graph.value(result_node, _SH.sourceShape)),
        source_constraint_component=_term_to_str(
            report_graph.value(result_node, _SH.sourceConstraintComponent)
        ),
        result_message=_term_to_str(report_graph.value(result_node, _SH.resultMessage)),
        result_severity=_term_to_str(report_graph.value(result_node, _SH.resultSeverity)),
    )


def _local_name(uri: str | None) -> str | None:
    if uri is None:
        return None
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def _normalize_source_shape(source_shape: str | None) -> str | None:
    """
    Keep only stable, meaningful shape identifiers.
    pySHACL often emits blank-node-like ids such as 'n90843768...':
    these must not be used for deduplication.
    """
    if source_shape is None:
        return None
    if source_shape.startswith(("http://", "https://", "urn:")):
        return source_shape
    return None


def _normalize_result_message(
    result_message: str | None,
    source_constraint_component: str | None,
) -> str | None:
    """
    Convert instance-specific messages into canonical problem labels.
    Raw SHACL messages often embed focus-node URIs, so they are not usable
    for structural deduplication.
    """
    component = _local_name(source_constraint_component)

    canonical = {
        "MinCountConstraintComponent": "Missing required value",
        "MaxCountConstraintComponent": "Too many values",
        "DatatypeConstraintComponent": "Incorrect datatype",
        "ClassConstraintComponent": "Incorrect class",
        "NodeConstraintComponent": "Linked node does not conform",
        "NodeKindConstraintComponent": "Incorrect node kind",
        "PatternConstraintComponent": "Value does not match required pattern",
        "MinLengthConstraintComponent": "Value shorter than required minimum",
        "MaxLengthConstraintComponent": "Value longer than allowed maximum",
        "UniqueLangConstraintComponent": "Duplicate language-tagged values",
        "ClosedConstraintComponent": "Unexpected property in closed shape",
        "HasValueConstraintComponent": "Required fixed value missing",
        "InConstraintComponent": "Value not in allowed set",
        "OrConstraintComponent": "Value does not satisfy any allowed alternative",
        "AndConstraintComponent": "Value does not satisfy all required constraints",
        "QualifiedMinCountConstraintComponent": "Too few qualified values",
        "QualifiedMaxCountConstraintComponent": "Too many qualified values",
    }

    if component in canonical:
        return canonical[component]

    if result_message is None:
        return None

    # Fallback: strip instance-specific URIs from the message.
    normalized = re.sub(r"<[^>]+>", "<NODE>", result_message)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _issue_signature(result: _LeafResult) -> tuple[str | None, ...]:
    normalized_shape = _normalize_source_shape(result.source_shape)
    normalized_message = _normalize_result_message(
        result.result_message,
        result.source_constraint_component,
    )

    return (
        result.source_constraint_component,
        result.result_path,
        normalized_shape,
        normalized_message,
        result.result_severity,
    )


def _issue_id(signature: tuple[str | None, ...]) -> str:
    normalized = "||".join(part or "" for part in signature)
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def summarize_independent_issues(report_graph: Graph) -> IndependentIssueSummary:
    top_level_nodes = _result_nodes(report_graph)
    leaf_results: list[_LeafResult] = []
    for node in top_level_nodes:
        leaf_results.extend(_leaf_results(report_graph, node))

    grouped: dict[tuple[str | None, ...], list[_LeafResult]] = {}
    for leaf in leaf_results:
        grouped.setdefault(_issue_signature(leaf), []).append(leaf)

    issues: list[IndependentIssue] = []
    for signature, group in grouped.items():
        example = group[0]
        issues.append(
            IndependentIssue(
                issue_id=_issue_id(signature),
                count=len(group),
                result_path=signature[1],
                source_shape=signature[2],
                source_constraint_component=signature[0],
                result_message=signature[3],
                result_severity=signature[4],
                example=IndependentIssueExample(
                    focus_node=example.focus_node,
                    value_node=example.value_node,
                    result_path=example.result_path,
                    source_shape=example.source_shape,
                    source_constraint_component=example.source_constraint_component,
                    result_message=example.result_message,
                    result_severity=example.result_severity,
                ),
            )
        )

    issues.sort(
        key=lambda issue: (
            -issue.count,
            issue.source_constraint_component or "",
            issue.result_path or "",
            issue.source_shape or "",
            issue.result_message or "",
        )
    )

    # NB: non usare Graph.value(None, _SH.conforms) - con rdflib 7.6.0 restituisce
    # None anche quando il triple esiste (bug di value() con subject=None sui
    # wildcard match), mentre objects() lo trova correttamente.
    conforms_term = next(iter(report_graph.objects(None, _SH.conforms)), None)
    conforms = str(conforms_term).lower() == "true"

    return IndependentIssueSummary(
        conforms=conforms,
        top_level_result_count=len(top_level_nodes),
        leaf_result_count=len(leaf_results),
        independent_issue_count=len(issues),
        issues=issues,
    )


def independent_issue_summary_to_dict(summary: IndependentIssueSummary) -> dict:
    return {
        "conforms": summary.conforms,
        "top_level_result_count": summary.top_level_result_count,
        "leaf_result_count": summary.leaf_result_count,
        "independent_issue_count": summary.independent_issue_count,
        "issues": [asdict(issue) for issue in summary.issues],
    }


def format_independent_issue_summary(summary: IndependentIssueSummary) -> str:
    lines = [
        f"Conforms: {summary.conforms}",
        f"Top-level validation results: {summary.top_level_result_count}",
        f"Leaf validation results: {summary.leaf_result_count}",
        f"Independent issue families: {summary.independent_issue_count}",
        "",
    ]

    for index, issue in enumerate(summary.issues, start=1):
        lines.extend(
            [
                f"[{index}] count={issue.count} issue_id={issue.issue_id}",
                f"  source_constraint_component: {issue.source_constraint_component}",
                f"  result_path: {issue.result_path}",
                f"  source_shape: {issue.source_shape}",
                f"  result_message: {issue.result_message}",
                f"  result_severity: {issue.result_severity}",
                "  example:",
                f"    focus_node: {issue.example.focus_node}",
                f"    value_node: {issue.example.value_node}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def write_independent_issue_outputs(
    summary: IndependentIssueSummary,
    *,
    json_path: str | Path | None = None,
    text_path: str | Path | None = None,
) -> None:
    if json_path is not None:
        json_target = Path(json_path)
        json_target.parent.mkdir(parents=True, exist_ok=True)
        json_target.write_text(
            json.dumps(independent_issue_summary_to_dict(summary), indent=2),
            encoding="utf-8",
        )
    if text_path is not None:
        text_target = Path(text_path)
        text_target.parent.mkdir(parents=True, exist_ok=True)
        text_target.write_text(format_independent_issue_summary(summary), encoding="utf-8")