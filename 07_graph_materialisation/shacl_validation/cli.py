from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .aliases import load_constraint_aliases
from .config import DEFAULT_CHAD_AP_TTL_URL, DEFAULT_PUBLIC_GRAPH_URL
from .extractor import ExtractionError, create_shacl_shapes
from .report_analysis import summarize_independent_issues, write_independent_issue_outputs
from .validator import ValidationExecutionError, validate_graph, write_validation_outputs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chadkg",
        description="Standalone SHACL extraction and CHAD-KG validation toolkit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="Generate SHACL shapes from an ontology")
    extract.add_argument("input", help="Input ontology source: file path, directory, or URL")
    extract.add_argument("output", help="Output Turtle file for the generated SHACL shapes")
    extract.add_argument("--shapes-base", help="Custom base URI for generated shapes")
    extract.add_argument(
        "--aliases-file",
        help="Optional JSON file with property_aliases and target_aliases overrides",
    )
    extract.add_argument(
        "--disable-default-aliases",
        action="store_true",
        help="Disable the built-in CHAD-AP alias corrections",
    )

    validate = subparsers.add_parser(
        "validate",
        help="Validate an RDF graph with generated or pre-existing SHACL shapes",
    )
    validate.add_argument(
        "--data-source",
        default=DEFAULT_PUBLIC_GRAPH_URL,
        help="RDF graph to validate (file path or URL)",
    )
    validate.add_argument(
        "--ontology-source",
        default=DEFAULT_CHAD_AP_TTL_URL,
        help="Ontology/application profile used to generate shapes",
    )
    validate.add_argument(
        "--shapes-source",
        help="Optional existing SHACL file; if omitted, shapes are generated from the ontology",
    )
    validate.add_argument("--shapes-base", help="Custom base URI for generated shapes")
    validate.add_argument(
        "--aliases-file",
        help="Optional JSON file with property_aliases and target_aliases overrides",
    )
    validate.add_argument(
        "--disable-default-aliases",
        action="store_true",
        help="Disable the built-in CHAD-AP alias corrections",
    )
    validate.add_argument(
        "--inference",
        default="none",
        choices=["none", "rdfs", "owlrl", "both"],
        help="pySHACL inference mode",
    )
    validate.add_argument(
        "--text-report",
        help="Write the human-readable validation report to this file",
    )
    validate.add_argument(
        "--rdf-report",
        help="Write the RDF validation report to this file",
    )
    validate.add_argument(
        "--rdf-report-format",
        default="turtle",
        choices=["turtle", "xml", "json-ld", "nt", "n3"],
        help="Serialization format for the RDF validation report",
    )
    validate.add_argument(
        "--summary-json",
        help="Write a short JSON summary with the conformance result and report paths",
    )
    validate.add_argument(
        "--independent-issues-json",
        help="Write the deduplicated set of independent leaf-level issue families to this JSON file",
    )
    validate.add_argument(
        "--independent-issues-text",
        help="Write a human-readable summary of the independent issue families to this text file",
    )
    validate.add_argument("--abort-on-first", action="store_true")
    validate.add_argument("--allow-infos", action="store_true")
    validate.add_argument("--allow-warnings", action="store_true")
    validate.add_argument("--disable-meta-shacl", action="store_true")
    validate.add_argument("--disable-advanced", action="store_true")
    validate.add_argument("--debug", action="store_true")
    validate.add_argument("--do-owl-imports", action="store_true")

    run = subparsers.add_parser(
        "run",
        help="Generate shapes from CHAD-AP and validate the public CHAD-KG in one step",
    )
    run.add_argument(
        "--data-source",
        default=DEFAULT_PUBLIC_GRAPH_URL,
        help="RDF graph to validate (file path or URL)",
    )
    run.add_argument(
        "--ontology-source",
        default=DEFAULT_CHAD_AP_TTL_URL,
        help="Ontology/application profile used to generate shapes",
    )
    run.add_argument(
        "--shapes-output",
        default="build/chad_ap_shapes.ttl",
        help="Path where the generated SHACL shapes will be written",
    )
    run.add_argument(
        "--text-report",
        default="build/validation_report.txt",
        help="Human-readable validation report path",
    )
    run.add_argument(
        "--rdf-report",
        default="build/validation_report.ttl",
        help="RDF validation report path",
    )
    run.add_argument(
        "--summary-json",
        default="build/validation_summary.json",
        help="JSON summary path",
    )
    run.add_argument(
        "--independent-issues-json",
        default="build/independent_issues.json",
        help="JSON output for the deduplicated set of independent leaf-level issue families",
    )
    run.add_argument(
        "--independent-issues-text",
        default="build/independent_issues.txt",
        help="Text output for the deduplicated set of independent leaf-level issue families",
    )
    run.add_argument("--shapes-base", help="Custom base URI for generated shapes")
    run.add_argument(
        "--aliases-file",
        help="Optional JSON file with property_aliases and target_aliases overrides",
    )
    run.add_argument(
        "--disable-default-aliases",
        action="store_true",
        help="Disable the built-in CHAD-AP alias corrections",
    )
    run.add_argument(
        "--inference",
        default="none",
        choices=["none", "rdfs", "owlrl", "both"],
        help="pySHACL inference mode",
    )
    run.add_argument("--abort-on-first", action="store_true")
    run.add_argument("--allow-infos", action="store_true")
    run.add_argument("--allow-warnings", action="store_true")
    run.add_argument("--disable-meta-shacl", action="store_true")
    run.add_argument("--disable-advanced", action="store_true")
    run.add_argument("--debug", action="store_true")
    run.add_argument("--do-owl-imports", action="store_true")

    return parser



def _resolve_aliases(args: argparse.Namespace):
    if args.disable_default_aliases and not args.aliases_file:
        return None

    if args.disable_default_aliases and args.aliases_file:
        return load_constraint_aliases(args.aliases_file)

    if args.aliases_file:
        return load_constraint_aliases(args.aliases_file)

    return load_constraint_aliases()



def _write_summary(
    path: str | Path,
    *,
    conforms: bool,
    text_report: str | None,
    rdf_report: str | None,
    independent_issue_count: int | None = None,
    leaf_result_count: int | None = None,
    top_level_result_count: int | None = None,
    independent_issues_json: str | None = None,
    independent_issues_text: str | None = None,
) -> None:
    summary = {
        "conforms": conforms,
        "text_report": text_report,
        "rdf_report": rdf_report,
    }
    if top_level_result_count is not None:
        summary["top_level_result_count"] = top_level_result_count
    if leaf_result_count is not None:
        summary["leaf_result_count"] = leaf_result_count
    if independent_issue_count is not None:
        summary["independent_issue_count"] = independent_issue_count
    if independent_issues_json is not None:
        summary["independent_issues_json"] = independent_issues_json
    if independent_issues_text is not None:
        summary["independent_issues_text"] = independent_issues_text
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")



def _cmd_extract(args: argparse.Namespace) -> int:
    aliases = _resolve_aliases(args)
    shacl_graph = create_shacl_shapes(
        args.input,
        shapes_base=args.shapes_base,
        aliases=aliases,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shacl_graph.serialize(destination=str(output), format="turtle", encoding="utf-8")
    return 0



def _cmd_validate(args: argparse.Namespace) -> int:
    aliases = _resolve_aliases(args)
    result = validate_graph(
        data_source=args.data_source,
        ontology_source=args.ontology_source,
        shapes_source=args.shapes_source,
        shapes_base=args.shapes_base,
        aliases=aliases,
        inference=args.inference,
        abort_on_first=args.abort_on_first,
        allow_infos=args.allow_infos,
        allow_warnings=args.allow_warnings,
        meta_shacl=not args.disable_meta_shacl,
        advanced=not args.disable_advanced,
        debug=args.debug,
        do_owl_imports=args.do_owl_imports,
    )
    write_validation_outputs(
        result,
        text_report_path=args.text_report,
        rdf_report_path=args.rdf_report,
        rdf_report_format=args.rdf_report_format,
    )
    issue_summary = None
    if args.independent_issues_json or args.independent_issues_text or args.summary_json:
        issue_summary = summarize_independent_issues(result.results_graph)
        write_independent_issue_outputs(
            issue_summary,
            json_path=args.independent_issues_json,
            text_path=args.independent_issues_text,
        )
    if args.summary_json:
        _write_summary(
            args.summary_json,
            conforms=result.conforms,
            text_report=args.text_report,
            rdf_report=args.rdf_report,
            independent_issue_count=(issue_summary.independent_issue_count if issue_summary else None),
            leaf_result_count=(issue_summary.leaf_result_count if issue_summary else None),
            top_level_result_count=(issue_summary.top_level_result_count if issue_summary else None),
            independent_issues_json=args.independent_issues_json,
            independent_issues_text=args.independent_issues_text,
        )
    print(result.results_text)
    return 0 if result.conforms else 1



def _cmd_run(args: argparse.Namespace) -> int:
    aliases = _resolve_aliases(args)
    shapes_output = Path(args.shapes_output)
    shapes_output.parent.mkdir(parents=True, exist_ok=True)
    shacl_graph = create_shacl_shapes(
        args.ontology_source,
        shapes_base=args.shapes_base,
        aliases=aliases,
    )
    shacl_graph.serialize(destination=str(shapes_output), format="turtle", encoding="utf-8")

    result = validate_graph(
        data_source=args.data_source,
        ontology_source=args.ontology_source,
        shapes_source=shapes_output,
        aliases=aliases,
        inference=args.inference,
        abort_on_first=args.abort_on_first,
        allow_infos=args.allow_infos,
        allow_warnings=args.allow_warnings,
        meta_shacl=not args.disable_meta_shacl,
        advanced=not args.disable_advanced,
        debug=args.debug,
        do_owl_imports=args.do_owl_imports,
    )
    write_validation_outputs(
        result,
        text_report_path=args.text_report,
        rdf_report_path=args.rdf_report,
        rdf_report_format="turtle",
    )
    issue_summary = summarize_independent_issues(result.results_graph)
    write_independent_issue_outputs(
        issue_summary,
        json_path=args.independent_issues_json,
        text_path=args.independent_issues_text,
    )
    _write_summary(
        args.summary_json,
        conforms=result.conforms,
        text_report=args.text_report,
        rdf_report=args.rdf_report,
        independent_issue_count=issue_summary.independent_issue_count,
        leaf_result_count=issue_summary.leaf_result_count,
        top_level_result_count=issue_summary.top_level_result_count,
        independent_issues_json=args.independent_issues_json,
        independent_issues_text=args.independent_issues_text,
    )
    print(result.results_text)
    return 0 if result.conforms else 1



def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "extract":
            raise SystemExit(_cmd_extract(args))
        if args.command == "validate":
            raise SystemExit(_cmd_validate(args))
        if args.command == "run":
            raise SystemExit(_cmd_run(args))
        raise SystemExit(2)
    except (ExtractionError, ValidationExecutionError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
