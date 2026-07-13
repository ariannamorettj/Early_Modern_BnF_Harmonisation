# 05 – Subset Optimisation — Usage & Technical Notes

## 1. Module structure

```
05_subset_optimisation/
│
├── roles_enricher.py        # Step 1 – build actor→role→editions map
├── gen_subset_optm.py       # Step 2 – produce optimised actor dataset
│
├── data/                    # Previously processed data (do not overwrite)
│   ├── bnf_actors_optimised.csv
│   ├── bnf_actors_optimised_minimal.csv
│   ├── actor_roles_links.csv
│   ├── summary_report.txt
│   └── merged_entities.json
│
├── id_roles/                # Output of Step 1 (current run)
│   └── actor_roles_links.csv
│
├── output/                  # Output of Step 2 (current run)
│   ├── bnf_actors_optimised.csv
│   └── bnf_actors_optimised_minimal.csv
│
└── report/                  # Reports of current run
    ├── summary_report.txt
    ├── merged_entities.json
    ├── multi_role_actors.json
    └── dedup_report.json    # only if --dedup-field was used
```

> `data/` contains outputs from previous runs and is never overwritten by the scripts.
> New outputs always go to `id_roles/`, `output/`, and `report/`.

---

## 2. Execution order

### Step 1 – `roles_enricher.py`

Scans the raw edition dataset and builds, for each actor, the mapping
of which editions they contributed to and under which role(s).

```bash
# Full dataset
python 05_subset_optimisation/roles_enricher.py

# Medieval period only (editions published up to 1450)
python 05_subset_optimisation/roles_enricher.py --year-to 1450

# Custom year range
python 05_subset_optimisation/roles_enricher.py --year-from 1000 --year-to 1450
```

**Outputs:**
- `id_roles/actor_roles_links.csv` — columns: `actor`, `role_edition_map`, `roles`
  - `role_edition_map` encodes `"author:id1,id2;editor:id3"` (role:editions structure)
  - `roles` encodes `"author;editor"` (flat list for quick filtering)
- `report/multi_role_actors.json` — actors that held more than one role:
  ```json
  {
    "<actor_uri>": {
      "author": ["ed_id1", "ed_id2"],
      "editor": ["ed_id3"]
    }
  }
  ```

---

### Step 2 – `gen_subset_optm.py`

Aggregates the actor dataset (one row per actor), enriches with roles,
and optionally filters by year or deduplicates on a chosen field.

```bash
# Default – full dataset, no filters
python 05_subset_optimisation/gen_subset_optm.py

# Medieval actors only
# (roles_mapping must have been built with --year-to 1450 in Step 1)
python 05_subset_optimisation/gen_subset_optm.py --year-to 1450

# With deduplication on actor_name
python 05_subset_optimisation/gen_subset_optm.py --dedup-field actor_name

# Full custom run
python 05_subset_optimisation/gen_subset_optm.py \
    --input-zip  data/bnf_agents_data_querying/actor_queries_results.zip \
    --roles-mapping 05_subset_optimisation/id_roles/actor_roles_links.csv \
    --output-dir 05_subset_optimisation/output \
    --report-dir 05_subset_optimisation/report \
    --year-from 1000 --year-to 1450 \
    --dedup-field BnF_ID
```

**Outputs:**
- `output/bnf_actors_optimised.csv` — full dataset, columns:
  ```
  BnF_ID, actor_name, actor_first_name, actor_last_name,
  actor_birth, actor_death, actor_start, actor_end,
  first_year, entity_type, actor_gender,
  actor_country, actor_language,
  actor_link_exact, actor_link_close,
  role_edition_map, roles
  ```
- `output/bnf_actors_optimised_minimal.csv` — columns:
  ```
  BnF_ID, actor_name, actor_link_exact, actor_link_close
  ```
- `report/summary_report.txt` — statistics (fill rates, merge counts, etc.)
- `report/merged_entities.json` — actors with field-level variations across merged rows
- `report/dedup_report.json` — (only if `--dedup-field` used) groups where fields
  carried more than one distinct value after collapsing:
  ```json
  {
    "<dedup_key_value>": {
      "actor_birth": ["1620", "1621"],
      "actor_link_exact": ["<uri_1>", "<uri_2>"]
    }
  }
  ```

---

## 3. Parameters reference

### `roles_enricher.py`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--actors-zip` | `data/bnf_agents_data_querying/actor_queries_results.zip` | ZIP with actor CSVs |
| `--editions-zip` | `data/bnf_edition_data/bnf_edition_data_raw.zip` | ZIP with edition CSVs |
| `--output-dir` | `id_roles` | Output directory for roles CSV |
| `--report-dir` | `report` | Output directory for JSON report |
| `--output-filename` | `actor_roles_links.csv` | Output CSV filename |
| `--year-from` | *(none)* | Include editions from this year (inclusive) |
| `--year-to` | *(none)* | Include editions up to this year (inclusive) |

### `gen_subset_optm.py`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--input-zip` | `data/bnf_agents_data_querying/actor_queries_results.zip` | ZIP with actor CSVs |
| `--roles-mapping` | `id_roles/actor_roles_links.csv` | CSV from Step 1 |
| `--output-dir` | `output` | Output directory for CSVs |
| `--report-dir` | `report` | Output directory for reports |
| `--output-filename` | `bnf_actors_optimised.csv` | Full output CSV filename |
| `--year-from` | *(none)* | Retain only actors in editions from this year |
| `--year-to` | *(none)* | Retain only actors in editions up to this year |
| `--dedup-field` | *(none)* | Field to use as deduplication key |

---

## 4. Notes on `role_edition_map` and `profession`

`actor_profession` is **not** a direct field in the output. Profession is
derived from the roles each actor held in relation to the editions dataset,
following the principle that the role performed is the most reliable
indicator of the actor's professional function in the Early Modern book trade.

The `role_edition_map` column encodes this information as:

```
author:id1,id2,id3;editor:id4,id5;translator:id6
```

The `roles` column provides a flat summary:

```
author;editor;translator
```

The full breakdown of which editions correspond to which role per actor
is available in `report/multi_role_actors.json`.

---

## 5. Deduplication logic

When `--dedup-field FIELD` is provided:

1. Rows are grouped by the value of `FIELD`.
2. Within each group:
   - If all rows are identical on every other field → they collapse into one row.
   - If rows differ on some fields → the distinct values for each differing field
     are collected, sorted, and joined with `", "` in the merged row.
3. The `dedup_report.json` records every group where at least one field
   carried more than one distinct value (the dedup key is the dictionary key,
   each entry maps field names to the list of distinct values found).

---

## 6. Summary of output files

| File | Produced by | Description |
|------|-------------|-------------|
| `id_roles/actor_roles_links.csv` | `roles_enricher.py` | Actor→role→editions map |
| `report/multi_role_actors.json` | `roles_enricher.py` | Actors with >1 role |
| `output/bnf_actors_optimised.csv` | `gen_subset_optm.py` | Full optimised dataset |
| `output/bnf_actors_optimised_minimal.csv` | `gen_subset_optm.py` | Minimal linking subset |
| `report/summary_report.txt` | `gen_subset_optm.py` | Statistics |
| `report/merged_entities.json` | `gen_subset_optm.py` | Merge-tracking |
| `report/dedup_report.json` | `gen_subset_optm.py` | Dedup detail (optional) |
