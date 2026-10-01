from __future__ import annotations

from pathlib import Path

# BnF: paths below are resolved against this package, so the module works
# whatever the current directory (07_graph_materialisation/shacl_validation/).
_PACKAGE_DIR = Path(__file__).resolve().parent
_MODULE_07_DIR = _PACKAGE_DIR.parent

# L'application profile resta remoto: e' un riferimento esterno/canonico, non
# qualcosa che questo repo produce.
#
# BnF: the URL below is the upstream default, CHAD-AP 2.1.0. It is kept for
# reference but NOT used as the default here: the BnF mappings
# (mapping_actors.yaml, mapping_bibliographic.yaml, mapping_roles.yaml) use
# the CHAD-AP "development/14" namespace
# https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/
# (obj:Person, obj:Appellation, obj:isIdentifiedBy, ...), which no published
# CHAD-AP release (1.0.0 to 2.1.0) contains: those model everything with
# CIDOC-CRM / LRMoo / CRMdig directly. Shapes generated from 2.1.0 would
# validate the BnF graph against a different model from the one its data
# uses. The default is therefore the development/14 schema, expected as a
# local file (see DEFAULT_CHAD_AP_TTL_URL); bnf_run.py stops with an
# explanation when it is missing.
CHAD_AP_2_1_0_TTL_URL = (
    "https://raw.githubusercontent.com/dharc-org/chad-ap/main/docs/current/chad-ap.ttl"
)
CHAD_AP_DEVELOPMENT_14_TTL = _PACKAGE_DIR / "resources" / "chad_ap_development_14.ttl"
DEFAULT_CHAD_AP_TTL_URL = str(CHAD_AP_DEVELOPMENT_14_TTL)
# Namespace the BnF mappings use: bnf_run.py checks the ontology against it.
BNF_CHAD_AP_NAMESPACE = "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/"

# Come modulo interno, il target di validazione di default e' il grafo che
# questa stessa pipeline produce localmente (results/merged_graph_output.ttl,
# scritto da run_unified_pipeline.py), non piu' una copia remota su GitHub —
# evita un giro remoto per validare un file gia' presente in locale, e resta
# sempre allineato all'ultima run piuttosto che all'ultimo push.
# Il nome della costante resta invariato per non toccare i punti che la usano;
# accetta comunque anche un URL http(s) se passato esplicitamente via CLI.
#
# BnF: the merged sample graph written by module 07 (N-Triples; rdflib picks
# the parser from the .nt extension).
DEFAULT_PUBLIC_GRAPH_URL = str(_MODULE_07_DIR / "output" / "sample" / "knowledge-graph_merged.nt")
# BnF: timestamped reports of bnf_run.py.
DEFAULT_REPORT_DIR = _MODULE_07_DIR / "report" / "shacl"
DEFAULT_SHAPES_BASE = "https://w3id.org/skg-if/shapes/"
DC_DESCRIPTION = "http://purl.org/dc/elements/1.1/description"
PROPERTY_PATTERN = r"([\w:-]+) -\[(\d+|[*N])(\.\.)?(\d+|[*N])?]->\s+([\w:-]+)"
ROOT_CLASSES = {
    "agent": "http://xmlns.com/foaf/0.1/Agent",
    "data-source": "http://www.w3.org/ns/dcat#DataService",
    "grant": "http://purl.org/cerif/frapo/Grant",
    "research-product": "http://purl.org/spar/fabio/Work",
    "topic": "http://purl.org/spar/fabio/SubjectTerm",
    "venue": "http://purl.org/spar/fabio/ExpressionCollection",
}
