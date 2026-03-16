# BnF Actor Dataset Optimisation – Usage and Technical Notes

## 1. Execution Order (Pipeline)

1. **Step 1 – Generate actor–roles–editions links**

   ```bash
   python subset_optimisation/roles_enricher.py

Output:
`subset_optimisation/id_roles/actor_roles_links.csv`

2. **Step 2 – Optimise the actor dataset and enrich with roles**

   ```bash
   python subset_optimisation/gen_author_links_optm.py
   ```

   Outputs:

   * `subset_optimisation/output/bnf_actors_optimised.csv`
   * `subset_optimisation/output/bnf_actors_optimised_minimal.csv`
   * `subset_optimisation/report/summary_report.txt`
   * `subset_optimisation/report/merged_entities.json`

In total, the full process produces **five main files**.

---

## 2. Module Overview

The module `subset_optimisation` contains two main scripts that operate in sequence:

1. `roles_enricher.py`

   * Builds a mapping between BnF actor identifiers, the editions they contributed to, and their roles in those editions.
   * Uses the raw BnF actor and edition datasets.

2. `gen_author_links_optm.py`

   * Aggregates all actor records by BnF ID, treating all actor fields as potentially multi-valued.
   * Detects and excludes exact duplicates.
   * Tracks merges and field variations.
   * Enriches each actor with aggregated roles and edition links from `actor_roles_links.csv`.
   * Produces full and minimal optimised actor datasets, plus a report and a merge-tracking JSON.

---

## 3. Script 1 – `roles_enricher.py`

### 3.1 Purpose

`roles_enricher.py` scans the edition dataset and, for each actor that appears as a responsible agent (author, editor, translator, etc.), records:

* in which editions they appear, and
* under which roles they appear.

The result is a compact CSV used as an enrichment source by `gen_author_links_optm.py`.

### 3.2 Inputs

**Default paths:**

* Actors ZIP (agent records):

  ```text
  data/bnf_agents_data_querying/actor_queries_results.zip
  ```

* Editions ZIP (edition records):

  ```text
  data/bnf_edition_data/bnf_edition_data_raw.zip
  ```

**Relevant fields in the editions dataset:**

* `bnf_id` or `edition` – edition identifier (used as `contributed_to`)
* Role fields:

  ```text
  author
  editor
  translator
  publisher_2
  illustrator
  ```

Each role field is expected to contain a single BnF actor URI (as in the sample).

### 3.3 Processing

1. **Actor ID collection**
   From `actor_queries_results.zip`, the script collects all distinct values of the `actor` field.
   Only these IDs are considered valid actors for the subsequent step.

2. **Edition scan**
   For every row in `bnf_edition_data_raw.zip`:

   * Determine the edition identifier:

     * Prefer `bnf_id`; if missing, fall back to `edition`.
   * For each role field in `["author", "editor", "translator", "publisher_2", "illustrator"]`:

     * If the field exists and is non-empty:

       * If the value matches a known actor ID from the previous step:

         * Add this edition to the actor’s `contributed_to` set.
         * Add the role name to the actor’s `roles` set.

3. **Normalisation**

   * Values like `"NA"`, `"N/A"`, `"NULL"` (any case), or empty are treated as missing.

4. **Aggregation**

   * For each actor that appears at least once in the editions:

     * `contributed_to`: sorted list of edition IDs, joined by `;`
     * `roles`: sorted list of roles, joined by `;`

### 3.4 Output

**File 1: `actor_roles_links.csv`**

* Location: `subset_optimisation/id_roles/actor_roles_links.csv`
* Columns:

  ```text
  actor           - BnF actor ID (URI)
  contributed_to  - list of edition IDs (bnf_id or edition), separated by ";"
  roles           - list of role labels ("author", "editor", ...) separated by ";"
  ```

This file is the enrichment input for `gen_author_links_optm.py`.

### 3.5 Usage

**Default:**

```bash
python subset_optimisation/roles_enricher.py
```

**Custom paths:**

```bash
python subset_optimisation/roles_enricher.py \
  --actors-zip data/bnf_agents_data_querying/actor_queries_results.zip \
  --editions-zip data/bnf_edition_data/bnf_edition_data_raw.zip \
  --output-dir subset_optimisation/id_roles \
  --output-filename actor_roles_links.csv
```

---

## 4. Script 2 – `gen_author_links_optm.py`

### 4.1 Purpose

`gen_author_links_optm.py` performs three main tasks:

1. Aggregates all actor records by BnF ID (from the actors ZIP), treating every field as potentially multi-valued.
2. Tracks duplicate rows and field variations across multiple records per actor.
3. Enriches each actor with role and edition information from `actor_roles_links.csv`, then exports:

   * a full optimised actors dataset,
   * a minimal subset for external authority linking,
   * a text report with statistics,
   * a JSON file tracking merges and field variations.

### 4.2 Inputs

**Primary data:**

* Actors ZIP (default):

  ```text
  data/bnf_agents_data_querying/actor_queries_results.zip
  ```

  Each CSV inside the ZIP must contain at least:

  ```text
  actor              - BnF ID (aggregation key)
  actor_name
  actor_first_name
  actor_last_name
  actor_birth
  actor_death
  actor_start
  actor_end
  first_year
  entity_type
  actor_gender
  actor_profession
  actor_country
  actor_language
  actor_link_exact
  actor_link_close
  ```

**Roles mapping (enrichment source):**

* Default:

  ```text
  subset_optimisation/id_roles/actor_roles_links.csv
  ```

* Required columns:

  ```text
  actor           - BnF ID (must match BnF_ID in final dataset)
  contributed_to  - editions where the actor appears
  roles           - roles in those editions
  ```

The path can be overridden via `--roles-mapping`.

### 4.3 Core behaviour

#### 4.3.1 Aggregation by actor

1. For each row in every CSV inside `actor_queries_results.zip`:

   * Normalize the `actor` field; skip if empty.
   * Use the normalized `actor` value as the key (`bnf_id`).

2. Duplicate detection per actor:

   * Build a `row_signature` by concatenating the normalized values of all fields in `ALL_DATA_FIELDS`.
   * Maintain a list of signatures per `bnf_id`.
   * If a row’s signature already exists for that `bnf_id`, it is counted as an exact duplicate and skipped.

3. Field aggregation:

   * For each non-empty value of every field in `ALL_DATA_FIELDS`:

     * Add it to a `set` associated with that field for the actor.
   * All values are deduplicated at the set level.

4. Merge tracking:

   * For each actor, the script tracks:

     * `merge_count`: number of rows that actually introduced new values for at least one field.
     * `fields_with_variations`: for each field, the list of additional values that produced variation (i.e. when a new value is added to a field that already had at least one different value).

5. Output record creation:

   * After all rows are processed, the script flattens the `set`s:

     * Each field is turned into a `"; "`-joined string of sorted values.
     * A row is created with:

       ```text
       BnF_ID, actor_name, actor_first_name, ..., actor_link_close
       ```

#### 4.3.2 Enrichment with roles and editions

1. `load_roles_mapping` reads `actor_roles_links.csv`:

   * Performs a raw scan to identify lines longer than 131072 characters and prints them for inspection.
   * Parses the file via `csv.DictReader`.
   * Builds a dictionary:

     ```python
     mapping[actor_id] = {
         "contributed_to": "...",
         "roles": "..."
     }
     ```

2. For each actor record in the aggregated dataset:

   * Look up `BnF_ID` in `mapping`.
   * If present:

     * Add `contributed_to` and `roles` fields from the mapping.
   * Otherwise:

     * Set `contributed_to` and `roles` to empty strings.

### 4.4 Outputs

The script produces **four files**.

#### 4.4.1 Full optimised actor dataset

**File 2: `bnf_actors_optimised.csv`**

* Location: `subset_optimisation/output/bnf_actors_optimised.csv`

* Columns:

  ```text
  BnF_ID
  actor_name
  actor_first_name
  actor_last_name
  actor_birth
  actor_death
  actor_start
  actor_end
  first_year
  entity_type
  actor_gender
  actor_profession
  actor_country
  actor_language
  actor_link_exact
  actor_link_close
  contributed_to
  roles
  ```

* All fields except `BnF_ID` are the result of set-based aggregation and may contain multiple values separated by `"; "`.

* `contributed_to` and `roles` are imported from `actor_roles_links.csv`.

#### 4.4.2 Minimal actor dataset

**File 3: `bnf_actors_optimised_minimal.csv`**

* Location: `subset_optimisation/output/bnf_actors_optimised_minimal.csv`

* Columns:

  ```text
  BnF_ID
  actor_link_exact
  actor_link_close
  ```

* One row per actor.

* Designed as a compact subset focused on external authority linking (e.g. VIAF or similar), without additional descriptive metadata.

#### 4.4.3 Statistical report

**File 4: `summary_report.txt`**

* Location: `subset_optimisation/report/summary_report.txt`
* Structure:

  1. **Basic statistics**

     * Total source rows
     * Exact duplicate rows
     * Net rows (excluding duplicates)
     * Total unique actors
     * Actors with merged records
     * Merge rate
     * Average records per actor

  2. **Field statistics (all fields)**

     For each field in `ALL_DATA_FIELDS`:

     * Number of actors with at least one value
     * Fill rate (%) relative to total actors
     * Average number of values per actor for that field

  3. **Overall average**

     * Average number of items per entity across all fields.

  4. **Average items per entity by field**

     * Single line per field, reporting the average number of values per actor.

  5. **Merge details**

     * For each field:

       * Number of entities where that field had variations (multiple different values).

#### 4.4.4 Merge tracking JSON

**File 5: `merged_entities.json`**

* Location: `subset_optimisation/report/merged_entities.json`

* Includes only actors for which at least one field has multiple values.

* Structure per actor:

  ```json
  {
    "http://data.bnf.fr/ark:/12148/cb12345678x#about": {
      "merge_count": 2,
      "fields_with_variations": {
        "actor_name": [
          "Jean Dupont",
          "J. Dupont"
        ],
        "actor_link_exact": [
          "http://viaf.org/viaf/123",
          "http://viaf.org/viaf/456"
        ]
      }
    }
  }
  ```

* `merge_count` counts the number of rows that actually introduced new values (not exact duplicates).

* `fields_with_variations` lists only fields that exhibit genuine variation.

### 4.5 Usage

**Default:**

```bash
python subset_optimisation/gen_author_links_optm.py
```

This assumes:

* actors ZIP at `data/bnf_agents_data_querying/actor_queries_results.zip`
* roles mapping at `subset_optimisation/id_roles/actor_roles_links.csv`
* outputs written to:

  * `subset_optimisation/output`
  * `subset_optimisation/report`

**Custom arguments:**

```bash
python subset_optimisation/gen_author_links_optm.py \
  --input-zip data/bnf_agents_data_querying/actor_queries_results.zip \
  --output-dir subset_optimisation/output \
  --report-dir subset_optimisation/report \
  --output-filename bnf_actors_optimised.csv \
  --roles-mapping subset_optimisation/id_roles/actor_roles_links.csv
```

---

## 5. Summary of the Five Main Files

1. `subset_optimisation/id_roles/actor_roles_links.csv`

   * Produced by `roles_enricher.py`
   * Maps each actor to the editions they contribute to and their roles.

2. `subset_optimisation/output/bnf_actors_optimised.csv`

   * Produced by `gen_author_links_optm.py`
   * Full, multi-valued, enriched actor dataset.

3. `subset_optimisation/output/bnf_actors_optimised_minimal.csv`

   * Produced by `gen_author_links_optm.py`
   * Minimal authority-linking subset with BnF_ID and external links.

4. `subset_optimisation/report/summary_report.txt`

   * Produced by `gen_author_links_optm.py`
   * Statistical overview of the optimisation and aggregation process.

5. `subset_optimisation/report/merged_entities.json`

   * Produced by `gen_author_links_optm.py`
   * Detailed record of merged entities and their field-level variations.
   