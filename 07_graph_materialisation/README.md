# 07_graph_materialisation — BnF graph pipeline

Converts preprocessed BnF actor and edition data into RDF N-Triples via
[morph-kgc](https://morph-kgc.readthedocs.io/) and YARRRML mappings, implementing
the [CHAD-AP](https://dharc-org.github.io/chad-ap/current/chad-ap.html) application
profile (development/14, `https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/`).

All generated artefacts stay inside this folder:

```text
07_graph_materialisation/
  input/ready_to_convert/          # full preprocessed CSVs  (generated)
  input/sample_ready_to_convert/   # sample preprocessed CSVs (generated)
  output/full/                     # full RDF N-Triples outputs (generated)
  output/sample/                   # sample RDF N-Triples outputs (generated)
  output/runtime_configs/          # generated morph-kgc ini configs
  output/logs/                     # timestamped pipeline logs and reports
  logs/                            # pipeline script logs
  scripts/bnf_graph_pipeline.py    # low-level pipeline commands
  run_full_pipeline.py             # high-level orchestrator
  mapping_actors.yaml              # YARRRML: actors + authority links
  mapping_bibliographic.yaml       # YARRRML: editions + ESTC seeAlso
  mapping_roles.yaml               # YARRRML: edition–actor role edges
  pipeline_config.ini              # all configurable paths and settings
  udfs.py                          # morph-kgc user-defined functions
```

---

## Input sources (priority order)

The preprocess step automatically picks the best available upstream source:

| Priority | Source | Path |
|----------|--------|------|
| 1 | Module 06 enriched actors | `06_mapping/output/bnf_actors_enriched.csv` |
| 2 | Module 05 optimised actors | `05_subset_optimisation/output/bnf_actors_optimised.csv` |
| 3 | Legacy raw ZIP | `01_data_retrieval/02_actors/data/old_zip/actor_data.zip` |
| 1 | Module 06 enriched editions | `06_mapping/output/bnf_editions_enriched.csv` |
| 3 | Legacy raw ZIP | `01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip` |

The module 05 minimal CSV (`bnf_actors_optimised_minimal.csv`) is merged in
automatically to supply `actor_link_exact` / `actor_link_close` when those
columns are absent from the enriched actors file.

All paths are configured in `pipeline_config.ini`.

---

## What gets materialised

| Graph target | Source CSV(s) | Output file | Content |
|---|---|---|---|
| `actors` | `bnf_actors_ready.csv`, link CSVs | `knowledge-graph_actors.nt` | Actor types, names, events, country, profession — all modelled with CHAD-AP `obj:` classes and properties. External links: `owl:sameAs` VIAF/Wikidata, `rdfs:seeAlso` ISNI/LC |
| `bibliographic` | `bnf_editions_ready.csv` | `knowledge-graph_bibliographic.nt` | Editions (`lrmoo:F3_Manifestation`), expressions, works, titles, dates, publishers, subjects. Shared elements (identifiers, appellations, time-spans, places, actors) use CHAD-AP `obj:` classes. `rdfs:seeAlso` ESTC |
| `roles` | `bnf_actors_ready_roles.csv` | `knowledge-graph_roles.nt` | Edition–actor role edges: `crm:E7_Activity` typed via `obj:hasType` with AAT concept, linked to actor via `crm:P14_carried_out_by`, attached to `lrmoo:F28_Expression_Creation` via `crm:P9_consists_of` |
| *(merged)* | all three | `knowledge-graph_merged.nt` | Union of all above |

The roles graph is only materialised when `bnf_actors_ready_roles.csv` exists
(i.e., when the upstream actors data contains a `role_edition_map` column).

---

## Recommended workflow: full orchestrator

```bash
cd /path/to/07_graph_materialisation

# 1. Preprocess (reads enriched CSVs from modules 05/06, or falls back to ZIPs)
/Users/ariannamorettj/miniforge3/bin/python3.12 scripts/bnf_graph_pipeline.py \
    preprocess --profile full --force

# 2. Run the full pipeline (materialise → validate → merge → report)
/Users/ariannamorettj/miniforge3/bin/python3.12 run_full_pipeline.py \
    --profile full

# Optional flags for run_full_pipeline.py:
#   --skip-actors   reuse latest existing actors .nt
#   --skip-bib      reuse latest existing bibliographic .nt
#   --skip-roles    omit roles materialisation from this run
#   --sample-lines  lines to validate per graph (default 10 000)
```

---

## Step-by-step workflow (low-level)

All commands run from `07_graph_materialisation/`.

### 1 — Preprocess

Reads upstream enriched/optimised CSVs (or legacy ZIPs) and writes ready CSVs,
including the roles table and authority URI columns.

```bash
# Full dataset
python3.12 scripts/bnf_graph_pipeline.py preprocess --profile full --force

# Sample (20 rows per dataset)
python3.12 scripts/bnf_graph_pipeline.py preprocess --profile sample --sample 20 --force
```

### 2 — Materialise

```bash
# All targets (actors + bibliographic + roles if roles CSV present)
python3.12 scripts/bnf_graph_pipeline.py materialize --profile full

# Single target
python3.12 scripts/bnf_graph_pipeline.py materialize --profile full --target actors
python3.12 scripts/bnf_graph_pipeline.py materialize --profile full --target bibliographic
python3.12 scripts/bnf_graph_pipeline.py materialize --profile full --target roles
```

### 3 — Validate

```bash
python3.12 scripts/bnf_graph_pipeline.py validate --profile full --target actors
python3.12 scripts/bnf_graph_pipeline.py validate --profile full --target bibliographic
python3.12 scripts/bnf_graph_pipeline.py validate --profile full --target roles
python3.12 scripts/bnf_graph_pipeline.py validate --profile full --target merged
```

### 4 — Merge

Concatenates all `knowledge-graph_*.nt` files present in the output directory
(actors, bibliographic, roles if available) into `knowledge-graph_merged.nt`.

```bash
python3.12 scripts/bnf_graph_pipeline.py merge --profile full
```

### 5 — All-in-one (sample)

```bash
python3.12 scripts/bnf_graph_pipeline.py all --profile sample --sample 20 --force
```

---

## Ready CSV files

| File | Produced by | Used by |
|---|---|---|
| `bnf_actors_ready.csv` | preprocess | `mapping_actors.yaml` — includes `viaf_uri`, `wikidata_uri`, `isni_uri`, `lc_uri` columns |
| `bnf_actors_ready_links_exact.csv` | preprocess | `mapping_actors.yaml` |
| `bnf_actors_ready_links_close.csv` | preprocess | `mapping_actors.yaml` |
| `bnf_actors_ready_roles.csv` | preprocess (`role_edition_map` column) | `mapping_roles.yaml` |
| `bnf_editions_ready.csv` | preprocess | `mapping_bibliographic.yaml` — includes `estc_uri` column |

---

## Notes

- All three mapping files implement the **CHAD-AP application profile** (development/14). Classes and properties that have a local CHAD-AP wrapper use the `obj:` prefix; bibliographic-specific classes (LRMoo `F*`, `crm:E7_Activity`, `crmdig:D9_Data_Object`, etc.) use their canonical base-ontology URIs, which CHAD-AP declares without wrapping.
- Sample and full profiles never share ready or output directories.
- morph-kgc is run as a subprocess (not via `materialize_set()`) to avoid loading the full graph in memory.
- Malformed IRI values are filtered out before materialisation.
- morph-kgc temporary files (e.g. `0-0-0-0.nt`) are written into target-specific tmp folders, then concatenated and renamed automatically.
- Output filenames from `run_full_pipeline.py` are timestamped so no existing file is ever overwritten.
- `role_edition_map` format expected from module 05: `author:id1,id2;editor:id3` — role names must be one of `author`, `editor`, `translator`, `illustrator` (others are skipped).
- Edition IDs inside `role_edition_map` can be full IRIs, ARK fragments (`cb…`), or bare numeric BnF IDs.
