Here is the English translation:

---

## **General Overview**

The software implements an **end-to-end pipeline** to acquire, inspect, clean, harmonise, and transform into an RDF graph the bibliographic data (editions/manifestations) and actor data (bibliographic agents) from the SPARQL endpoint of the **Bibliothèque nationale de France (BnF)** — `https://data.bnf.fr/sparql`.

The ultimate goal is to produce a **knowledge graph** conforming to the **CHAD-AP** application profile (development/14), integrating the BnF dataset with external authorities (VIAF, Wikidata, ESTC/ECCO).

The pipeline is organised into **8 numbered modules**, each in a dedicated folder, ensuring a clear execution order and allowing partial re-runs of individual stages.

---

## **Pipeline Architecture**

```
BnF SPARQL endpoint
        │
        ▼
┌──────────────────────┐
│  00_monitor          │  Monitoring system (cross-stage)
└──────────────────────┘
        │ (optional, integrated in each module)
        ▼
┌──────────────────────┐
│  01_data_retrieval   │  Data acquisition (R)
└──────────────────────┘
        │  bnf_edition_data_raw.csv + actor_data.csv
        ▼
┌──────────────────────┐
│  02_sampling         │  Exploratory inspection (Python)
└──────────────────────┘
        │  structural reports and value samples
        ▼
┌──────────────────────┐
│  03_analysis         │  Quantitative analysis (Python)
└──────────────────────┘
        │  field profiles, cardinality, duplicates
        ▼
┌──────────────────────────────────────┐
│  04_harmonisation_and_evaluation     │  Harmonisation + QA (Python)
└──────────────────────────────────────┘
        │  harmonised CSVs with _original / _harmonised columns
        ▼
┌──────────────────────┐
│  05_subset_optim.    │  Actor dataset optimisation (Python)
└──────────────────────┘
        │  bnf_actors_optimised.csv + role_edition_map
        ▼
┌──────────────────────┐
│  06_mapping          │  Mapping to external authorities (Python + LLM)
└──────────────────────┘
        │  bnf_actors_enriched.csv + bnf_editions_enriched.csv
        ▼
┌──────────────────────┐
│  07_graph_material.  │  RDF materialisation (Python + morph-kgc)
└──────────────────────┘
        │  knowledge-graph_merged.nt (N-Triples)
        ▼
      CHAD-AP RDF Graph
```

---

## **Modules — Detailed Description**

---

### **`00_monitor` — Monitoring System**

**Languages:** Python and R (mirrored implementations)

**Scripts:** **`monitor.py`** · **`monitor.R`**

Provides a passive monitoring layer for long-running processes.

### **Metrics collected**

| **Metric** | **Source** |
| --- | --- |
| System CPU | `/proc/stat` (delta between samples) |
| System memory | `/proc/meminfo` (`MemTotal`, `MemAvailable`) |
| Disk | `df -P /` |
| Network throughput | delta byte counters (Download/Upload in Mbps) |
| GPU (if NVIDIA) | `nvidia-smi` |
| Process CPU | CPU jiffies + wall-clock time |
| Process memory | RSS / total memory |

### **Operating modes**

- **Continuous standalone**: infinite loop with configurable interval; writes one block of metrics per cycle.
- **Embedded state-based**: checkpoint API called from other scripts (`start_monitor_state()`, `update_monitor_state()`, `stop_monitor_state()`); does not start infinite loops.

### **Output**

Timestamped text reports in `00_monitor/report/`, with header, per-cycle/checkpoint blocks (with optional text context), and footer.

**NOTES**

The monitor requires `/proc/*` files typical of Linux. Pure functions (formulas, report I/O) can be tested on macOS/Windows as well, but live monitoring requires Linux.

---

### **`00_test` — Automated Test Suite**

**Scripts:** **`test_monitor_py.py`** · **`test_monitor_R.R`** · **`test_place_harmonisation.py`** · **`test_query_actors.R`** · **`test_query_editions.R`**

Covers the deterministic behaviours of the main components:

- Monitor formulas and helpers (Python + R)
- Resume logic and SPARQL queries for editions and actors (R)
- Publication place harmonisation (Python)

---

### **`01_data_retrieval` — Data Acquisition**

**Language:** R

**Technologies:** SPARQL, endpoint `https://data.bnf.fr/sparql`

Two R scripts work in sequence to produce the two base datasets.

### **Stage 1 — `query_editions.R`**

Retrieves bibliographic data **year by year** (from 1454 onwards).

**Process:**

1. Builds and executes a SPARQL query for each year (`FILTER(?year_first = <YEAR>)`)
2. Writes a CSV per year to `data/edition_raw_data_by_year/`
3. Compiles all annual CSVs into `bnf_edition_data_raw.csv`
4. Computes descriptive statistics (unique editions, field coverage)

**Resume logic:** restarts from the maximum year already present in the annual folder (repeats the last year; not a strict skip-to-next mechanism).

**Fields retrieved per edition:** `edition`, `bnf_id`, `title`, `year_first`, `year_range`, `description`, `place`, `publisher`, `work`, `digital_copy_link`, `subject_topic`, `expression`, `language`, `record_type`, `author`, `editor`, `translator`, `publisher_2`, `illustrator`

### **Stage 2 — `query_agents.R`**

Reads the editions dataset and, for each unique actor URI found in the role columns, executes an enrichment SPARQL query.

**Process:**

1. Extracts unique URIs from `author`, `editor`, `translator`, `publisher_2`, `illustrator`
2. For each actor: builds the query, writes an intermediate CSV (if non-empty), updates `last_processed_index.txt`
3. At completion: merges all intermediate CSVs into `actor_data.csv`

**Resume logic:** resumes from index `last_processed_index + 1` (strict index-based mechanism).

**Fields retrieved per actor:** `actor`, `actor_birth`, `actor_name`, `actor_first_name`, `actor_last_name`, `entity_type`, `first_year`, `actor_country`, `actor_language`, `actor_gender`, `actor_profession`, `actor_death`, `actor_start`, `actor_end`, `actor_link_exact`, `actor_link_close`

**IMPORTANT**

An actor may appear on multiple rows because `skos:exactMatch`/`closeMatch` return one binding per value, generating row multiplicity.

---

### **`02_sampling` — Exploratory Inspection**

**Language:** Python

**Scripts:** **`01_zip_tree.py`** · **`02_column_names.py`** · **`03_full_row_sample.py`** · **`04_column_value_sample.py`**

**Shared library:** **`sampling_utils.py`**

Supports manual inspection of zipped datasets. All scripts operate on ZIPs (including nested ones) without modifying the source data.

| **Script** | **Function** | **Output** |
| --- | --- | --- |
| `01_zip_tree.py` | Internal structure of ZIP file (tree + counts by extension) | `.txt` report |
| `02_column_names.py` | All column names found in internal CSVs; optional filter by year or file | `.txt` report |
| `03_full_row_sample.py` | N best-populated rows, with iterative fallback (increasing null tolerance) | `.csv` sample |
| `04_column_value_sample.py` | N values evenly distributed per column (or specific column) | `.txt` per column |

**Recommended order:** `01` → `02` → `03` → `04` (archive structure → column schema → concrete rows → value variety).

**Main intellectual output:** the **Transition Table** in the **02_sampling README** that classifies each field as "requires harmonisation" vs "quantitative check only".

---

### **`03_analysis` — Quantitative Analysis**

**Language:** Python

**Main scripts:** **`01_field_values.py`** · **`02_column_unique_values.py`** · **`03_subset_by_value.py`** · **`04_actor_field_cardinality.py`** · **`05_dataset_profiler.py`**

In-depth statistical analysis of the raw datasets.

| **Script** | **Description** |
| --- | --- |
| `01_field_values.py` | Extracts distinct values for selected fields from CSV/ZIP |
| `02_column_unique_values.py` | Unique values per column with counts |
| `03_subset_by_value.py` | Extracts subsets of rows filtered by a field value |
| `04_actor_field_cardinality.py` | Cardinality per actor field (how many distinct values per actor) |
| `05_dataset_profiler.py` | **Full profiler**: counts non-empty, unique values, fill rate %, top-10 most frequent values (excludes null/NA/N/A/None/null) |

**Specialised subfolders:**

- `actors/` — analyses specific to the actor dataset
- `bib_resources/` — analyses for the bibliographic dataset
- `actors/names/` — AI-assisted toolkit for name classification (Flair NER, rules, review table generation)

### **Names Toolkit (in `actors/names/`)**

| **Script** | **Role** |
| --- | --- |
| `detect_real_names.py` | Rule-based classification (real names vs. noise) |
| `enhanced_detect_names.py` | Classification with Flair NER |
| `enhanced_detect_names_cleaner.py` | Noise removal from classified names |
| `csv_analysis_maker.py` | Generates CSV table for manual review |

---

### **`04_harmonisation_and_evaluation` — Harmonisation and QA**

Divided into two sub-modules:

### **`01_harmonisation` — Normalisation Scripts**

**Language:** Python

**Structure:** each field has its own folder, containing:

- `01_heuristic_rules/` — deterministic approach (regex, dictionaries, substitutions)
- `02_llm_based/` — LLM approach for remaining ambiguous cases

**Fields covered:**

| **Folder** | **Field(s)** | **Status** |
| --- | --- | --- |
| `actor_name/` | `actor_name`, `actor_first_name`, `actor_last_name` | 🔄 In progress |
| `actor_dates/` | `actor_birth`, `actor_death`, `actor_start`, `actor_end` | 📋 Planned |
| `external_links/` | `actor_link_close`, `actor_link_exact` | 📋 Planned |
| `publication_place/` | `place` | ✅ Approach 02 complete |
| `publisher/` | `publisher_1` | 📋 Planned |
| `language/` | `language` | 📋 Planned |

**Output of each normaliser:**

| **Column** | **Content** |
| --- | --- |
| `<id_column>` | Primary key URI |
| `<field>_original` | Raw value |
| `<field>_harmonised` | Normalised value |
| `correction_type` | Rule/approach label |
| `confidence` | `high` / `medium` / `low` |
| `llm_explanation` | (LLM only) Textual justification |

### **`02_evaluation` — Quality Evaluators**

**Architecture:** base class `Evaluation` (**`evaluation_base.py`**) + subclasses per field.

```
Evaluation (base)
├── PersonNameEvaluation       → actor_name_evaluation.py       ✅
├── ActorDatesEvaluation       → actor_dates_evaluation.py      🔄
├── ExternalLinksEvaluation    → external_links_evaluation.py   🔄
├── PublicationPlaceEvaluation → publication_place_evaluation.py 🔄
├── PublisherEvaluation        → publisher_evaluation.py        🔄
└── LanguageEvaluation         → language_evaluation.py         🔄
```

The base class provides: CSV/ZIP reading, iteration with progress bar, report writing.

Each subclass implements `evaluate_value(value)` which returns `warnings` and `errors`.

**Reports produced per field:**

- `<field>_summary.csv` — case label / type / count / percentage
- `<field>_warnings.csv` — original value → warnings
- `<field>_errors.csv` — original value → error label → suggested replacement

**Entry point:** **`run_evaluation.py`** — dispatcher that routes by column name.

---

### **`05_subset_optimisation` — Actor Dataset Optimisation**

**Language:** Python

**Scripts:** **`roles_enricher.py`** · **`gen_subset_optm.py`** · **`extract_minimal.py`**

Produces an **optimised** actor dataset (one row per actor) with bibliographic role information.

### **Step 1 — `roles_enricher.py`**

Scans the raw editions dataset and builds, for each actor, the role → editions mapping.

**Key output — `actor_roles_links.csv`:**

- `role_edition_map`: `"author:id1,id2;editor:id3"`
- `roles`: `"author;editor"` (flat list for fast filtering)

Supports filtering by year range (`--year-from` / `--year-to`).

### **Step 2 — `gen_subset_optm.py`**

Aggregates the actor dataset (one row per actor), enriches with roles, optionally filters by year and deduplicates on a chosen field.

**Main output — `bnf_actors_optimised.csv`:** `BnF_ID, actor_name, actor_first_name, actor_last_name, actor_birth, actor_death, actor_start, actor_end, first_year, entity_type, actor_gender, actor_country, actor_language, actor_link_exact, actor_link_close, role_edition_map, roles`

**Minimal output — `bnf_actors_optimised_minimal.csv`:** `BnF_ID, actor_name, actor_link_exact, actor_link_close`

**NOTES**

`actor_profession` is not a direct field in the output: the bibliographic role (from `role_edition_map`) is considered the most reliable proxy for the agent's professional function in the Early Modern book trade.

---

### **`06_mapping` — Enrichment with External Authorities**

**Language:** Python (+ optional Claude API)

Links the BnF dataset to three external authority catalogues.

| **Script** | **Target** | **Method** |
| --- | --- | --- |
| **`01_map_viaf.py`** | VIAF | ID lookup → SRU name search (Levenshtein ≥ 0.85) |
| **`02_map_wikidata.py`** | Wikidata | QID lookup → SPARQL label search |
| **`03_map_estc_ecco.py`** | ESTC/ECCO | Heuristic field matching + LLM translation check |
| **`04_merge_mappings.py`** | — | Join of all mappings → final enriched datasets |

### **Algorithm details**

**VIAF (01):**

- Pass 1 (ID-based): VIAF URIs already present in `actor_link_exact`/`actor_link_close` → VIAF REST API for preferred name, dates, co-referents (Wikidata QID, LC, IdRef)
- Pass 2 (name-based): SRU search if VIAF URI is absent; accepted if Levenshtein similarity ≥ threshold

**Wikidata (02):**

- Pass 1 (ID-based): QID from existing links or from VIAF mapping → MediaWiki Entity API (labels, dates, BnF ARK authority P268, VIAF P214, ISNI P213, LC P244)
- Pass 2 (SPARQL label): Wikidata Query Service query with filter on `rdfs:label` in French (±2 years birth date)

**ESTC/ECCO (03):**

- Pass 1 (ID bridge): via VIAF ID shared between BnF and ESTC (scaffolded; requires ESTC authority table with VIAF ID)
- Pass 2 (heuristic): year filter ±`year_window`, author similarity ≥ 0.80, title similarity ≥ 0.75
- Pass 3 (LLM, optional): if author passes but title does not, and languages differ → Claude prompt to verify whether it is a translation. Requires `ANTHROPIC_API_KEY`. Output logged in `report/llm_calls.jsonl` for reproducibility.

**Final outputs (04):**

- `bnf_actors_enriched.csv` — actors with additional columns: `viaf_id`, `qid`, `isni`, `lc_id`, etc.
- `bnf_editions_enriched.csv` — editions with additional columns: `estc_id`, `estc_title`, `estc_confidence`, etc.

---

### **`07_graph_materialisation` — RDF Materialisation**

**Language:** Python

**RDF engine:** morph-kgc + YARRRML mappings

**Standard:** CHAD-AP development/14

**Scripts:** **`run_full_pipeline.py`** (orchestrator) + **`scripts/bnf_graph_pipeline.py`** (low-level commands)

### **Input (in priority order)**

| **Priority** | **Source** | **Path** |
| --- | --- | --- |
| 1 | Enriched actors (Module 06) | `06_mapping/output/bnf_actors_enriched.csv` |
| 2 | Optimised actors (Module 05) | `05_subset_optimisation/output/bnf_actors_optimised.csv` |
| 3 | Raw ZIP fallback | `01_data_retrieval/02_actors/data/old_zip/actor_data.zip` |
| 1 | Enriched editions (Module 06) | `06_mapping/output/bnf_editions_enriched.csv` |
| 3 | Raw ZIP fallback | `01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip` |

### **YARRRML Mappings**

| **File** | **Content** |
| --- | --- |
| **`mapping_actors.yaml`** | Actor types, names, events (birth/death), country, profession; authority links: `owl:sameAs` VIAF/Wikidata, `rdfs:seeAlso` ISNI/LC |
| **`mapping_bibliographic.yaml`** | Editions (`lrmoo:F3_Manifestation`), expressions, works, titles, dates, publishers, subjects; `rdfs:seeAlso` ESTC |
| **`mapping_roles.yaml`** | Role arcs edition→actor: `crm:E7_Activity` typed via `obj:hasType` with AAT concept |

### **RDF Output (N-Triples)**

| **File** | **Content** |
| --- | --- |
| `knowledge-graph_actors.nt` | Actors graph |
| `knowledge-graph_bibliographic.nt` | Bibliographic graph |
| `knowledge-graph_roles.nt` | Roles graph (if `role_edition_map` present) |
| `knowledge-graph_merged.nt` | Union of all three |

### **Pipeline stages (commands)**

```bash
# 1. Preprocess (reads upstream CSV or fallback ZIP, writes ready CSVs)
python3.12 scripts/bnf_graph_pipeline.py preprocess --profile full --force

# 2. Materialise (morph-kgc → N-Triples)
python3.12 scripts/bnf_graph_pipeline.py materialize --profile full

# 3. Validate (samples N triples, checks syntax)
python3.12 scripts/bnf_graph_pipeline.py validate --profile full --target merged

# 4. Merge (concatenates .nt → merged.nt)
python3.12 scripts/bnf_graph_pipeline.py merge --profile full

# Or all in one (orchestrator):
python3.12 run_full_pipeline.py --profile full
```

Supports `--profile sample` (N rows for quick testing) and `--profile full` (complete dataset).

---

## **Complete End-to-End Data Flow**

```
BnF SPARQL
    │
    ├─[query_editions.R]─────────────────────────────────────────►  bnf_edition_data_raw.csv
    │                                                                          │
    └─[query_agents.R]──────────────────────────────────────────►  actor_data.csv
                                                                               │
                                          02_sampling (inspection) ◄───────────┤
                                                                               │
                                          03_analysis (profiling) ◄────────────┤
                                                                               │
                               04_harmonisation (normalisation) ◄──────────────┤
                                                                               │
                             05_subset_optimisation (one row/actor) ◄──────────┤
                                                                    bnf_actors_optimised.csv
                                                                               │
                                 06_mapping (VIAF/Wikidata/ESTC) ◄────────────┤
                                                                    bnf_actors_enriched.csv
                                                                    bnf_editions_enriched.csv
                                                                               │
                             07_graph_materialisation (RDF/CHAD-AP) ◄──────────┘
                                                                    knowledge-graph_merged.nt
```

---

## **Technologies and Dependencies**

| **Component** | **Technologies** |
| --- | --- |
| Data acquisition | R, `SPARQL`, `tidyverse` packages |
| Inspection and analysis | Python (stdlib: `zipfile`, `csv`, `io`, `json`) |
| Name NER | Flair (NER model) |
| Authority mapping | VIAF REST API, Wikidata SPARQL, MediaWiki Entity API |
| LLM (optional) | Anthropic Claude API (`claude-sonnet-4-6`) |
| RDF materialisation | morph-kgc (subprocess), YARRRML |
| Ontological standards | CHAD-AP, LRMoo, CRMdig, FOAF, SKOS, MARC relators, BIO, BnF-onto |
| Testing | pytest (Python), testthat (R) |

---

## **Dataset Fields: Harmonisation Classification**

### **Actor Dataset (`actor_data.csv`)**

| **Field** | **Requires Harmonisation** |
| --- | --- |
| `actor_birth`, `actor_death`, `actor_start`, `actor_end` | ✅ Yes — dates with non-uniform formats |
| `actor_country`, `actor_language` | ✅ Yes — URIs to be resolved and enriched |
| `actor_name`, `actor_first_name`, `actor_last_name` | ✅ Yes — cleaning, titles, punctuation |
| `actor_profession` | ✅ Yes — free text, vocabulary mapping |
| `actor_link_exact`, `actor_link_close` | ✅ Yes — URI protocol normalisation |
| `actor` (URI), `entity_type`, `actor_gender` | ❌ No — already conformant |

### **Bibliographic Dataset (`bnf_edition_data_raw.csv`)**

| **Field** | **Requires Harmonisation** |
| --- | --- |
| `description`, `place`, `publisher`, `title`, `language` | ✅ Yes — free text or URI |
| `edition`, `bnf_id`, `expression`, `work`, `author/editor/translator/illustrator/publisher_2`, `year_first`, `year_range`, `record_type`, `subject_topic`, `digital_copy_link` | ❌ No — already conformant (quantitative check only) |

---

## **Operational Notes**

**TIP**

For partial runs: each module is independent thanks to the numbered folder structure. It is possible to re-run only the module of interest without restarting the entire pipeline.

**WARNING**

The two R retrieval scripts **do not clean** pre-existing output folders. Files with the same path are overwritten. The monitor does not delete previous reports.

**NOTE**

Pass 3 of the ESTC mapping (LLM) introduces a non-deterministic element. For reproducibility, all LLM calls are logged in `report/llm_calls.jsonl` with the model's complete response.

**CAUTION**

The monitoring system (`00_monitor`) requires access to Linux `/proc/*` files for live monitoring. On macOS (current development environment) pure function tests pass, but live monitoring will not work correctly.