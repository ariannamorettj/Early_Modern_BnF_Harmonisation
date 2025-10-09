#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
reverse_graph_creator.py
------------------
Genera un grafo RDF unificato a partire da DUE dataset separati di CSV:

1) ATTORI (struttura: cartella -> csv, divisi per mestiere)
   Colonne attese:
     year,actor,actor_birth,actor_country,actor_death,actor_end,
     actor_gender,actor_language,actor_link_close,actor_link_exact,
     actor_name,actor_profession,actor_start

   - 'actor' deve essere un URI (soggetto del nodo agente)
   - 'actor_link_exact' e 'actor_link_close' (se URI) → owl:sameAs / skos:closeMatch
   - start/end come xsd:gYear

   > data/unified_agents

2) EDIZIONI (struttura: cartella -> csv, divisi per anni)
   Colonne attese:
     edition,author,author_end,author_entity_type,author_first_name,author_gender,
     author_last_name,author_link_close,author_link_exact,author_name,author_start,
     bnf_id,description,digital_copy_link,editor,editor_end,editor_entity_type,
     editor_first_name,editor_gender,editor_last_name,editor_link_close,
     editor_link_exact,editor_name,editor_start,expression,illustrator,
     illustrator_end,illustrator_entity_type,illustrator_first_name,illustrator_gender,
     illustrator_last_name,illustrator_link_close,illustrator_link_exact,illustrator_name,
     illustrator_start,language,place,publication_year,publisher,publisher_2,
     publisher_2_end,publisher_2_entity_type,publisher_2_first_name,publisher_2_gender,
     publisher_2_last_name,publisher_2_link_close,publisher_2_link_exact,publisher_2_name,
     publisher_2_start,record_type,subject_topic,title,translator,translator_end,
     translator_entity_type,translator_first_name,translator_gender,translator_last_name,
     translator_link_close,translator_link_exact,translator_name,translator_start,
     work,year_dir,year_range

   - 'edition' dev’essere un URI (soggetto dell’edizione)
   - Anno principale: usa 'year_dir' (se presente), altrimenti 'publication_year' → bnf-onto:firstYear (xsd:gYear)
   - Colonne *_link_exact/close (se URI) → owl:sameAs / skos:closeMatch per il nodo persona collegato
   - *_entity_type (se URI) → rdf:type per il nodo persona collegato
   - Altri metadati *_first_name, *_last_name, *_name, *_gender, *_start, *_end → su nodo persona

   > data/unified_dataset/unified_chunks

Dipendenze: rdflib, pandas, tqdm
Installazione: pip install rdflib pandas tqdm
Uso:
    python reverse_graph_creator.py \
      --actors-root data/unified_agents \
      --editions-root data/unified_dataset/unified_chunks \
      --out data/reverse_unified_graph.ttl
"""

import argparse
from pathlib import Path
import pandas as pd
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, XSD
from tqdm import tqdm
import re
import shutil
from typing import List
import tempfile
import os
import zlib

# ---------------- Namespaces (allineati a BnF / MARC relators / DC / FOAF / BIO / SKOS)
BNF = Namespace("http://data.bnf.fr/ontology/bnf-onto/")
RDAREL = Namespace("http://rdvocab.info/RDARelationshipsWEMI/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
RDAM = Namespace("http://rdaregistry.info/Elements/m/#")
MARCREL = Namespace("http://id.loc.gov/vocabulary/relators/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
BIO = Namespace("http://purl.org/vocab/bio/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

# ---------------- Utility
def _shard_index(line: bytes, shards: int) -> int:
    return zlib.adler32(line) % shards

def dedupe_nt_lines(input_path: Path, output_path: Path, shards: int = 64, tmp_root: Path | None = None):
    """
    Dedupe su un .nt senza caricare tutto in RAM:
    1) sharda per hash riga -> file temporanei
    2) per ciascuno shard: carica in memoria solo le sue righe, deduplica con set
    3) concatena gli shard deduplicati in output_path
    L'ordine delle righe NON è preservato (ma non è rilevante per NT/TTL).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="nt_dedupe_", dir=str(tmp_root or output_path.parent)))

    shard_paths = [tmp_dir / f"shard_{i:03d}.nt" for i in range(shards)]
    shard_files = [open(p, "wb") for p in shard_paths]
    try:
        with open(input_path, "rb") as inp:
            for line in inp:
                if not line.strip():
                    continue
                idx = _shard_index(line, shards)
                shard_files[idx].write(line)
    finally:
        for fh in shard_files:
            fh.close()

    dedup_paths = []
    for sp in shard_paths:
        seen: set[bytes] = set()
        dp = sp.with_suffix(".dedup")
        with open(sp, "rb") as r, open(dp, "wb") as w:
            for line in r:
                if line in seen:
                    continue
                seen.add(line)
                w.write(line)
        dedup_paths.append(dp)

    with open(output_path, "wb") as out:
        for dp in dedup_paths:
            with open(dp, "rb") as r:
                shutil.copyfileobj(r, out)

    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

def is_uri(value: str) -> bool:
    return isinstance(value, str) and value.startswith("http")

# --- NUOVO: normalizzazione e split valori multipli --------------------------
URI_TRIM_RE = re.compile(r'^[<\s]*|[>\s]*$')

def normalize_uri(v: str) -> str:
    """
    Pulisce un URI grezzo proveniente dai CSV:
    - rimuove spazi e brackets <...>
    - rimuove separatori finali spurii (; ,)
    """
    if v is None:
        return ""
    s = URI_TRIM_RE.sub("", str(v))
    s = s.rstrip(";,")
    return s

def maybe_split_values(val: str):
    """
    Gestisce liste con separatori multipli.
    Split su '|' e ';' (spesso presenti nei CSV), trim e normalizzazione URI.
    """
    if val is None:
        return []
    s = str(val).strip()
    if not s:
        return []
    # split su | oppure ; (con spazi opzionali attorno)
    parts = re.split(r"\s*[|;]\s*", s)
    cleaned = [normalize_uri(p) for p in parts if normalize_uri(p)]
    return cleaned if cleaned else []

def bind_prefixes(g: Graph):
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("xsd", XSD)
    g.bind("skos", SKOS)
    g.bind("foaf", FOAF)
    g.bind("dcterms", DCTERMS)
    g.bind("rdam", RDAM)
    g.bind("rdarelationships", RDAREL)
    g.bind("marcrel", MARCREL)
    g.bind("bnf-onto", BNF)
    g.bind("bio", BIO)

# Mapping colonne → predicati

ACTOR_LITS = {
    "actor_name":        (FOAF.name,               None, None),
    "actor_country":     (BNF["countryAssociatedWithThePerson"], None, None),
    "actor_language":    (BNF["languageOfThePerson"], None, None),
    "actor_gender":      (FOAF.gender,             None, None),
    "actor_profession":  (BNF["biographicalInformation"], None, None),
    "actor_birth":       (BIO.birth,               None, None),
    "actor_death":       (BIO.death,               None, None),
    "actor_start":       (BNF["firstYear"],        "gYear", None),
    "actor_end":         (BNF["lastYear"],         "gYear", None),
}

EDITION_LITS = {
    "bnf_id":        (BNF["FRBNF"],     None,  None),
    "title":         (DCTERMS.title,    None,  None),
    "year_range":    (DCTERMS.date,     None,  None),
    "description":   (DCTERMS.description, None, None),
    "language":      (DCTERMS.language, None,  None),
    "record_type":   (DCTERMS.type,     None,  None),
}

EDITION_OBJS = {
    "expression":        (RDAREL["expressionManifested"],),
    "work":              (RDAREL["workManifested"],),
    "place":             (RDAM["P30279"],),
    "subject_topic":     (DCTERMS.subject,),
    "digital_copy_link": (RDAM["P30016"],),
}

EDITION_PUBLISHER_LIT = (RDAM["P30176"], None, None)
EDITION_PUBLISHER_OBJ = (RDAM["P30176"],)

ROLES = [
    ("author",       MARCREL["aut"]),
    ("editor",       MARCREL["edt"]),
    ("translator",   MARCREL["trl"]),
    ("publisher_2",  MARCREL["pbl"]),
    ("illustrator",  MARCREL["ill"]),
]

ROLE_META_PRED_MAP = {
    "first_name": (FOAF.givenName, None, None),
    "last_name":  (FOAF.familyName, None, None),
    "name":       (FOAF.name, None, None),
    "gender":     (FOAF.gender, None, None),
    "start":      (BNF["firstYear"], "gYear", None),
    "end":        (BNF["lastYear"], "gYear", None),
}

# ---------------- Costruzione grafo

def to_gyear_or_none(val: str):
    if val is None:
        return None
    s = str(val).strip()
    if re.fullmatch(r"-?\d{4}", s):
        return s
    m = re.search(r"-?\d{4}", s)
    return m.group(0) if m else None

def add_lit(g: Graph, s: URIRef, p, v, dtype=None, lang=None):
    if v is None or v == "":
        return
    if lang:
        g.add((s, p, Literal(str(v), lang=lang)))
        return
    if dtype == "gYear":
        gy = to_gyear_or_none(v)
        if gy is not None:
            g.add((s, p, Literal(gy, datatype=XSD.gYear)))
        else:
            g.add((s, p, Literal(str(v))))
        return
    g.add((s, p, Literal(str(v))))

def add_obj(g: Graph, s: URIRef, p, v):
    """Aggiunge una triple s p o se v è un URI (dopo normalizzazione)."""
    v_norm = normalize_uri(v)
    if v_norm and is_uri(v_norm):
        g.add((s, p, URIRef(v_norm)))

def add_actor_row(g: Graph, row: pd.Series, use_actor_year: bool = False):
    actor_uri = row.get("actor")
    if not is_uri(str(actor_uri).strip("<> ")):
        return
    s = URIRef(normalize_uri(actor_uri))
    for col, (pred, dtype, lang) in ACTOR_LITS.items():
        if col in row and row[col] != "":
            add_lit(g, s, pred, row[col], dtype=dtype, lang=lang)
    if use_actor_year and "year" in row and row["year"]:
        add_lit(g, s, DCTERMS.date, row["year"], dtype="gYear")
    if "actor_link_exact" in row and row["actor_link_exact"]:
        for v in maybe_split_values(row["actor_link_exact"]):
            add_obj(g, s, OWL.sameAs, v)
    if "actor_link_close" in row and row["actor_link_close"]:
        for v in maybe_split_values(row["actor_link_close"]):
            add_obj(g, s, SKOS.closeMatch, v)

def add_edition_row(g: Graph, row: pd.Series):
    ed_uri = row.get("edition")
    if not is_uri(str(ed_uri).strip("<> ")):
        return
    s = URIRef(normalize_uri(ed_uri))

    y = row.get("year_dir") or row.get("publication_year")
    if y:
        add_lit(g, s, BNF["firstYear"], y, dtype="gYear")

    for col, (pred, dtype, lang) in EDITION_LITS.items():
        if col in row and row[col] != "":
            add_lit(g, s, pred, row[col], dtype=dtype, lang=lang)

    if "publisher" in row and row["publisher"]:
        for v in maybe_split_values(row["publisher"]):
            if is_uri(v):
                add_obj(g, s, EDITION_PUBLISHER_OBJ[0], v)
            else:
                add_lit(g, s, EDITION_PUBLISHER_LIT[0], v)

    for col, (pred,) in EDITION_OBJS.items():
        if col in row and row[col]:
            for v in maybe_split_values(row[col]):
                add_obj(g, s, pred, v)

    for role, pred in ROLES:
        agent_val = row.get(role)
        if not agent_val:
            continue
        for agent_uri in maybe_split_values(agent_val):
            if not is_uri(agent_uri):
                continue
            agent = URIRef(normalize_uri(agent_uri))
            g.add((s, pred, agent))

            lex = row.get(f"{role}_link_exact", "")
            if lex:
                for v in maybe_split_values(lex):
                    add_obj(g, agent, OWL.sameAs, v)

            lcl = row.get(f"{role}_link_close", "")
            if lcl:
                for v in maybe_split_values(lcl):
                    add_obj(g, agent, SKOS.closeMatch, v)

            et = row.get(f"{role}_entity_type")
            if et and is_uri(normalize_uri(et)):
                g.add((agent, RDF.type, URIRef(normalize_uri(et))))

            for suf, (pp, dtype, lang) in ROLE_META_PRED_MAP.items():
                colname = f"{role}_{suf}"
                if colname in row and row[colname]:
                    add_lit(g, agent, pp, row[colname], dtype=dtype, lang=lang)

# builder RA per SINGOLO FILE
def build_actor_graph_from_file(csv_path: Path, use_actor_year: bool = False) -> Graph:
    g = Graph()
    bind_prefixes(g)
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    for _, row in tqdm(df.iterrows(), total=len(df), leave=False, desc=f"rows:{csv_path.name}"):
        add_actor_row(g, row, use_actor_year=use_actor_year)
    return g

# builder BR da LISTA di file (chunk)
def build_edition_graph_from_files(files: List[Path], tranche_name: str = "Edition files") -> Graph:
    g = Graph()
    bind_prefixes(g)
    for f in tqdm(files, desc=tranche_name):
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        for _, row in tqdm(df.iterrows(), total=len(df), leave=False, desc=f"rows:{f.name}"):
            add_edition_row(g, row)
    return g

# utility di chunking
def chunked(seq: List[Path], size: int) -> List[List[Path]]:
    return [seq[i:i+size] for i in range(0, len(seq), size)]

# nomi file di output (prefisso)
def derive_paths(out_path: Path):
    stem, ext, out_dir = out_path.stem, out_path.suffix, out_path.parent
    return stem, ext, out_dir

# serializzazione: pezzi sempre NT
def serialize_piece_nt(g: Graph, path: Path, label: str):
    g.serialize(destination=str(path), format="nt")
    print(f"{label} scritto (NT): {path}  (triples: {len(g)})")

# merge NT veloce
def concat_nt(input_paths: List[Path], merged_nt_path: Path):
    with open(merged_nt_path, "wb") as w:
        for p in tqdm(input_paths, desc="Merging NT pieces"):
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w)
    print(f"Merge NT (concat): {merged_nt_path}")

# header Turtle da premettere (prefissi unificati, indipendenti da RA/BR)
TTL_HEADER = """@prefix rdf: <{rdf}> .
@prefix rdfs: <{rdfs}> .
@prefix owl: <{owl}> .
@prefix xsd: <{xsd}> .
@prefix skos: <{skos}> .
@prefix foaf: <{foaf}> .
@prefix dcterms: <{dcterms}> .
@prefix rdam: <{rdam}> .
@prefix rdarelationships: <{rdarel}> .
@prefix marcrel: <{marcrel}> .
@prefix bnf-onto: <{bnf}> .
@prefix bio: <{bio}> .

""".format(
    rdf=str(RDF), rdfs=str(RDFS), owl=str(OWL), xsd=str(XSD),
    skos=str(SKOS), foaf=str(FOAF), dcterms=str(DCTERMS),
    rdam=str(RDAM), rdarel=str(RDAREL), marcrel=str(MARCREL),
    bnf=str(BNF), bio=str(BIO),
)

def nt_wrap_as_turtle(merged_nt_path: Path, ttl_path: Path):
    with open(ttl_path, "wb") as out:
        out.write(TTL_HEADER.encode("utf-8"))
        with open(merged_nt_path, "rb") as src:
            shutil.copyfileobj(src, out)
    print(f"Turtle scritto (header + NT): {ttl_path}")

# ---------------- CLI

def main():
    ap = argparse.ArgumentParser(description="CSV (Attori + Edizioni) → RDF (pezzi NT veloci + merge NT + wrapper finale TTL senza parsing)")
    ap.add_argument("--actors-root", required=True, type=Path, help="Root directory con CSV degli attori (cartelle annidate)")
    ap.add_argument("--editions-root", required=True, type=Path, help="Root directory con CSV delle edizioni (cartelle annidate)")
    ap.add_argument("--out", required=True, type=Path, help="Percorso file finale .ttl")
    ap.add_argument("--br-chunk", type=int, default=50, help="Dimensione dei blocchi BR (default: 50)")
    ap.add_argument("--use-actor-year", action="store_true",
                    help="Mappa la colonna 'year' dei CSV attori in dcterms:date (xsd:gYear) con fallback a literal.")
    ap.add_argument("--keep-nt", action="store_true", help="Mantieni i pezzi .nt e l'NT finale dopo il wrapping")
    ap.add_argument("--dedupe", action="store_true", help="Dedupe delle triple (line-based) dopo il merge NT")
    ap.add_argument("--dedupe-shards", type=int, default=64, help="Numero shard per la dedupe NT (default: 64)")

    args = ap.parse_args()

    if args.out.suffix.lower() != ".ttl":
        print("Consigliato: imposta --out con estensione .ttl (es. data/reverse_unified_graph.ttl)")

    stem, ext, out_dir = derive_paths(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"{stem}_nt_pieces_", dir=str(out_dir)))
    print(f"Temp dir: {tmp_dir}")

    nt_pieces: List[Path] = []

    # 1) RA: un file NT per CSV
    actor_files = sorted([p for p in args.actors_root.rglob("*.csv")])
    for i, f in enumerate(tqdm(actor_files, desc="Actor files"), start=1):
        g_ra = build_actor_graph_from_file(f, args.use_actor_year)
        ra_nt_path = tmp_dir / f"{stem}_ra_{i:04d}.nt"
        serialize_piece_nt(g_ra, ra_nt_path, f"Agents graph [{i}/{len(actor_files)}]")
        nt_pieces.append(ra_nt_path)

    # 2) BR: un file NT ogni N CSV
    edition_files = sorted([p for p in args.editions_root.rglob("*.csv")])
    br_chunks = chunked(edition_files, args.br_chunk)
    for j, chunk in enumerate(tqdm(br_chunks, desc=f"Edition chunks (size={args.br_chunk})"), start=1):
        g_br = build_edition_graph_from_files(chunk, tranche_name=f"Edition files chunk {j}/{len(br_chunks)}")
        br_nt_path = tmp_dir / f"{stem}_br_{j:04d}.nt"
        serialize_piece_nt(g_br, br_nt_path, f"Bibliographic graph (chunk {j})")
        nt_pieces.append(br_nt_path)

    # 3) Merge NT
    merged_nt_path = tmp_dir / f"{stem}_ALL.nt"
    concat_nt(nt_pieces, merged_nt_path)

    # 3b) Dedupe opzionale
    dedup_source = merged_nt_path
    if args.dedupe:
        dedup_nt_path = tmp_dir / f"{stem}_ALL_dedup.nt"
        dedupe_nt_lines(merged_nt_path, dedup_nt_path, shards=args.dedupe_shards, tmp_root=tmp_dir)
        dedup_source = dedup_nt_path

    # 4) Wrapping NT → Turtle (senza parsing)
    nt_wrap_as_turtle(dedup_source, args.out)

    # 5) Pulizia
    if not args.keep_nt:
        try:
            shutil.rmtree(tmp_dir)
            print("Rimossi i file NT temporanei.")
        except Exception as e:
            print(f"Impossibile rimuovere {tmp_dir}: {e}")
    else:
        print(f"File NT mantenuti in: {tmp_dir}")

if __name__ == "__main__":
    main()

'''
python reverse_graph_creator.py \
  --actors-root data/unified_agents \
  --editions-root data/unified_dataset/unified_chunks \
  --out data/reverse_unified_graph.ttl \
  --br-chunk 20 \
  --keep-nt \
  --dedupe \
  --dedupe-shards 64
'''
