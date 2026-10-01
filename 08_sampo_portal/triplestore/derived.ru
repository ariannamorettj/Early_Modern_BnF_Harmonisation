# Portal layer derived from the CHAD-AP graph (module 07).
#
# The CHAD-AP graph models every label as an Appellation node and gives each
# edition its own place and publisher node. Sampo-UI facets need shared
# entities with a skos:prefLabel, so this update materialises portal
# shortcuts into their own named graph. It only ever reads the CHAD-AP graph
# and is re-run from scratch on every `portal.py load`, so it tracks whatever
# module 07 produced last.

PREFIX obj:   <https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/>
PREFIX crm:   <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX lrmoo: <http://iflastandards.info/ns/lrm/lrmoo/>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>
PREFIX wgs84: <http://www.w3.org/2003/01/geo/wgs84_pos#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX aat:   <http://vocab.getty.edu/aat/>
PREFIX bnfp:  <https://w3id.org/bnf/portal/schema/>

DROP SILENT GRAPH <https://w3id.org/bnf/portal/graph/derived> ;

# ── Editions: label, year ────────────────────────────────────────────────────
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e skos:prefLabel ?label .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e a lrmoo:F3_Manifestation ; crm:P102_has_title/obj:hasSymbolicContent ?title .
  BIND(IF(STRLEN(?title) > 160, CONCAT(SUBSTR(?title, 1, 157), "..."), ?title) AS ?label)
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:year ?year ; bnfp:decade ?decade .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e a lrmoo:F3_Manifestation ; obj:hasTimeSpan ?ts .
  FILTER(STRENDS(STR(?ts), "#ts_year_first"))
  ?ts crm:P82a_begin_of_the_begin ?begin .
  FILTER(REGEX(STR(?begin), "^[0-9]{4}$"))
  BIND(xsd:integer(STR(?begin)) AS ?year)
  BIND(?year - (?year - FLOOR(?year / 10) * 10) AS ?decade)
} } ;

# ── Editions: shared places from module 04's harmonised place name ───────────
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:place ?place .
  ?place a bnfp:Place ; skos:prefLabel ?name .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e a lrmoo:F3_Manifestation ; crm:P7_took_place_at ?p .
  ?p obj:isIdentifiedBy ?app .
  ?app obj:hasType aat:300404670 ; obj:hasSymbolicContent ?name .
  BIND(IRI(CONCAT("https://w3id.org/bnf/portal/place/", ENCODE_FOR_URI(LCASE(?name)))) AS ?place)
} } ;

# One coordinate pair per shared place (the TGN lookup gives every edition of
# a harmonised place the same point; SAMPLE guards against drift).
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?place wgs84:lat ?lat ; wgs84:long ?long .
} }
WHERE {
  {
    SELECT ?place (SAMPLE(?wkt) AS ?point) WHERE {
      GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
        ?e crm:P7_took_place_at ?p .
        ?p crm:P168_place_is_defined_by ?wkt ; obj:isIdentifiedBy ?app .
        ?app obj:hasType aat:300404670 ; obj:hasSymbolicContent ?name .
      }
      BIND(IRI(CONCAT("https://w3id.org/bnf/portal/place/", ENCODE_FOR_URI(LCASE(?name)))) AS ?place)
    } GROUP BY ?place
  }
  BIND(STRBEFORE(STRAFTER(STR(?point), "POINT("), ")") AS ?coords)
  BIND(xsd:decimal(STRBEFORE(?coords, " ")) AS ?long)
  BIND(xsd:decimal(STRAFTER(?coords, " ")) AS ?lat)
} ;

# ── Editions: shared publishers (harmonised name, raw name as fallback) ──────
# Two passes instead of OPTIONAL + FILTER NOT EXISTS, which did not finish
# in 5 minutes on the full graph: harmonised names first, then the recorded
# name for editions that still have no publisher (checked on the small
# derived graph). The recorded appellation is the #pub_actor_app node.
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:publisher ?pub .
  ?pub a bnfp:Publisher ; skos:prefLabel ?name .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e crm:P14_carried_out_by ?pa .
  ?pa obj:isIdentifiedBy ?h .
  ?h obj:hasType aat:300404670 ; obj:hasSymbolicContent ?name .
  BIND(IRI(CONCAT("https://w3id.org/bnf/portal/publisher/", ENCODE_FOR_URI(LCASE(?name)))) AS ?pub)
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:publisher ?pub .
  ?pub a bnfp:Publisher ; skos:prefLabel ?name .
} }
WHERE {
  GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
    ?e crm:P14_carried_out_by ?pa .
    ?pa obj:isIdentifiedBy ?r .
    FILTER(STRENDS(STR(?r), "#pub_actor_app"))
    ?r obj:hasSymbolicContent ?name .
  }
  FILTER NOT EXISTS { GRAPH <https://w3id.org/bnf/portal/graph/derived> { ?e bnfp:publisher ?any } }
  BIND(IRI(CONCAT("https://w3id.org/bnf/portal/publisher/", ENCODE_FOR_URI(LCASE(?name)))) AS ?pub)
} ;

# ── Editions: language ───────────────────────────────────────────────────────
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:language ?lang .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e a lrmoo:F3_Manifestation ; lrmoo:R4_embodies/crm:P72_has_language ?lang .
} } ;

# ── Contributors by role (both the edition-side and actor-side role edges) ───
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?e bnfp:contributor ?a ; ?roleProp ?a .
  ?a bnfp:contributedTo ?e ; bnfp:role ?role .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?e a lrmoo:F3_Manifestation ; crm:P16i_was_used_for/crm:P9_consists_of ?act .
  ?act crm:P14_carried_out_by ?a ; obj:hasType ?role .
  VALUES (?role ?roleProp) {
    (aat:300025492 bnfp:author)
    (aat:300312355 bnfp:editor)
    (aat:300069831 bnfp:translator)
    (aat:300025164 bnfp:illustrator)
  }
} } ;

# ── Actors: label, type, life years, gender ──────────────────────────────────
# Full name, else surname, else the ARK id: three passes instead of a GROUP
# BY with two OPTIONALs over every actor, which did not finish in 5 minutes
# on the full graph. Each actor has one #app_fullname node at most.
INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a skos:prefLabel ?label .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?a obj:isIdentifiedBy ?fa .
  ?fa obj:hasType obj:full-name ; obj:hasSymbolicContent ?full .
  # Serialised literals ("France"@fr) are unwrapped upstream since module 04's
  # assembly fix; kept as a guard for graphs built before it.
  BIND(REPLACE(?full, "^\"(.*)\"@[A-Za-z-]+$", "$1") AS ?label)
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a skos:prefLabel ?last .
} }
WHERE {
  GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
    ?a obj:isIdentifiedBy ?la .
    ?la obj:hasType obj:last-name ; obj:hasSymbolicContent ?last .
  }
  FILTER NOT EXISTS { GRAPH <https://w3id.org/bnf/portal/graph/derived> { ?a skos:prefLabel ?any } }
} ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a skos:prefLabel ?label .
} }
WHERE {
  GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
    VALUES ?type { obj:Person obj:Organization }
    ?a a ?type .
  }
  FILTER NOT EXISTS { GRAPH <https://w3id.org/bnf/portal/graph/derived> { ?a skos:prefLabel ?any } }
  BIND(REPLACE(STR(?a), "^.*/(cb[^#]+).*$", "$1") AS ?label)
} ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a bnfp:actorType ?type .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  VALUES ?type { obj:Person obj:Organization }
  ?a a ?type .
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a ?yearProp ?year .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?a obj:wasPresentAt ?ev .
  ?ev obj:hasType ?evType ; obj:hasTimeSpan/obj:hasStartTime ?start .
  VALUES (?evType ?yearProp) {
    (obj:birth bnfp:birthYear)
    (obj:death bnfp:deathYear)
    (obj:foundation bnfp:foundationYear)
    (obj:dissolution bnfp:dissolutionYear)
  }
  FILTER(REGEX(STR(?start), "^[0-9]{4}-"))
  # mapping_actors.yaml types actor_start/actor_end as foundation/dissolution
  # for every actor, but for persons BnF fills them with the life years;
  # only an organisation's start/end is a foundation/dissolution.
  FILTER(?yearProp IN (bnfp:birthYear, bnfp:deathYear) || EXISTS { ?a a obj:Organization })
  BIND(xsd:integer(SUBSTR(STR(?start), 1, 4)) AS ?year)
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a bnfp:gender ?g .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?aa obj:assignsAttributeTo ?a ; obj:assignsPropertyOfType obj:gender ; obj:assigns ?g .
} } ;

INSERT { GRAPH <https://w3id.org/bnf/portal/graph/derived> {
  ?a bnfp:country ?c .
} }
WHERE { GRAPH <https://w3id.org/bnf/portal/graph/chad-ap> {
  ?a obj:hasResidenceIn ?c .
} }
