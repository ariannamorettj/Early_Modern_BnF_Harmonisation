"""SHACL validation of a module 07 graph, with timestamped reports.

BnF addition (not in the upstream package): one command that generates the
shapes from the CHAD-AP schema, validates the graph with pySHACL, and writes
to 07_graph_materialisation/report/shacl/:

    shacl_<timestamp>_summary.json   conformance, counts, ontology version, coverage
    shacl_<timestamp>_report.txt     pySHACL's human-readable report
    shacl_<timestamp>_issues.json    violations grouped in independent families
    shacl_<timestamp>_issues.txt     (report_analysis.py), as JSON and as text
    shacl_<timestamp>_coverage.txt   classes of the graph reached by the shapes
    shacl_<timestamp>_shapes.ttl     the generated shapes

Before validating, it checks that the ontology contains the namespace the
BnF data use (config.BNF_CHAD_AP_NAMESPACE): shapes generated from another
CHAD-AP version would validate the data against a model it does not use.

Exit codes as in cli.py: 0 conforms, 1 does not conform (a valid result,
not an error), 2 the validation could not run.

Usage, from 07_graph_materialisation/:
    python -m shacl_validation [--data-source GRAPH.nt] [--ontology-source CHAD-AP.ttl]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from .aliases import ConstraintAliases, load_constraint_aliases
from .config import (
    BNF_CHAD_AP_NAMESPACE,
    DEFAULT_CHAD_AP_TTL_URL,
    DEFAULT_PUBLIC_GRAPH_URL,
    DEFAULT_REPORT_DIR,
)
from .coverage import class_coverage, format_class_coverage
from .extractor import ExtractionError, _is_url, create_shacl_shapes
from .report_analysis import summarize_independent_issues, write_independent_issue_outputs
from .validator import ValidationExecutionError, load_rdf_graph, validate_graph, write_validation_outputs


SH_NODE_SHAPE = URIRef("http://www.w3.org/ns/shacl#NodeShape")


class OntologyMismatchError(RuntimeError):
    """The ontology is missing, or does not contain the namespace of the data."""


def ontology_version(ontology: Graph) -> dict:
    """IRI and version of the owl:Ontology declared in the schema, if any."""
    for subject in ontology.subjects(RDF.type, OWL.Ontology):
        version_iri = ontology.value(subject, OWL.versionIRI)
        version_info = ontology.value(subject, OWL.versionInfo)
        return {
            "ontology_iri": str(subject),
            "version_iri": str(version_iri) if version_iri else None,
            "version_info": str(version_info) if version_info else None,
        }
    return {"ontology_iri": None, "version_iri": None, "version_info": None}


def _load_ontology(ontology_source: str, expected_namespace: str | None) -> Graph:
    if not _is_url(ontology_source) and not Path(ontology_source).exists():
        raise OntologyMismatchError(
            f"CHAD-AP schema not found: {ontology_source}. The BnF mappings use the "
            f"namespace {BNF_CHAD_AP_NAMESPACE} (CHAD-AP development/14), which no "
            "published CHAD-AP release contains; place that schema there or pass "
            "--ontology-source."
        )
    ontology = Graph()
    ontology.parse(ontology_source)
    if expected_namespace and not any(
        str(term).startswith(expected_namespace) for triple in ontology for term in triple
    ):
        raise OntologyMismatchError(
            f"{ontology_source} does not contain the namespace {expected_namespace} "
            "used by the data: its shapes would validate the graph against a "
            "different model."
        )
    return ontology


def run_validation(
    *,
    data_source: str | Path = DEFAULT_PUBLIC_GRAPH_URL,
    ontology_source: str | Path = DEFAULT_CHAD_AP_TTL_URL,
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    expected_namespace: str | None = BNF_CHAD_AP_NAMESPACE,
    aliases: ConstraintAliases | None = None,
    inference: str = "none",
    timestamp: str | None = None,
) -> dict:
    started = time.time()
    data_source, ontology_source = str(data_source), str(ontology_source)
    timestamp = timestamp or datetime.now().strftime("%Y%m%dT%H%M%S")
    ontology = _load_ontology(ontology_source, expected_namespace)

    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    out = {name: report_dir / f"shacl_{timestamp}_{name}" for name in
           ("summary.json", "report.txt", "issues.json", "issues.txt", "coverage.txt", "shapes.ttl")}
    shapes = create_shacl_shapes(ontology_source, aliases=aliases)
    shapes.serialize(destination=str(out["shapes.ttl"]), format="turtle", encoding="utf-8")

    data_graph = load_rdf_graph(data_source)
    coverage = class_coverage(data_graph, ontology_source)
    out["coverage.txt"].write_text(format_class_coverage(coverage), encoding="utf-8")

    result = validate_graph(
        data_source=data_source,
        ontology_source=ontology_source,
        shapes_source=out["shapes.ttl"],
        aliases=aliases,
        inference=inference,
    )
    write_validation_outputs(result, text_report_path=out["report.txt"])
    issues = summarize_independent_issues(result.results_graph)
    write_independent_issue_outputs(
        issues, json_path=out["issues.json"], text_path=out["issues.txt"],
    )

    summary = {
        "timestamp": timestamp,
        "data_source": data_source,
        "triples_validated": len(data_graph),
        "ontology_source": ontology_source,
        **ontology_version(ontology),
        "expected_namespace": expected_namespace,
        "node_shapes": len(set(shapes.subjects(RDF.type, SH_NODE_SHAPE))),
        "inference": inference,
        # Same keys as cli._write_summary.
        "conforms": result.conforms,
        "text_report": str(out["report.txt"]),
        "rdf_report": None,
        "top_level_result_count": issues.top_level_result_count,
        "leaf_result_count": issues.leaf_result_count,
        "independent_issue_count": issues.independent_issue_count,
        "independent_issues_json": str(out["issues.json"]),
        "independent_issues_text": str(out["issues.txt"]),
        "top_issue_families": [
            {"count": issue.count, "source_shape": issue.source_shape,
             "result_path": issue.result_path, "problem": issue.result_message}
            for issue in issues.issues[:5]
        ],
        "coverage": coverage,
        "coverage_text": str(out["coverage.txt"]),
        "shapes": str(out["shapes.ttl"]),
        "duration_seconds": round(time.time() - started, 1),
    }
    out["summary.json"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["summary_json"] = str(out["summary.json"])
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shacl_validation",
        description="SHACL validation of a BnF module 07 graph against CHAD-AP, "
                    "with timestamped reports in report/shacl/.",
    )
    parser.add_argument("--data-source", default=DEFAULT_PUBLIC_GRAPH_URL,
                        help="RDF graph to validate (default: the merged sample graph)")
    parser.add_argument("--ontology-source", default=DEFAULT_CHAD_AP_TTL_URL,
                        help="CHAD-AP schema the shapes are generated from")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--expected-namespace", default=BNF_CHAD_AP_NAMESPACE,
                        help="Namespace the ontology must contain; '' disables the check")
    parser.add_argument("--aliases-file",
                        help="JSON with property_aliases/target_aliases (default: the built-in CHAD-AP ones)")
    parser.add_argument("--disable-default-aliases", action="store_true")
    parser.add_argument("--inference", default="none", choices=["none", "rdfs", "owlrl", "both"])
    args = parser.parse_args(argv)

    if args.disable_default_aliases and not args.aliases_file:
        aliases = None
    else:
        aliases = load_constraint_aliases(args.aliases_file)

    try:
        summary = run_validation(
            data_source=args.data_source,
            ontology_source=args.ontology_source,
            report_dir=args.report_dir,
            expected_namespace=args.expected_namespace or None,
            aliases=aliases,
            inference=args.inference,
        )
    except (OntologyMismatchError, ExtractionError, ValidationExecutionError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Triples validated      : {summary['triples_validated']:,}")
    print(f"Ontology               : {summary['version_iri'] or summary['ontology_iri'] or summary['ontology_source']}")
    print(f"Conforms               : {summary['conforms']}")
    print(f"Violations (leaf)      : {summary['leaf_result_count']:,}")
    print(f"Issue families         : {summary['independent_issue_count']:,}")
    by_status = summary["coverage"]["by_status"]
    print("Classes in the graph   : " + ", ".join(f"{k} {v}" for k, v in by_status.items()))
    print(f"Summary                : {summary['summary_json']}")
    return 0 if summary["conforms"] else 1
