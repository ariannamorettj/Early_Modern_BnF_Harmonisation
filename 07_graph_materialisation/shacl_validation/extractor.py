from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, XSD

from .aliases import ConstraintAliases, apply_property_alias, apply_target_alias
from .config import DC_DESCRIPTION, DEFAULT_SHAPES_BASE, PROPERTY_PATTERN, ROOT_CLASSES

PREFIX_PATTERN = re.compile(r"@prefix\s+(\w+):\s+<([^>]+)>\s*\.")
# Prefissi noti ma non sempre dichiarati nel testo di CHAD-AP (ne' via @prefix
# nelle dc:description, ne' come URI usata altrove nell'ontologia): usato come
# ultima risorsa in _resolve_namespace. "edtf" e' lo stesso namespace usato per
# i timespan in questo repo (vedi EDTF_DT in run_unified_pipeline.py).
WELL_KNOWN_PREFIXES = {
    "edtf": "http://id.loc.gov/datatypes/edtf/",
}
_PROPERTY_RE = re.compile(PROPERTY_PATTERN)
_DC_DESCRIPTION_URI = URIRef(DC_DESCRIPTION)
_SH = Namespace("http://www.w3.org/ns/shacl#")


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _get_ontology_iri(g: Graph) -> Optional[str]:
    for subject in g.subjects(RDF.type, OWL.Ontology, unique=True):
        return str(subject)
    return None


def _derive_module_name(source: str, g: Graph) -> str:
    iri = _get_ontology_iri(g)
    if iri:
        parsed = urlparse(iri)
        parts = [part for part in parsed.path.rstrip("/").split("/") if part]
        if parts:
            return parts[-1]

    if _is_url(source):
        parsed = urlparse(source)
        parts = [part for part in parsed.path.rstrip("/").split("/") if part]
    else:
        parts = [Path(source).stem]

    if parts:
        name = parts[-1]
        if "." in name:
            name = name.rsplit(".", 1)[0]
        return name
    return "ontology"


def _derive_shapes_base(source: str, g: Graph) -> str:
    iri = _get_ontology_iri(g)
    if iri:
        return iri.rstrip("/") + "/shapes/"
    return "http://example.org/shapes/"


def _build_uri_namespace_map(g: Graph) -> dict[str, str]:
    result: dict[str, str] = {}
    for subject, predicate, obj in g:
        for term in (subject, predicate, obj):
            if not isinstance(term, URIRef):
                continue
            uri = str(term)
            if "#" in uri:
                idx = uri.rindex("#") + 1
            elif "/" in uri:
                idx = uri.rindex("/") + 1
            else:
                continue
            local = uri[idx:]
            namespace = uri[:idx]
            if local and namespace:
                result[local] = namespace
    return result


def _extract_prefixes_from_literals(g: Graph) -> dict[str, str]:
    result: dict[str, str] = {}
    for _, _, obj in g:
        if not isinstance(obj, Literal):
            continue
        for match in PREFIX_PATTERN.finditer(str(obj)):
            result[match.group(1)] = match.group(2)
    return result


def _resolve_namespace(
    prefix: str,
    local_name: str,
    g: Graph,
    uri_ns_map: dict[str, str],
    literal_prefix_map: dict[str, str],
) -> Optional[str]:
    namespace = g.store.namespace(prefix)
    if namespace:
        return str(namespace)
    if local_name in uri_ns_map:
        return uri_ns_map[local_name]
    if prefix in literal_prefix_map:
        return literal_prefix_map[prefix]
    if prefix in WELL_KNOWN_PREFIXES:
        return WELL_KNOWN_PREFIXES[prefix]
    return None


def _split_description_properties(desc: str) -> list[str]:
    return [entry for entry in re.split(r"\n[*-] ", desc) if entry.strip()][1:]


def _detect_root_classes(g: Graph, described_classes: set[str]) -> set[str]:
    uri_ns_map = _build_uri_namespace_map(g)
    literal_prefix_map = _extract_prefixes_from_literals(g)
    referenced: set[str] = set()

    for cls in g.subjects(RDF.type, OWL.Class, unique=True):
        desc = g.value(cls, _DC_DESCRIPTION_URI)
        if not desc or "The properties that can be used" not in str(desc):
            continue
        properties = _split_description_properties(str(desc))
        for prop in properties:
            match = _PROPERTY_RE.match(prop.strip())
            if not match:
                continue
            target = match.group(5)
            if ":" in target:
                target_prefix, target_local = target.split(":", 1)
                if target_prefix in {"rdfs", "xsd"}:
                    continue
                target_ns = _resolve_namespace(
                    target_prefix,
                    target_local,
                    g,
                    uri_ns_map,
                    literal_prefix_map,
                )
            else:
                target_local = target
                target_ns = uri_ns_map.get(target)
            if target_ns:
                referenced.add(target_ns + target_local)

    return described_classes - referenced


class ExtractionError(ValueError):
    """Raised when SHACL extraction cannot resolve a documented constraint."""



def load_ontology_by_module(path: str) -> dict[str, Graph]:
    modules: dict[str, Graph] = {}
    path_obj = Path(path)
    module_dirs = [
        directory for directory in path_obj.iterdir() if directory.is_dir() and directory.name != "resources"
    ]
    for module_dir in sorted(module_dirs):
        rdf_files = []
        for suffix in ("*.ttl", "*.rdf", "*.owl", "*.n3", "*.nt", "*.jsonld"):
            rdf_files.extend(module_dir.glob(suffix))
        if rdf_files:
            graph = Graph()
            graph.parse(rdf_files[0])
            modules[module_dir.name] = graph
    return modules


def get_class_local_name(class_uri: str) -> str:
    if "#" in class_uri:
        return class_uri.split("#")[-1]
    return class_uri.split("/")[-1]


def _load_source(input_source: str) -> tuple[dict[str, Graph], bool]:
    if _is_url(input_source):
        graph = Graph()
        graph.parse(input_source)
        module_name = _derive_module_name(input_source, graph)
        return {module_name: graph}, False

    path = Path(input_source)
    if path.is_dir():
        return load_ontology_by_module(input_source), True

    graph = Graph()
    graph.parse(input_source)
    module_name = _derive_module_name(input_source, graph)
    return {module_name: graph}, False


def _resolve_shapes_base(
    input_source: str,
    modules: dict[str, Graph],
    is_modular: bool,
    shapes_base: Optional[str],
) -> str:
    if shapes_base:
        return shapes_base
    if is_modular:
        return DEFAULT_SHAPES_BASE
    first_graph = next(iter(modules.values()))
    return _derive_shapes_base(input_source, first_graph)


def _build_class_to_modules(modules: dict[str, Graph]) -> dict[str, list[str]]:
    class_to_modules: dict[str, list[str]] = {}
    for module_name, graph in modules.items():
        for cls in graph.subjects(RDF.type, OWL.Class, unique=True):
            desc = graph.value(cls, _DC_DESCRIPTION_URI)
            if desc and "The properties that can be used" in str(desc):
                class_to_modules.setdefault(str(cls), []).append(module_name)
    return class_to_modules


def _resolve_root_class_uris(
    modules: dict[str, Graph],
    class_to_modules: dict[str, list[str]],
    is_modular: bool,
) -> set[str]:
    if is_modular:
        return set(ROOT_CLASSES.values())

    all_graphs = Graph()
    for graph in modules.values():
        for triple in graph:
            all_graphs.add(triple)
        for prefix, namespace in graph.namespaces():
            all_graphs.bind(prefix, namespace)
    return _detect_root_classes(all_graphs, set(class_to_modules.keys()))


def _bind_namespaces(shacl_graph: Graph, modules: dict[str, Graph]) -> None:
    for graph in modules.values():
        for prefix, namespace in graph.namespaces():
            shacl_graph.bind(prefix, namespace)


def _bind_shape_namespaces(
    shacl_graph: Graph,
    modules: dict[str, Graph],
    shapes_base: str,
    is_modular: bool,
) -> None:
    if is_modular:
        for module_name in modules:
            shape_ns = shapes_base + module_name + "/"
            prefix = f"skg-sh-{module_name}".replace("-", "_")
            shacl_graph.bind(prefix, Namespace(shape_ns))
    else:
        module_name = next(iter(modules.keys()))
        prefix = module_name.replace("-", "_") + "_sh"
        # BnF: a Turtle prefix must start with a letter. An ontology IRI ending
        # in a number (".../development/14") would give "14_sh", and the
        # serialised shapes could not be parsed back.
        if not prefix[0].isalpha():
            prefix = "m" + prefix
        shacl_graph.bind(prefix, Namespace(shapes_base))


def _parse_property_constraint(
    prop_text: str,
    class_uri: str,
    aliases: ConstraintAliases | None,
) -> tuple[str, str, str | None, str | None, str]:
    match = _PROPERTY_RE.match(prop_text)
    if not match:
        raise ExtractionError(f"Invalid property format in {class_uri}: {prop_text}")
    prop_name, card_min, range_sep, card_max, target = match.groups()
    prop_name = apply_property_alias(prop_name, aliases)
    target = apply_target_alias(target, aliases)
    return prop_name, card_min, range_sep, card_max, target


def _resolve_target(
    *,
    target: str,
    prop_text: str,
    class_uri: str,
    graph: Graph,
    uri_ns_map: dict[str, str],
    literal_prefix_map: dict[str, str],
) -> tuple[str, str]:
    """Restituisce (target_ns, target_local) per un singolo target dichiarato."""
    if ":" in target:
        target_prefix, target_local = target.split(":", 1)
        target_ns = _resolve_namespace(target_prefix, target_local, graph, uri_ns_map, literal_prefix_map)
        if not target_ns:
            raise ExtractionError(
                f"Unknown prefix '{target_prefix}' in {class_uri}: {prop_text}"
            )
    else:
        target_local = target
        target_ns = uri_ns_map.get(target)
        if not target_ns:
            raise ExtractionError(
                f"Cannot resolve unqualified name '{target}' in {class_uri}: {prop_text}"
            )
    return target_ns, target_local


def _add_target_constraint(
    *,
    constraint_shape,
    target: str,
    target_ns: str,
    target_local: str,
    class_to_modules: dict[str, list[str]],
    module_name: str,
    shapes_base: str,
    is_modular: bool,
    shacl_graph: Graph,
) -> None:
    """Aggiunge a `constraint_shape` i triple che vincolano il valore atteso per
    un singolo target (letterale o nodo). `constraint_shape` puo' essere la
    property shape stessa (caso a target singolo) o un nodo alternativa
    all'interno di un sh:or (caso multi-target, vedi _process_property_group)."""
    if target == "rdfs:Literal":
        shacl_graph.add((constraint_shape, _SH.nodeKind, _SH.Literal))
        return

    if target.startswith("xsd:"):
        shacl_graph.add(
            (constraint_shape, _SH.datatype, URIRef(f"http://www.w3.org/2001/XMLSchema#{target_local}"))
        )
        return

    # Prefissi di datatype letterali non-xsd, noti solo dinamicamente (es. "edtf:EDTF",
    # risolto tramite WELL_KNOWN_PREFIXES/letterali @prefix): trattati come sh:datatype,
    # non come riferimento a una classe/nodo, altrimenti un literal valido (es.
    # "Y-99-01-01"^^edtf:EDTF) violerebbe erroneamente un vincolo sh:nodeKind BlankNodeOrIRI.
    target_uri = URIRef(target_ns + target_local)
    target_class_uri = str(target_uri)
    if target_class_uri in class_to_modules:
        target_modules = class_to_modules[target_class_uri]
        target_module = module_name if module_name in target_modules else sorted(target_modules)[0]
        target_shape_ns = shapes_base + target_module + "/" if is_modular else shapes_base
        target_shape_uri = URIRef(target_shape_ns + target_local + "Shape")
        shacl_graph.add((constraint_shape, _SH.node, target_shape_uri))
    elif target_ns in WELL_KNOWN_PREFIXES.values():
        shacl_graph.add((constraint_shape, _SH.datatype, target_uri))
    else:
        shacl_graph.add((constraint_shape, _SH.nodeKind, _SH.BlankNodeOrIRI))


def _process_property_group(
    *,
    prop_name: str,
    declarations: list[tuple[str, str | None, str | None, str]],  # (card_min, range_sep, card_max, target)
    prop_text_for_errors: str,
    class_uri: str,
    graph: Graph,
    shape_uri: URIRef,
    class_to_modules: dict[str, list[str]],
    module_name: str,
    shapes_base: str,
    is_modular: bool,
    shacl_graph: Graph,
    uri_ns_map: dict[str, str],
    literal_prefix_map: dict[str, str],
) -> None:
    prop_prefix, prop_local = prop_name.split(":", 1)
    prop_ns = _resolve_namespace(prop_prefix, prop_local, graph, uri_ns_map, literal_prefix_map)
    if not prop_ns:
        raise ExtractionError(
            f"Unknown prefix '{prop_prefix}' in {class_uri}: {prop_text_for_errors}"
        )
    prop_uri = URIRef(prop_ns + prop_local)

    property_shape = BNode()
    shacl_graph.add((shape_uri, _SH.property, property_shape))
    shacl_graph.add((property_shape, _SH.path, prop_uri))

    # Cardinalita': presa dalla prima dichiarazione (le dichiarazioni multiple
    # della stessa proprieta' in CHAD-AP condividono sempre la stessa cardinalita',
    # sono alternative sul *target*, non sul numero di valori ammessi).
    card_min, range_sep, card_max, _ = declarations[0]
    if range_sep is None and card_min not in {"*", "N"}:
        exact_cardinality = int(card_min)
        shacl_graph.add((property_shape, _SH.minCount, Literal(exact_cardinality, datatype=XSD.integer)))
        shacl_graph.add((property_shape, _SH.maxCount, Literal(exact_cardinality, datatype=XSD.integer)))
    else:
        if card_min and card_min not in {"*", "N"}:
            shacl_graph.add((property_shape, _SH.minCount, Literal(int(card_min), datatype=XSD.integer)))
        if card_max and card_max not in {"*", "N"}:
            shacl_graph.add((property_shape, _SH.maxCount, Literal(int(card_max), datatype=XSD.integer)))

    resolved_targets = [
        (target, *_resolve_target(
            target=target,
            prop_text=prop_text_for_errors,
            class_uri=class_uri,
            graph=graph,
            uri_ns_map=uri_ns_map,
            literal_prefix_map=literal_prefix_map,
        ))
        for _, _, _, target in declarations
    ]

    if len(resolved_targets) == 1:
        target, target_ns, target_local = resolved_targets[0]
        _add_target_constraint(
            constraint_shape=property_shape,
            target=target,
            target_ns=target_ns,
            target_local=target_local,
            class_to_modules=class_to_modules,
            module_name=module_name,
            shapes_base=shapes_base,
            is_modular=is_modular,
            shacl_graph=shacl_graph,
        )
        return

    # Piu' target dichiarati per la stessa proprieta' (es. P82a_begin_of_the_begin
    # -[1]-> xsd:dateTime E -[1]-> edtf:EDTF in CHAD-AP): un valore conforme deve
    # soddisfarne almeno uno, non tutti — si combinano con sh:or, non con due
    # sh:property indipendenti sullo stesso path (che sarebbero AND impliciti).
    alt_nodes = []
    for target, target_ns, target_local in resolved_targets:
        alt_shape = BNode()
        _add_target_constraint(
            constraint_shape=alt_shape,
            target=target,
            target_ns=target_ns,
            target_local=target_local,
            class_to_modules=class_to_modules,
            module_name=module_name,
            shapes_base=shapes_base,
            is_modular=is_modular,
            shacl_graph=shacl_graph,
        )
        alt_nodes.append(alt_shape)

    shacl_graph.add((property_shape, _SH["or"], _to_rdf_list(shacl_graph, alt_nodes)))


def _to_rdf_list(graph: Graph, items: list) -> BNode:
    head = BNode()
    current = head
    for index, item in enumerate(items):
        graph.add((current, RDF.first, item))
        if index == len(items) - 1:
            graph.add((current, RDF.rest, RDF.nil))
        else:
            next_node = BNode()
            graph.add((current, RDF.rest, next_node))
            current = next_node
    return head



def create_shacl_shapes(
    input_source: str | Path,
    *,
    shapes_base: Optional[str] = None,
    aliases: ConstraintAliases | None = None,
) -> Graph:
    input_source = str(input_source)
    modules, is_modular = _load_source(input_source)
    resolved_shapes_base = _resolve_shapes_base(input_source, modules, is_modular, shapes_base)

    shacl_graph = Graph()
    shacl_graph.bind("sh", _SH)
    _bind_namespaces(shacl_graph, modules)

    class_to_modules = _build_class_to_modules(modules)
    root_class_uris = _resolve_root_class_uris(modules, class_to_modules, is_modular)
    _bind_shape_namespaces(shacl_graph, modules, resolved_shapes_base, is_modular)

    for module_name, graph in modules.items():
        shape_ns = Namespace(
            resolved_shapes_base + module_name + "/" if is_modular else resolved_shapes_base
        )
        uri_ns_map = _build_uri_namespace_map(graph)
        literal_prefix_map = _extract_prefixes_from_literals(graph)

        for cls in graph.subjects(RDF.type, OWL.Class, unique=True):
            desc = graph.value(cls, _DC_DESCRIPTION_URI)
            if not desc:
                continue
            desc_str = str(desc)
            if "The properties that can be used" not in desc_str:
                continue

            class_uri = str(cls)
            class_local = get_class_local_name(class_uri)
            shape_uri = URIRef(str(shape_ns) + class_local + "Shape")
            shacl_graph.add((shape_uri, RDF.type, _SH.NodeShape))
            if class_uri in root_class_uris:
                shacl_graph.add((shape_uri, _SH.targetClass, cls))

            properties = _split_description_properties(desc_str)
            # Raggruppa le dichiarazioni per nome di proprieta' (nell'ordine di
            # prima comparsa), cosi' una proprieta' con piu' target alternativi
            # dichiarati su righe separate (es. P82a_begin_of_the_begin sia verso
            # xsd:dateTime che verso edtf:EDTF) produce un'unica property shape
            # con sh:or, invece di due sh:property indipendenti sullo stesso path.
            grouped: dict[str, list[tuple[str, str | None, str | None, str]]] = {}
            first_prop_text: dict[str, str] = {}
            for prop in properties:
                prop_text = prop.strip()
                if not prop_text:
                    continue
                prop_name, card_min, range_sep, card_max, target = _parse_property_constraint(
                    prop_text, class_uri, aliases
                )
                grouped.setdefault(prop_name, []).append((card_min, range_sep, card_max, target))
                first_prop_text.setdefault(prop_name, prop_text)

            for prop_name, declarations in grouped.items():
                _process_property_group(
                    prop_name=prop_name,
                    declarations=declarations,
                    prop_text_for_errors=first_prop_text[prop_name],
                    class_uri=class_uri,
                    graph=graph,
                    shape_uri=shape_uri,
                    class_to_modules=class_to_modules,
                    module_name=module_name,
                    shapes_base=resolved_shapes_base,
                    is_modular=is_modular,
                    shacl_graph=shacl_graph,
                    uri_ns_map=uri_ns_map,
                    literal_prefix_map=literal_prefix_map,
                )

    return shacl_graph
