// Editions (lrmoo:F3_Manifestation) of the CHAD-AP graph, read through the
// portal layer that 08_sampo_portal/triplestore/derived.ru adds on load.
//
// Page URLs use the ARK local id: <http://data.bnf.fr/ark:/12148/cb31015462k#about>
// becomes /editions/page/cb31015462k, and URITemplate in editions.json maps it back.

export const editionProperties = `
    {
      ?id skos:prefLabel ?prefLabel__id .
      BIND(?prefLabel__id AS ?prefLabel__prefLabel)
      BIND(CONCAT("/editions/page/", REPLACE(STR(?id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?prefLabel__dataProviderUrl)
      BIND(?id AS ?uri__id)
      BIND(STR(?id) AS ?uri__prefLabel)
      BIND(REPLACE(STR(?id), "#about$", "") AS ?uri__dataProviderUrl)
    }
    UNION
    {
      ?id crm:P102_has_title/obj:hasSymbolicContent ?fullTitle .
    }
    UNION
    {
      ?id bnfp:author ?author__id .
      ?author__id skos:prefLabel ?author__prefLabel .
      BIND(CONCAT("/actors/page/", REPLACE(STR(?author__id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?author__dataProviderUrl)
    }
    UNION
    {
      VALUES (?roleProp ?roleLabel) {
        (bnfp:editor "editor") (bnfp:translator "translator") (bnfp:illustrator "illustrator")
      }
      ?id ?roleProp ?contributor__id .
      ?contributor__id skos:prefLabel ?contributorName .
      BIND(CONCAT(?contributorName, " (", ?roleLabel, ")") AS ?contributor__prefLabel)
      BIND(CONCAT("/actors/page/", REPLACE(STR(?contributor__id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?contributor__dataProviderUrl)
    }
    UNION
    {
      ?id bnfp:year ?year .
    }
    UNION
    {
      ?id bnfp:place ?place__id .
      ?place__id skos:prefLabel ?place__prefLabel .
    }
    UNION
    {
      ?id crm:P7_took_place_at/obj:isIdentifiedBy ?rawPlaceApp .
      FILTER NOT EXISTS { ?rawPlaceApp obj:hasType ?anyType }
      ?rawPlaceApp obj:hasSymbolicContent ?placeAsRecorded .
    }
    UNION
    {
      ?id bnfp:publisher ?publisher__id .
      ?publisher__id skos:prefLabel ?publisher__prefLabel .
    }
    UNION
    {
      ?id bnfp:language ?language__id .
      OPTIONAL { ?language__id skos:prefLabel ?languageLabel }
      BIND(COALESCE(?languageLabel, REPLACE(STR(?language__id), "^.*/", "")) AS ?language__prefLabel)
      BIND(STR(?language__id) AS ?language__dataProviderUrl)
    }
    UNION
    {
      ?id crm:P130i_features_are_also_found_on/obj:isIdentifiedBy/obj:hasSymbolicContent ?digitalCopy__id .
      BIND(STR(?digitalCopy__id) AS ?digitalCopy__prefLabel)
      BIND(STR(?digitalCopy__id) AS ?digitalCopy__dataProviderUrl)
    }
    UNION
    {
      ?id crm:P3_has_note ?description .
    }
    UNION
    {
      ?id obj:isIdentifiedBy ?bnfIdNode .
      FILTER(STRENDS(STR(?bnfIdNode), "#bnf_id"))
      ?bnfIdNode obj:hasSymbolicContent ?frbnf .
    }
`

export const editionPlacesQuery = `
  SELECT ?id ?lat ?long (COUNT(DISTINCT ?edition) AS ?instanceCount)
  WHERE {
    <FILTER>
    ?edition bnfp:place ?id .
    ?id wgs84:lat ?lat ;
        wgs84:long ?long .
  }
  GROUP BY ?id ?lat ?long
`

export const placePropertiesInfoWindow = `
    ?id skos:prefLabel ?prefLabel__id .
    BIND(?prefLabel__id AS ?prefLabel__prefLabel)
`

export const editionsPublishedAt = `
    OPTIONAL {
      <FILTER>
      ?related__id bnfp:place ?id ;
                   skos:prefLabel ?related__prefLabel .
      BIND(CONCAT("/editions/page/", REPLACE(STR(?related__id), "^.*/(cb[^/#]+)#about$", "$1")) AS ?related__dataProviderUrl)
    }
`

export const editionsByDecadeQuery = `
  SELECT ?category (COUNT(DISTINCT ?edition) AS ?count)
  WHERE {
    <FILTER>
    ?edition bnfp:decade ?category .
  }
  GROUP BY ?category
  ORDER BY ?category
`
