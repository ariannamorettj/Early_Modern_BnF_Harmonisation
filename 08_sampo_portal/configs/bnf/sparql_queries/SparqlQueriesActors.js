// Actors (obj:Person, obj:Organization) of the CHAD-AP graph, read through the
// portal layer that 08_sampo_portal/triplestore/derived.ru adds on load.

export const actorProperties = `
    {
      ?id skos:prefLabel ?prefLabel__id .
      BIND(?prefLabel__id AS ?prefLabel__prefLabel)
      BIND(CONCAT("/actors/page/", REPLACE(STR(?id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?prefLabel__dataProviderUrl)
      BIND(?id AS ?uri__id)
      BIND(STR(?id) AS ?uri__prefLabel)
      BIND(REPLACE(STR(?id), "#about$", "") AS ?uri__dataProviderUrl)
    }
    UNION
    {
      ?id bnfp:actorType ?type__id .
      ?type__id skos:prefLabel ?type__prefLabel .
    }
    UNION
    {
      ?id bnfp:birthYear ?birthYear .
    }
    UNION
    {
      ?id bnfp:deathYear ?deathYear .
    }
    UNION
    {
      ?id bnfp:gender ?gender__id .
      OPTIONAL { ?gender__id skos:prefLabel ?genderLabel }
      BIND(COALESCE(?genderLabel, REPLACE(STR(?gender__id), "^.*/", "")) AS ?gender__prefLabel)
    }
    UNION
    {
      ?id bnfp:country ?country__id .
      OPTIONAL { ?country__id skos:prefLabel ?countryLabel }
      BIND(COALESCE(?countryLabel, REPLACE(STR(?country__id), "^.*/", "")) AS ?country__prefLabel)
    }
    UNION
    {
      ?id bnfp:role ?role__id .
      ?role__id skos:prefLabel ?role__prefLabel .
    }
    UNION
    {
      ?id bnfp:contributedTo ?edition__id .
      ?edition__id skos:prefLabel ?edition__prefLabel .
      BIND(CONCAT("/editions/page/", REPLACE(STR(?edition__id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?edition__dataProviderUrl)
    }
    UNION
    {
      ?id obj:isIdentifiedBy ?externalLink__id .
      ?externalLink__id a obj:Identifier .
      FILTER(!STRSTARTS(STR(?externalLink__id), "http://data.bnf.fr/"))
      BIND(STR(?externalLink__id) AS ?externalLink__prefLabel)
      BIND(STR(?externalLink__id) AS ?externalLink__dataProviderUrl)
    }
`

export const actorBirthsByDecadeQuery = `
  SELECT ?category (COUNT(DISTINCT ?actor) AS ?count)
  WHERE {
    <FILTER>
    ?actor bnfp:birthYear ?year .
    BIND(?year - (?year - FLOOR(?year / 10) * 10) AS ?category)
  }
  GROUP BY ?category
  ORDER BY ?category
`
