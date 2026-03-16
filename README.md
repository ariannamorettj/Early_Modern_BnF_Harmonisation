# Actors and Editions Processing, Analysis, and RDF Graph Generation

This collection of Python scripts forms a coherent workflow for processing, unifying, analyzing, and transforming **agent (actor)** and **edition** datasets into structured and linked formats.
Each script performs a specific task — from inspecting raw CSVs and merging data to identifying duplicates, computing field statistics, and building RDF graphs.

---

## File List
0. [Data retrieval: get_edition_raw_data.R + query_missing_agents.R](#0_retrieval)
1. [main.py](#1_mainpy)
2. [agents_main.py](#2_agents_mainpy)
3. [actors_id_matching.py](#3_actors_id_matchingpy)
4. [actors_name_matching.py](#4_actors_name_matchingpy)
5. [actors_one_to_may_fields_analysis.py](#5_actors_one_to_may_fields_analysispy)
6. [actors_names_to_many_fields_analysis.py](#6_actors_names_to_many_fields_analysispy)
7. [names_with_multiple_ids.py](#7_names_with_multiple_idspy)
8. [reduce_actors_dataset.py](#8_reduce_actors_datasetpy)
9. [reverse_graph_creator.py](#9_reverse_graph_creatorpy)
10. [unique_values_per_field.py](#10_unique_values_per_fieldpy)
11. [sparql_queries.py](#11_sparql_queriespy)
12. [WORKFLOW OVERVIEW](#WORKFLOW)

---
## 0. Data retrieval 
<a id="0_retrieval"></a>

## BnF data acquisition: column-level documentation (README)

This repository contains two acquisition scripts:

* **Bibliographic entities (editions / manifestations / expressions):** `data/bnf_edition_data/get_edition_raw_data.R`
* **Agents (actors) enrichment:** `data/bnf_agents_data_querying/query_missing_agents.R`

The two outputs are conceptually distinct:

1. **Edition-level CSV**: records about bibliographic entities and their linked agents via MARC relators.
2. **Actor-level CSV**: authority-style enrichment for each agent URI harvested from the edition-level CSV.

---

### 1) Edition / bibliographic entity dataset (`bnf_edition_data_raw.csv`)

**Script:** `data/bnf_edition_data/get_edition_raw_data.R`
**Endpoint:** `https://data.bnf.fr/sparql`

### Columns

* **edition** → BnF URI of the edition/manifestation resource being queried
  → SPARQL pattern: `?edition bnf-onto:firstYear ?year_first .` (the `?edition` subject bound by this triple)

* **bnf_id** → FRBNF identifier for the edition/manifestation
  → `OPTIONAL { ?edition bnf-onto:FRBNF ?bnf_id . }`

* **title** → title string of the edition/manifestation
  → `OPTIONAL { ?edition dcterms:title ?title . }`

* **year_first** → first year associated with the edition/manifestation (used to drive yearly extraction)
  → `?edition bnf-onto:firstYear ?year_first .` and filtered via `FILTER(?year_first = <YEAR>)`

* **year_range** → date string/range associated with the edition/manifestation
  → `OPTIONAL { ?edition dcterms:date ?year_range . }`

* **description** → free-text description of the edition/manifestation
  → `OPTIONAL { ?edition dcterms:description ?description . }`

* **place** → place associated with the manifestation (RDA element)
  → `OPTIONAL { ?edition rdam:P30279 ?place . }`

* **publisher** → publisher statement/value associated with the manifestation (RDA element)
  → `OPTIONAL { ?edition rdam:P30176 ?publisher . }`

* **work** → linked Work resource manifested by the edition/manifestation
  → `OPTIONAL { ?edition rdarelationships:workManifested ?work . }`

* **digital_copy_link** → link/resource pointing to a digital copy (RDA element)
  → `OPTIONAL { ?edition rdam:P30016 ?digital_copy_link . }`

* **subject_topic** → subject resource(s) linked to the edition/manifestation
  → `OPTIONAL { ?edition dcterms:subject ?subject_topic . }`

* **expression** → linked Expression resource manifested by the edition/manifestation
  → `?edition rdarelationships:expressionManifested ?expression .`

* **language** → language of the Expression
  → `OPTIONAL { ?expression dcterms:language ?language . }`

* **record_type** → type of the Expression record
  → `OPTIONAL { ?expression dcterms:type ?record_type . }`

* **author** → agent URI linked to the Expression as author (MARC relator)
  → `OPTIONAL { ?expression marcrel:aut ?author . }`

* **editor** → agent URI linked to the Expression as editor (MARC relator)
  → `OPTIONAL { ?expression marcrel:edt ?editor . }`

* **translator** → agent URI linked to the Expression as translator (MARC relator)
  → `OPTIONAL { ?expression marcrel:trl ?translator . }`

* **publisher_2** → agent URI linked to the Expression as publisher (MARC relator)
  → `OPTIONAL { ?expression marcrel:pbl ?publisher_2 . }`

* **illustrator** → agent URI linked to the Expression as illustrator (MARC relator)
  → `OPTIONAL { ?expression marcrel:ill ?illustrator . }`

---

### 2) Actor / agent enrichment dataset (`actor_data.csv`)

**Script:** `data/bnf_agents_data_querying/query_missing_agents.R`
**Input dependency:** `bnf_edition_data_raw.csv`
**Endpoint:** `https://data.bnf.fr/sparql`

### How `actor` is obtained (not from SPARQL in this script)

The script reads the edition-level CSV and builds a unique list of agent URIs from the role columns:

* `author`, `editor`, `translator`, `publisher_2`, `illustrator`
  Then it deduplicates them (e.g., via `unique(...)`) and queries enrichment for each URI.

### Columns

* **actor** → agent URI being enriched
  → **Not retrieved via SPARQL** in this script; injected in output by R when writing results (prepended as a constant column for each query result row)

* **actor_birth** → birth value (typically a date literal)
  → `OPTIONAL { <actor> bio:birth ?actor_birth . }`

* **actor_name** → full name string (if present on the actor URI)
  → `OPTIONAL { <actor> foaf:name ?actor_name . }`

* **actor_first_name** → given name (if modelled)
  → `OPTIONAL { <actor> foaf:givenName ?actor_first_name . }`

* **actor_last_name** → family name (if modelled)
  → `OPTIONAL { <actor> foaf:familyName ?actor_last_name . }`

* **entity_type** → RDF class of the actor URI (e.g., `foaf:Person`, organisation classes, etc.)
  → `OPTIONAL { <actor> rdf:type ?entity_type . }`

* **first_year** → first year associated with the actor (BnF ontology)
  → `OPTIONAL { <actor> bnf-onto:firstYear ?first_year . }`

* **actor_country** → country associated with the person (RDA Group 2 element)
  → `OPTIONAL { <actor> rdagroup2elements:countryAssociatedWithThePerson ?actor_country . }`

* **actor_language** → language associated with the person (RDA Group 2 element)
  → `OPTIONAL { <actor> rdagroup2elements:languageOfThePerson ?actor_language . }`

* **actor_gender** → gender value (if present)
  → `OPTIONAL { <actor> foaf:gender ?actor_gender . }`

* **actor_profession** → biographical information note (free-text)
  → `OPTIONAL { <actor> rdagroup2elements:biographicalInformation ?actor_profession . }`

* **actor_death** → death value (typically a date literal)
  → `OPTIONAL { <actor> bio:death ?actor_death . }`

* **actor_start** → first year associated with the actor, used as an interpreted “start” temporal bound
  → `OPTIONAL { <actor> bnf-onto:firstYear ?actor_start . }`

* **actor_end** → last year associated with the actor, used as an interpreted “end” temporal bound
  → `OPTIONAL { <actor> bnf-onto:lastYear ?actor_end . }`

* **actor_link_exact** → external authority link(s) declared as exact matches
  → `OPTIONAL { ?person foaf:focus <actor> . ?person skos:exactMatch ?actor_link_exact . }`

* **actor_link_close** → external authority link(s) declared as close matches
  → `OPTIONAL { ?person foaf:focus <actor> . ?person skos:closeMatch ?actor_link_close . }`

**Note on row multiplicity:** a single `actor` may appear in multiple rows because `skos:exactMatch` / `skos:closeMatch` can return multiple values, producing multiple distinct solution bindings.

---

### 3) Recovering the actor’s role (and differentiating it from “profession”)

### Role (bibliographic function in the record)

The **role** is the function an agent plays **in relation to a bibliographic entity**, and it is encoded in the edition-level dataset via MARC relator predicates on the **Expression**:

* `marcrel:aut` → author
* `marcrel:edt` → editor
* `marcrel:trl` → translator
* `marcrel:pbl` → publisher (agent role)
* `marcrel:ill` → illustrator

To recover role(s) for a given actor URI:

* Search across the role columns (`author`, `editor`, `translator`, `publisher_2`, `illustrator`) in `bnf_edition_data_raw.csv`.
* The column in which the URI occurs is the role label for that occurrence.
* Because the same URI can occur in multiple columns across different records, a single actor can legitimately have **multiple roles** (role is not an intrinsic property of the agent; it is a contextual relation).

### Profession (agent attribute)

The **profession** (or more precisely, the agent’s biographical/occupational description) is an **attribute of the agent**, not a role in a bibliographic record. In the actor enrichment CSV, the field named `actor_profession` is sourced from:

* `rdagroup2elements:biographicalInformation`

This is a **free-text biographical note**, not a controlled profession taxonomy, and should not be treated as equivalent to the MARC relator roles.

### Practical linkage model

* Use `bnf_edition_data_raw.csv` to model:
  **(edition/expression) —[role predicate]→ (actor URI)**
* Use `actor_data.csv` to enrich the actor URI with:
  **(actor URI) —[attributes]→ (birth/death, country, language, biographical note, external matches, etc.)**

This separation preserves:

* contextual **roles** from the bibliographic graph, and
* intrinsic **agent attributes** from authority-style enrichment.

### Actor URIs: how they are obtained (pattern)

Actor URIs are not generated ad hoc: they are harvested from the **edition/expression query** by reading the agent-role properties on `?expression`:

* `?expression marcrel:aut ?author`
* `?expression marcrel:edt ?editor`
* `?expression marcrel:trl ?translator`
* `?expression marcrel:pbl ?publisher_2`
* `?expression marcrel:ill ?illustrator`

These URIs are then concatenated and de-duplicated in R (e.g., `unique(c(author, editor, translator, publisher_2, illustrator))`) to form the list passed to the actor-enrichment query.

---

### Actor enrichment table (`actor_data.csv`): field structure (concise)

**Key**

* `actor` → the BnF agent URI being enriched (added by R, not returned by SPARQL).

**Identity / label**

* `actor_name` → `foaf:name`
* `actor_first_name` → `foaf:givenName`
* `actor_last_name` → `foaf:familyName`
* `entity_type` → `rdf:type` (e.g., `foaf:Person`, org types)

**Temporal**

* `actor_birth` → `bio:birth`
* `actor_death` → `bio:death`
* `first_year` / `actor_start` → `bnf-onto:firstYear` (generic first year; interpreted as “start” esp. for non-person agents)
* `actor_end` → `bnf-onto:lastYear`

**Contextual attributes (RDA / FOAF)**

* `actor_country` → `rdagroup2elements:countryAssociatedWithThePerson`
* `actor_language` → `rdagroup2elements:languageOfThePerson`
* `actor_gender` → `foaf:gender`
* `actor_profession` → `rdagroup2elements:biographicalInformation` (free-text biographical note; not a controlled profession)

**External links**

* `actor_link_exact` → via a `?person` node with `foaf:focus actor`, then `skos:exactMatch`
* `actor_link_close` → same pattern, `skos:closeMatch`

**Row multiplicity note**

* One `actor` can appear in multiple rows because `skos:exactMatch/closeMatch` may return multiple values (one row per match).




## 1. main.py

<a id="1_mainpy"></a>

**Purpose**
Scans all `.csv` files under `data/results_bnf/` recursively, collects every distinct column name encountered, and writes a timestamped list to `report.txt`.

**Details**

* Detects all CSVs regardless of nested folder structure.
* Extracts headers and aggregates them into a global set.
* Handles UTF-8 decoding errors gracefully.
* Appends results to an existing `report.txt` rather than overwriting it.

**Output**

* `report.txt` → cumulative list of all column names found.

**Usage**

```bash
python main.py
```

---

## 2. agents_main.py

<a id="2_agents_mainpy"></a>

**Purpose**
Unifies agent CSVs per MARC relator role (`aut`, `edt`, `ill`, `pbl`, `trl`) across multiple years.

**Process**

1. Iterates through all `data/results_agents/<year>/<role>/` directories.
2. Reads all CSVs inside each role folder (auto-detecting encoding and delimiter).
3. Adds a `year` column derived from the folder name.
4. Concatenates dataframes and harmonizes headers across files.
5. Saves one unified CSV for each role.

**Output folder**
`data/unified_agents/` with files:

```
unified_aut.csv
unified_edt.csv
unified_ill.csv
unified_pbl.csv
unified_trl.csv
```

**Usage**

```bash
python agents_main.py
```

---

## 3. actors_id_matching.py

<a id="3_actors_id_matchingpy"></a>

**Purpose**
Groups records from unified CSVs by the actor’s **unique ID** (`actor` field) and aggregates values found in all other columns, counting occurrences per distinct value.

**Details**

* Input: CSVs from `data/unified_agents/`.
* Each JSON output stores one object per actor ID, mapping each field to a list of `[value, count]`.
* Used to identify ID-level duplicates and field variation.

**Output folder**
`data/actors_matched_ids/`

**Usage**

```bash
python actors_id_matching.py
```

---

## 4. actors_name_matching.py
<a id="4_actors_name_matchingpy"></a>

**Purpose**
Groups actors by **normalized name** (case- and punctuation-insensitive) rather than by ID.

**Details**

* Same aggregation logic as the ID-based version.
* Each key represents a normalized name.
* Counts occurrences of distinct values across all other fields.

**Output folder**
`data/actors_matched_names/`

**Usage**

```bash
python actors_name_matching.py
```

---

## 5. actors_one_to_may_fields_analysis.py

<a id="5_actors_one_to_may_fields_analysispy"></a>

**Purpose**
Performs quantitative analysis on the JSONs generated by `actors_id_matching.py`.
Computes the **average number of distinct values per field per actor**, for all ID-based files.

**Logic**

* For each file in `data/actors_matched_ids/`, counts how many distinct values each actor has per field.
* Excludes actors missing the field from the average.
* Outputs per-file summaries and a global average.

**Outputs**

* `final_dataset_analysis/reports/actors_field_cardinality_<file>.json`
* `final_dataset_analysis/reports/actors_field_cardinality_ALL.json`

**Usage**

```bash
python actors_one_to_may_fields_analysis.py
```

---

## 6. actors_names_to_many_fields_analysis.py

<a id="6_actors_names_to_many_fields_analysispy"></a>

**Purpose**
Same as above, but analyzes **name-based** actor matches (from `actors_name_matching.py`).

**Logic**

* Reads all JSONs in `data/actors_matched_names/`.
* Computes per-field average list lengths (number of values per name).
* Produces both per-file and global summary JSONs.

**Outputs**

* Per-file: `data/fields_to_values_average_name/actors_field_cardinality_<file>.json`
* Aggregated: `data/fields_to_values_average_name/actors_field_cardinality_ALL.json`

**Usage**

```bash
python actors_names_to_many_fields_analysis.py
```

---

## 7. names_with_multiple_ids.py

<a id="7_names_with_multiple_idspy"></a>

**Purpose**
Builds a unified subset containing only names that are linked to **more than one distinct actor ID**.

**Steps**

1. Merge all files from `data/actors_matched_names/`.
2. Deduplicate and sum count values when duplicates appear.
3. Filter to names with multiple IDs in the `actor` field.
4. Save results to both JSON and CSV.

**Outputs**

* `data/actors_matched_names_multiple_ids.json`
* `data/actors_matched_names_multiple_ids.csv` (columns: `name`, `ids`)

**Usage**

```bash
python names_with_multiple_ids.py
```

---

## 8. reduce_actors_dataset.py

<a id="8_reduce_actors_datasetpy"></a>

**Purpose**
Merges all actor CSVs into a single dataset, removes perfect duplicates, and reports per-actor metadata inconsistencies.

**Workflow**

1. Read every CSV in `data/unified_agents/`.
2. Keep relevant columns:
   `actor`, `actor_name`, `actor_profession`, `actor_link_exact`, `actor_link_close`.
3. Save merged and deduplicated tables.
4. Detect actors with conflicting `profession` or `link` information and store them in JSON.

**Outputs**

* `data/all_actors_merged.csv`
* `data/all_actors_merged_dedup.csv`
* `data/all_actors_profession_conflicts.json`

**Usage**

```bash
python reduce_actors_dataset.py
```

---

## 9. reverse_graph_creator.py

<a id="9_reverse_graph_creatorpy"></a>

**Purpose**
Generates a complete RDF graph (in Turtle format) combining actor and edition metadata from separate CSV datasets.

**Input directories**

* `data/unified_agents/` → Actor information
* `data/unified_dataset/unified_chunks/` → Edition information

**Features**

* Namespace binding for major ontologies: BnF, FOAF, SKOS, MARC relators, BIO, etc.
* Support for multi-value fields (`|` or `;` separated).
* Generates `.nt` graph shards, merges them, and optionally deduplicates triples by line.
* Final `.ttl` output includes RDF prefix header and concatenated triples.

**Outputs**

* Final Turtle graph: `data/reverse_unified_graph.ttl`
* Optional intermediate `.nt` files if `--keep-nt` flag is set.

**Usage Example**

```bash
python reverse_graph_creator.py \
  --actors-root data/unified_agents \
  --editions-root data/unified_dataset/unified_chunks \
  --out data/reverse_unified_graph.ttl \
  --br-chunk 20 \
  --keep-nt \
  --dedupe \
  --dedupe-shards 64
```

---

## 10. unique_values_per_field.py

<a id="10_unique_values_per_fieldpy"></a>

**Purpose**
Extracts unique values for specific actor-related fields across all unified CSVs to support controlled vocabulary generation.

**Fields analyzed**

* `actor_birth`
* `actor_country`
* `actor_death`
* `actor_end`
* `actor_language`
* `actor_start`

**Logic**

* Reads CSVs from `data/unified_agents/` using encoding fallbacks.
* Collects distinct non-empty values per target field.
* Outputs alphabetically sorted lists per field.

**Output**
`data/unique_values_per_field/unique_values.json`

**Usage**

```bash
python unique_values_per_field.py
```

---

## 11. sparql_queries.py

<a id="11_sparql_queriespy"></a>

**Purpose**
Provides a central library of reusable SPARQL queries used in other scripts and notebooks.
Serves as a reference and template repository for querying linked data or RDF outputs.

---

## Summary Table

| Script                                      | Input                                     | Output                                             | Main Goal                                                          |
| ------------------------------------------- | ----------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------ |
| **main.py**                                 | `data/results_bnf/**/*.csv`               | `report.txt`                                       | Collect unique column names across raw BnF CSVs                    |
| **agents_main.py**                          | `data/results_agents/<year>/<role>/*.csv` | `data/unified_agents/*.csv`                        | Merge yearly agent CSVs by MARC relator role                       |
| **actors_id_matching.py**                   | `data/unified_agents/*.csv`               | `data/actors_matched_ids/*.json`                   | Aggregate duplicated actor IDs with field-level value counts       |
| **actors_name_matching.py**                 | `data/unified_agents/*.csv`               | `data/actors_matched_names/*.json`                 | Aggregate duplicated actor names and their metadata                |
| **actors_one_to_may_fields_analysis.py**    | `data/actors_matched_ids/*.json`          | `final_dataset_analysis/reports/*.json`            | Compute field-level variability per actor (ID-based)               |
| **actors_names_to_many_fields_analysis.py** | `data/actors_matched_names/*.json`        | `data/fields_to_values_average_name/*.json`        | Compute field-level variability per actor (name-based)             |
| **names_with_multiple_ids.py**              | `data/actors_matched_names/*.json`        | `data/actors_matched_names_multiple_ids.json/.csv` | Identify names linked to multiple distinct IDs                     |
| **reduce_actors_dataset.py**                | `data/unified_agents/**/*.csv`            | `data/all_actors_merged*.csv/.json`                | Merge and deduplicate actor data, detect profession/link conflicts |
| **reverse_graph_creator.py**                | Unified actors + editions                 | `data/reverse_unified_graph.ttl`                   | Generate complete RDF graph combining actors and editions          |
| **unique_values_per_field.py**              | `data/unified_agents/*.csv`               | `data/unique_values_per_field/unique_values.json`  | Extract and list controlled values per metadata field              |
| **sparql_queries.py**                       | –                                         | –                                                  | Store reusable SPARQL templates for querying and validation        |



-------------------

# Workflow README — End-to-end data flow and dependencies
<a id="WORKFLOW"></a>

Below is a consolidated view of the whole pipeline, ordered by how data flows from raw CSVs to analyses and, finally, RDF. Each block lists **what runs**, **what it reads**, and **what it produces** so you can see the dependencies at a glance. At the end you’ll find a list of **independent scripts** (their inputs/outputs don’t interact with other scripts).

---

## 1) Inventory / reconnaissance (column discovery)

**Script:** `main.py`
**Reads:** `data/results_bnf/**/*.csv` (raw BnF exports)
**Writes:** `report.txt` (complete list of distinct column headers)

**Purpose:** quick reconnaissance of all header names before unification.
**Downstream:** none (stand-alone report for humans).

---

## 2) Build unified datasets

### 2.1 Editions (unique-by-`edition` with provenance)

**Script:** `unique_dataset_maker/dataset_maker.py`
**Reads:** `data/results_bnf/<YEAR>/**.csv`
**Writes:**

* `data/unified_dataset/merged_editions_dataset_with_log.csv`
* `data/unified_dataset/merged_editions_sources_log.json`

**Purpose:** merge all year folders into one table keyed by `edition`, deduplicating values and logging source files per (edition, field, value).

**Next step:** splitter below.

**Script:** `unique_dataset_maker/dataset_maker_split_year.py`
**Reads:** `data/unified_dataset/merged_editions_dataset_with_log.csv`
**Writes:** `data/unified_dataset/unified_chunks/<year>.csv`

**Purpose:** split the unified editions table into **per-year chunks** for downstream analysis.

---

### 2.2 Agents (one file per MARC relator role)

**Script:** `agents_main.py`
**Reads:** `data/results_agents/<year>/<role>/*.csv`
**Writes:** `data/unified_agents/unified_{aut,edt,ill,pbl,trl}.csv`

**Purpose:** unify agent CSVs per role, adding a `year` column and harmonising schemas.

---

## 3) Actor matching and variability analysis

### 3.1 Match by **ID**

**Script:** `actors_id_matching.py`
**Reads:** `data/unified_agents/*.csv`
**Writes:** `data/actors_matched_ids/actors_*.json`

**Purpose:** for actors (by `actor` ID) appearing >1 time, aggregate per-field distinct values with counts.

**Script:** `actors_one_to_may_fields_analysis.py`
**Reads:** `data/actors_matched_ids/*.json`
**Writes:**

* `final_dataset_analysis/reports/actors_field_cardinality_<file>.json`
* `final_dataset_analysis/reports/actors_field_cardinality_ALL.json`

**Purpose:** compute **average #values per field per actor** (ID-based), to detect 1:1 vs 1:many fields.

---

### 3.2 Match by **name**

**Script:** `actors_name_matching.py`
**Reads:** `data/unified_agents/*.csv`
**Writes:** `data/actors_matched_names/actors_*.json`

**Purpose:** same as ID-based, but keys are **normalized names**.

**Script:** `actors_names_to_many_fields_analysis.py`
**Reads:** `data/actors_matched_names/*.json`
**Writes:**

* `data/fields_to_values_average_name/actors_field_cardinality_<file>.json`
* `data/fields_to_values_average_name/actors_field_cardinality_ALL.json`

**Purpose:** average #values per field **by name**, to highlight homonymy/ambiguity patterns.

**Script:** `names_with_multiple_ids.py`
**Reads:** `data/actors_matched_names/*.json`
**Writes:**

* `data/actors_matched_names_multiple_ids.json`
* `data/actors_matched_names_multiple_ids.csv` (`name, ids`)

**Purpose:** list names linked to **>1 ID** (potential homonyms or unreconciled duplicates).

---

## 4) Names analysis toolkit (extraction & AI-assisted validation)

**Script:** `names_analysis/names_dict_maker.py`
**Reads:** `data/results_bnf/**/*.csv`
**Writes:** `names_analysis/names_results/names_dict.json`

**Script:** `names_analysis/detect_real_names.py`
**Reads:** `names_analysis/names_results/names_dict.json`
**Writes:** `names_analysis/names_results/names_classification_report.json`

**Script:** `names_analysis/enhanced_detect_names.py`
**Reads:** `names_analysis/names_results/names_dict.json`
**Writes:** `names_analysis/names_results/names_classification_report_flair.json`

**Script:** `names_analysis/enhanced_detect_names_cleaner.py`
**Reads:** `names_analysis/names_results/names_dict.json`
**Writes:** `names_analysis/names_results/names_noise_removed_flair.json`

**Script:** `names_analysis/csv_analysis_maker.py`
**Reads:** `names_analysis/names_results/names_classification_report_flair.json` *(or rule-based)*
**Writes:** `names_analysis/names_results/names_review_table.csv`

**Purpose of the block:** build a canon of candidate names and classify them (rule-based or Flair NER), extract “noise”, then produce a **human review table**.

---

## 5) Editions analysis (duplicates, relationships, record types)

All scripts below read **per-year unified chunks**: `data/unified_dataset/unified_chunks/*.csv`

**Script:** `final_dataset_analysis/counting_types.py`
**Writes:**

* `final_dataset_analysis/reports/record_type_counts.json`
* `final_dataset_analysis/reports/record_type_entity_cardinality.json`
  **Purpose:** global counts of `record_type` and how many types per entity.

**Script:** `final_dataset_analysis/fetch_bnf_ark_titles.py`
**Reads:** `final_dataset_analysis/reports/record_type_counts.json`
**Writes:** `final_dataset_analysis/reports/bnf_ark_titles.json`
**Purpose:** fetch titles for `data.bnf.fr/ark:/12148/…` URIs found among record types.

**Script:** `final_dataset_analysis/edition_record_type_analysis.py`
**Reads:**

* `final_dataset_analysis/reports/bnf_ark_titles.json`
* `data/unified_dataset/unified_chunks/*.csv`
  **Writes:** `final_dataset_analysis/reports/edition_to_allowed_record_types.json`
  **Purpose:** edition → allowed record types (labelled whitelist).

**Script:** `final_dataset_analysis/editions_analysis.py`
**Writes:** `final_dataset_analysis/reports/duplicates_report.json`
**Purpose:** duplicates and **co-occurrence** analysis among editions/expressions/works.

**Script:** `final_dataset_analysis/editions_additional_analysis.py`
**Writes:**

* `final_dataset_analysis/reports/work_link_summary.json`
* `final_dataset_analysis/reports/edition_expression_checks.json`
* `final_dataset_analysis/reports/focus_uris.json` *(optional)*
  **Purpose:** structure and connectivity: edition–expression–work links, cardinalities, focus diagnostics.

**Script:** `final_dataset_analysis/find_entities_without_record_type.py`
**Writes:**

* `final_dataset_analysis/reports/editions_without_record_type.json`
* `final_dataset_analysis/reports/editions_without_record_type.csv`
  **Purpose:** find editions with missing `record_type`.

**Script:** `final_dataset_analysis/no_type_random_sample.py`
**Writes:** `final_dataset_analysis/reports/no_type_random_sample.csv`
**Purpose:** sample 100 “no type” editions → fetch BnF Catalogue **H1** title (sanity check).

**Script:** `final_dataset_analysis/stupid_counter.py`
**Reads:** `final_dataset_analysis/reports/edition_to_allowed_record_types.json`
**Writes:** console count
**Purpose:** quick edition count diagnostic.

---

## 6) Utilities for actor curation

**Script:** `reduce_actors_dataset.py`
**Reads:** `data/unified_agents/**/*.csv`
**Writes:**

* `data/all_actors_merged.csv`
* `data/all_actors_merged_dedup.csv`
* `data/all_actors_profession_conflicts.json`
  **Purpose:** merge all agent rows, deduplicate perfect duplicates, flag per-actor inconsistencies (profession/links).

**Script:** `unique_values_per_field.py`
**Reads:** `data/unified_agents/*.csv`
**Writes:** `data/unique_values_per_field/unique_values.json`
**Purpose:** enumerate distinct values per selected actor fields (useful to design controlled vocabularies and cleaning rules).

---

## 7) RDF generation

**Script:** `reverse_graph_creator.py`
**Reads:**

* `data/unified_agents/*.csv`
* `data/unified_dataset/unified_chunks/*.csv`
  **Writes:**
* final graph: `data/reverse_unified_graph.ttl`
* optional intermediates: `.nt` shards and merged `.nt` (with optional dedupe)
  **Purpose:** build a unified RDF graph (actors + editions), with namespaces (BnF, MARC relators, FOAF, SKOS, BIO, etc.), multi-value handling, chunked serialisation, and optional triple deduplication.

---

## 8) SPARQL templates

**Script:** `sparql_queries.py`
**Reads/Writes:** none (library of query templates)
**Purpose:** shared SPARQL snippets for validation and exploration.

---

# Visual flow (text schematic)

```
RAW BnF exports
 ├─ data/results_bnf/**/*                 ──► main.py (headers → report.txt)
 │
 ├─ unique_dataset_maker/dataset_maker.py ──► merged_editions_dataset_with_log.csv (+ sources_log.json)
 │                                          └─► dataset_maker_split_year.py → unified_chunks/<year>.csv
 │
 └─ data/results_agents/<year>/<role>/*.csv ─► agents_main.py → unified_agents/unified_{aut,edt,ill,pbl,trl}.csv

ACTOR ANALYSIS (from unified_agents)
 ├─ actors_id_matching.py → actors_matched_ids/*.json
 │    └─ actors_one_to_may_fields_analysis.py → reports/actors_field_cardinality_*.json, *_ALL.json
 ├─ actors_name_matching.py → actors_matched_names/*.json
 │    └─ names_with_multiple_ids.py → actors_matched_names_multiple_ids.{json,csv}
 │    └─ actors_names_to_many_fields_analysis.py → fields_to_values_average_name/*.json
 ├─ reduce_actors_dataset.py → all_actors_merged*.csv, all_actors_profession_conflicts.json
 └─ unique_values_per_field.py → unique_values.json

NAMES TOOLKIT (from results_bnf CSVs)
 └─ names_dict_maker.py → names_dict.json
      ├─ detect_real_names.py → names_classification_report.json
      ├─ enhanced_detect_names.py → names_classification_report_flair.json
      ├─ enhanced_detect_names_cleaner.py → names_noise_removed_flair.json
      └─ csv_analysis_maker.py → names_review_table.csv

EDITIONS ANALYSIS (from unified_chunks)
 ├─ counting_types.py → record_type_counts.json (+ entity_cardinality.json)
 │    └─ fetch_bnf_ark_titles.py → bnf_ark_titles.json
 │         └─ edition_record_type_analysis.py → edition_to_allowed_record_types.json
 ├─ editions_analysis.py → duplicates_report.json
 ├─ editions_additional_analysis.py → work_link_summary.json, edition_expression_checks.json, focus_uris.json
 ├─ find_entities_without_record_type.py → editions_without_record_type.{json,csv}
 │    └─ no_type_random_sample.py → no_type_random_sample.csv
 └─ stupid_counter.py (reads edition_to_allowed_record_types.json)

RDF GRAPH
 └─ reverse_graph_creator.py (uses unified_agents + unified_chunks) → reverse_unified_graph.ttl
```

---

# Independent scripts

> **Definition used:** “independent” means their **inputs and outputs do not feed any other script** in this repository (i.e., no other script consumes their outputs, and they don’t require another script’s outputs as inputs).

* **main.py**
  *Reads raw `data/results_bnf/**/*.csv` and writes `report.txt`.*
  Its output is not consumed by any other script.

* **sparql_queries.py**
  *Template/library only; no IO and not consumed as an input by other scripts.*

> All other scripts **participate in the workflow** via dependencies on either:
>
> * `unified_agents/*.csv` (produced by `agents_main.py`), or
> * `unified_dataset/unified_chunks/*.csv` (produced by the editions unifier), or
> * intermediate JSON/CSV produced by sibling steps (e.g., `actors_*_matching.py` feeding field-cardinality analyses, or `counting_types.py` feeding `fetch_bnf_ark_titles.py`, etc.).


### important next steps
- linking 
- documenting harmonisation 
- chiedere a sebastian 
- publish the dataset 
- evaluation !!!
- preparing what is necessary for dataset production 
- linking script on jonas side 
