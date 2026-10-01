// Sampo-UI's default result-set template (server/src/sparql/SparqlQueriesGeneral.js,
// facetResultSetQuery) with the property block wrapped in LATERAL.
//
// Without LATERAL, Oxigraph evaluates the UNION of property patterns for every
// instance of the class and only then joins it with the page of 20 ids: on the
// full graph the actors table took 95 s. LATERAL evaluates the properties once
// per id of the page (7 s). Selected per perspective through
// "generalQueries": { "facetResultSetQuery": "facetResultSetQueryLateral" }.
export const facetResultSetQueryLateral = `
  SELECT *
  WHERE {
    {
      SELECT DISTINCT ?id ?score ?literal ?orderBy {
        <FILTER>
        VALUES ?facetClass { <FACET_CLASS> }
        ?id <FACET_CLASS_PREDICATE> ?facetClass .
        <ORDER_BY_TRIPLE>
      }
      <ORDER_BY>
      <PAGE>
    }
    FILTER(BOUND(?id))
    LATERAL {
      <RESULT_SET_PROPERTIES>
    }
  }
  <ORDER_BY>
`
