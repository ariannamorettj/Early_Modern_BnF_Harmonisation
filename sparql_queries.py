# sparql_queries.py
from rdflib import ConjunctiveGraph
from pathlib import Path

STORE_DIR = Path("reverse_graph.oxigraph")  # directory dello store
DATA_NT   = Path("data/reverse_unified_graph_nt_pieces_1gzwxhbl/reverse_unified_graph_ALL.nt")  # NT deduplicato

g = ConjunctiveGraph(store="Oxigraph")

# Crea lo store solo se NON esiste. Se esiste, aprilo senza creare.
if STORE_DIR.exists():
    g.open(str(STORE_DIR), create=False)
else:
    g.open(str(STORE_DIR), create=True)

# Importa il file NT (assicurati che sia davvero N-Triples)
g.parse(str(DATA_NT), format="nt")
g.commit()

# Esegui query
q = """
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
SELECT ?ed ?author
WHERE {
  ?ed marcrel:aut ?author .
}
LIMIT 10
"""

for row in g.query(q):
    print(row.ed, row.author)

g.close()
