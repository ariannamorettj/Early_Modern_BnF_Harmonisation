import json
import re
from pathlib import Path

import pyoxigraph

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTAL = PROJECT_ROOT / "08_sampo_portal"
CONFIGS = PORTAL / "configs"

BASE_GRAPH = pyoxigraph.NamedNode("https://w3id.org/bnf/portal/graph/chad-ap")
DERIVED = "https://w3id.org/bnf/portal/graph/derived"

MINI_GRAPH = """
@prefix obj:   <https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/> .
@prefix crm:   <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix lrmoo: <http://iflastandards.info/ns/lrm/lrmoo/> .
@prefix aat:   <http://vocab.getty.edu/aat/> .
@prefix geo:   <http://www.opengis.net/ont/geosparql#> .
@prefix bnf:   <http://data.bnf.fr/ark:/12148/> .

bnf:cbE1\\#about a lrmoo:F3_Manifestation ;
    crm:P102_has_title bnf:cbE1\\#title ;
    obj:hasTimeSpan bnf:cbE1\\#ts_year_first ;
    crm:P7_took_place_at bnf:cbE1\\#pub_place ;
    crm:P14_carried_out_by bnf:cbE1\\#pub_actor ;
    lrmoo:R4_embodies bnf:cbE1\\#Expression ;
    crm:P16i_was_used_for bnf:cbE1\\#expr_creation .
bnf:cbE1\\#title obj:hasSymbolicContent "Cosmographia" .
bnf:cbE1\\#ts_year_first crm:P82a_begin_of_the_begin "1477" .
bnf:cbE1\\#pub_place obj:isIdentifiedBy bnf:cbE1\\#pub_place_app, bnf:cbE1\\#pub_place_norm_app ;
    crm:P168_place_is_defined_by "POINT(11.3426 44.4949)"^^geo:wktLiteral .
bnf:cbE1\\#pub_place_app obj:hasSymbolicContent "Bologna (Italie)" .
bnf:cbE1\\#pub_place_norm_app obj:hasType aat:300404670 ; obj:hasSymbolicContent "Bologna" .
bnf:cbE1\\#pub_actor obj:isIdentifiedBy bnf:cbE1\\#pub_actor_app .
bnf:cbE1\\#pub_actor_app obj:hasSymbolicContent "Domenico de' Lapi" .
bnf:cbE1\\#Expression crm:P72_has_language <http://id.loc.gov/vocabulary/iso639-2/lat> .
bnf:cbE1\\#expr_creation crm:P9_consists_of bnf:cbE1\\#expr_creation_author .
bnf:cbE1\\#expr_creation_author crm:P14_carried_out_by bnf:cbA1\\#about ; obj:hasType aat:300025492 .

bnf:cbA1\\#about a obj:Person ;
    obj:isIdentifiedBy bnf:cbA1\\#app_fullname ;
    obj:wasPresentAt bnf:cbA1\\#birth_event, bnf:cbA1\\#start_event .
bnf:cbA1\\#app_fullname obj:hasType obj:full-name ; obj:hasSymbolicContent "Ptolemy" .
bnf:cbA1\\#birth_event obj:hasType obj:birth ; obj:hasTimeSpan bnf:cbA1\\#birth_ts .
bnf:cbA1\\#birth_ts obj:hasStartTime "0100-01-01T00:00:00" .
bnf:cbA1\\#start_event obj:hasType obj:foundation ; obj:hasTimeSpan bnf:cbA1\\#start_ts .
bnf:cbA1\\#start_ts obj:hasStartTime "0100-01-01T00:00:00" .

bnf:cbO1\\#about a obj:Organization ;
    obj:isIdentifiedBy bnf:cbO1\\#app_fullname .
bnf:cbO1\\#app_fullname obj:hasType obj:full-name ; obj:hasSymbolicContent "\\"William Blake trust\\"@fr" .
"""


def derived_store():
    store = pyoxigraph.Store()
    store.load(MINI_GRAPH.encode("utf-8"), "text/turtle", to_graph=BASE_GRAPH)
    store.update((PORTAL / "triplestore" / "derived.ru").read_text(encoding="utf-8"))
    return store


def values(store, subject, predicate):
    q = f"SELECT ?o WHERE {{ GRAPH <{DERIVED}> {{ <{subject}> <{predicate}> ?o }} }}"
    return sorted(str(row["o"].value) for row in store.query(q))


BNFP = "https://w3id.org/bnf/portal/schema/"
SKOS = "http://www.w3.org/2004/02/skos/core#prefLabel"
E1 = "http://data.bnf.fr/ark:/12148/cbE1#about"
A1 = "http://data.bnf.fr/ark:/12148/cbA1#about"
O1 = "http://data.bnf.fr/ark:/12148/cbO1#about"


def test_derived_layer_builds_edition_shortcuts():
    s = derived_store()
    assert values(s, E1, SKOS) == ["Cosmographia"]
    assert values(s, E1, BNFP + "year") == ["1477"]
    assert values(s, E1, BNFP + "decade") == ["1470"]
    assert values(s, E1, BNFP + "place") == ["https://w3id.org/bnf/portal/place/bologna"]
    assert values(s, "https://w3id.org/bnf/portal/place/bologna", "http://www.w3.org/2003/01/geo/wgs84_pos#lat") == ["44.4949"]
    # No harmonised publisher name: the recorded one is used.
    assert values(s, E1, BNFP + "publisher") == ["https://w3id.org/bnf/portal/publisher/domenico%20de%27%20lapi"]
    assert values(s, E1, BNFP + "language") == ["http://id.loc.gov/vocabulary/iso639-2/lat"]
    assert values(s, E1, BNFP + "author") == [A1]


def test_derived_layer_builds_actor_shortcuts():
    s = derived_store()
    assert values(s, A1, SKOS) == ["Ptolemy"]
    assert values(s, A1, BNFP + "contributedTo") == [E1]
    assert values(s, A1, BNFP + "birthYear") == ["100"]
    # A person's start event is not a foundation.
    assert values(s, A1, BNFP + "foundationYear") == []
    # Serialised literal names are unwrapped for display.
    assert values(s, O1, SKOS) == ["William Blake trust"]


def _exports(js_file: Path) -> set:
    text = js_file.read_text(encoding="utf-8")
    names = set(re.findall(r"^export const (\w+)", text, re.M))
    for block in re.findall(r"^export \{([^}]*)\} from", text, re.M):  # re-exports
        names.update(n.strip() for n in block.split(",") if n.strip())
    return names


def test_perspective_configs_reference_existing_queries_and_labels():
    portal = json.loads((CONFIGS / "portalConfig.json").read_text(encoding="utf-8"))
    pid = portal["portalID"]
    locale = json.loads((CONFIGS / pid / "translations" / "localeEN.json").read_text(encoding="utf-8"))
    for perspective in portal["perspectives"]["searchPerspectives"]:
        cfg = json.loads((CONFIGS / pid / "search_perspectives" / f"{perspective}.json").read_text(encoding="utf-8"))
        exports = _exports(CONFIGS / pid / "sparql_queries" / cfg["sparqlQueriesFile"])
        referenced = set()
        for rc in cfg["resultClasses"].values():
            referenced.update(v for k, v in rc.items() if k == "sparqlQuery")
            for block in (rc.get("paginatedResultsConfig", {}), rc.get("instanceConfig", {})):
                referenced.update(v for k, v in block.items()
                                  if k in ("propertiesQueryBlock", "relatedInstances"))
        referenced.update(cfg.get("generalQueries", {}).values())
        assert referenced <= exports, (perspective, referenced - exports)

        labels = locale["perspectives"][perspective]["properties"]
        property_ids = {p["id"] for p in cfg["properties"]}
        assert property_ids <= set(labels), (perspective, property_ids - set(labels))
        assert set(cfg["facets"]) <= set(labels), (perspective, set(cfg["facets"]) - set(labels))
        assert (CONFIGS / pid / "assets" / cfg["frontPageImage"]).exists()
