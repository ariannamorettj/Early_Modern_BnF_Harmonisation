from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pyshacl import validate
from pyshacl.errors import ConstraintLoadError, ReportableRuntimeError, ShapeLoadError
from rdflib import Graph

from .aliases import ConstraintAliases
from .config import DEFAULT_CHAD_AP_TTL_URL, DEFAULT_PUBLIC_GRAPH_URL
from .extractor import create_shacl_shapes


@dataclass
class ValidationResult:
    conforms: bool
    results_graph: Graph
    results_text: str


class ValidationExecutionError(RuntimeError):
    """Raised when pySHACL cannot execute or load shapes."""



def load_rdf_graph(source: str | Path) -> Graph:
    graph = Graph()
    graph.parse(str(source))
    return graph



def validate_graph(
    *,
    data_source: str | Path = DEFAULT_PUBLIC_GRAPH_URL,
    ontology_source: str | Path = DEFAULT_CHAD_AP_TTL_URL,
    shapes_source: str | Path | None = None,
    shapes_base: str | None = None,
    aliases: ConstraintAliases | None = None,
    inference: str = "none",
    abort_on_first: bool = False,
    allow_infos: bool = False,
    allow_warnings: bool = False,
    meta_shacl: bool = True,
    advanced: bool = True,
    js: bool = False,
    debug: bool = False,
    do_owl_imports: bool = False,
) -> ValidationResult:
    data_graph = load_rdf_graph(data_source)

    if shapes_source is None:
        shacl_graph = create_shacl_shapes(
            ontology_source,
            shapes_base=shapes_base,
            aliases=aliases,
        )
    else:
        shacl_graph = load_rdf_graph(shapes_source)

    try:
        conforms, results_graph, results_text = validate(
            data_graph=data_graph,
            shacl_graph=shacl_graph,
            ont_graph=str(ontology_source) if ontology_source is not None else None,
            inference=inference,
            abort_on_first=abort_on_first,
            allow_infos=allow_infos,
            allow_warnings=allow_warnings,
            meta_shacl=meta_shacl,
            advanced=advanced,
            js=js,
            debug=debug,
            do_owl_imports=do_owl_imports,
        )
    except (
        ShapeLoadError,
        ConstraintLoadError,
        ReportableRuntimeError,
        RuntimeError,
    ) as exc:
        raise ValidationExecutionError(str(exc)) from exc

    return ValidationResult(
        conforms=bool(conforms),
        results_graph=results_graph,
        results_text=str(results_text),
    )



def write_validation_outputs(
    result: ValidationResult,
    *,
    text_report_path: str | Path | None = None,
    rdf_report_path: str | Path | None = None,
    rdf_report_format: str = "turtle",
) -> None:
    if text_report_path is not None:
        Path(text_report_path).write_text(result.results_text, encoding="utf-8")
    if rdf_report_path is not None:
        result.results_graph.serialize(destination=str(rdf_report_path), format=rdf_report_format)
