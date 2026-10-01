"""Which classes of a data graph the shapes generated from an ontology reach.

BnF addition (not in the upstream package). create_shacl_shapes() writes one
node shape per class whose dc:description lists its properties, but gives
sh:targetClass only to the "root" classes, those no other documented class
points to. A class therefore falls in one of three groups:

- targeted: its shape has sh:targetClass, so every instance is validated;
- reachable_via_sh_node: it has a shape, but the shape applies only to
  instances reached as the value of a property of an already validated node
  (sh:node); an instance reached by no such property is not validated;
- not_covered: the ontology documents no properties for it, so no shape
  exists. No shape is invented for these classes.
"""

from __future__ import annotations

from collections import Counter

from rdflib import Graph
from rdflib.namespace import RDF

from .extractor import _build_class_to_modules, _load_source, _resolve_root_class_uris

STATUSES = ("targeted", "reachable_via_sh_node", "not_covered")


def class_coverage(data_graph: Graph, ontology_source: str) -> dict:
    modules, is_modular = _load_source(str(ontology_source))
    class_to_modules = _build_class_to_modules(modules)
    root_classes = _resolve_root_class_uris(modules, class_to_modules, is_modular)

    instances = Counter(str(cls) for cls in data_graph.objects(None, RDF.type))
    classes = []
    for cls, count in sorted(instances.items(), key=lambda item: (-item[1], item[0])):
        if cls in root_classes:
            status = "targeted"
        elif cls in class_to_modules:
            status = "reachable_via_sh_node"
        else:
            status = "not_covered"
        classes.append({"class": cls, "instances": count, "status": status})

    return {
        "classes_in_data": len(classes),
        "by_status": {
            status: sum(1 for row in classes if row["status"] == status) for status in STATUSES
        },
        "instances_by_status": {
            status: sum(row["instances"] for row in classes if row["status"] == status)
            for status in STATUSES
        },
        "classes": classes,
    }


def format_class_coverage(coverage: dict) -> str:
    lines = [
        f"Classes in the data graph: {coverage['classes_in_data']}",
        *(f"  {status}: {coverage['by_status'][status]} classes, "
          f"{coverage['instances_by_status'][status]} instances" for status in STATUSES),
        "",
        f"{'instances':>9}  {'status':<22}  class",
    ]
    for row in coverage["classes"]:
        lines.append(f"{row['instances']:>9}  {row['status']:<22}  {row['class']}")
    return "\n".join(lines) + "\n"
