## Early Modern BnF Dataset Harmonisation Workflow

The software is organised through a **nested numerical folder system** designed to preserve execution order, make the workflow easier to navigate, and support partial or repeated re-execution of individual stages without restructuring the project.

At the highest level, the numbering reflects the main functional areas of the workflow.  
Within each area, subfolders follow the same logic, so that each component can be located, executed, tested, or resumed in a predictable way.

---

## Running the Sampo portal locally

The workflow ends in a [Sampo](https://github.com/SemanticComputing/sampo-ui)
faceted-search portal over the knowledge graph (`08_sampo_portal/`): editions
and actors with facets, a map of places of publication, charts per decade,
and a page for every edition and actor.

> [!IMPORTANT]
> **The portal is not online.** A Sampo portal is not a static website: the
> React client queries a Node.js server, which queries a SPARQL endpoint
> holding the whole graph. GitHub Pages only serves static files, and the
> full graph is too large to host cheaply:
>
> | | Size |
> |---|---|
> | Full graph, N-Triples (`knowledge-graph_merged.nt`) | 39.3 million lines, 7.0 GB |
> | Oxigraph store built from it, with the portal layer | 9.4 GB on disk (about 13 GB while loading) |
> | Sample graph (included in this repository) | 14,861 triples, 3.0 MB |
>
> Serving the full graph needs a server with that much disk and enough memory
> to query it, which no free hosting tier provides. The portal therefore runs
> on your machine: on the sample graph in a few minutes, or on the full graph
> once you have rebuilt it.

### Quick start: the sample graph (about 10 minutes)

Requirements: Python 3.11+, Git, and [Node.js 22](https://nodejs.org/)
(an installer, or the portable zip on your `PATH`, is enough).

```bash
git clone https://github.com/ariannamorettj/Early_Modern_BnF_Harmonisation.git
cd Early_Modern_BnF_Harmonisation

python 08_sampo_portal/portal.py setup                  # once: Oxigraph + Sampo-UI + npm install
python 08_sampo_portal/portal.py load --profile sample  # builds the triplestore (seconds)
python 08_sampo_portal/portal.py dev                    # then open http://localhost:8080
```

`portal.py` needs only the Python standard library. `setup` downloads the
Oxigraph binary pinned in `08_sampo_portal/portal.lock.json`
and checks its SHA-256, clones Sampo-UI at the pinned commit, and runs
`npm install`. `dev` starts three processes (SPARQL endpoint on port 7878, API
on 3001, portal on 8080) and stops them all on Ctrl+C.

### The full graph

The full graph is not in the repository (7.0 GB). Rebuilding it needs module
04's `data/bnf_edition_data/bnf_editions_ready.csv` (482 MB, git-ignored),
which modules 01–04 produce from the data.bnf.fr acquisition. With that file
in place, and the pipeline's dependencies installed:

```bash
pip install pandas rdflib morph-kgc pyyaml "pyoxigraph>=0.3,<0.4" pycountry
cd 07_graph_materialisation
python scripts/bnf_graph_pipeline.py all --profile full --force   # ~15 min, 7.0 GB output
cd ..
python 08_sampo_portal/portal.py load --profile full              # ~40 min, 9.4 GB store
python 08_sampo_portal/portal.py dev
```

Plan for about 25 GB of free disk space (graph plus store, and the
temporary copy `load` builds before swapping it in). On the full graph the
portal answers in 1-15 s for tables, map and charts and in 20-30 s for the
facets over the 814,031 editions, on a 22-core laptop.

### When the data changes

The portal holds no copy of the data of its own: after any re-run of modules
04–07, rebuild the graph and run `portal.py load` again. Stop `portal.py dev`
first, because the endpoint keeps the store open. `load` swaps in the new
store only once it is complete.

Details (what each command does, the portal layer derived from the graph,
configuration, known limits): [`08_sampo_portal/README.md`](08_sampo_portal/README.md).

### `00_test`

This directory contains the automated test suite for the main workflow components.  
Its purpose is to verify the deterministic behaviour of the scripts, the correctness of key formulas and helper functions, and the expected structure of outputs and resume logic.

### `00_monitor`

This directory contains the system monitoring utilities used to record machine-level and process-level metrics during long-running executions.  
It includes aligned Python and R implementations and supports both standalone execution and embedded use within other workflow scripts.

### `01_data_retrieval`

This directory contains the data acquisition stage of the workflow.  
It includes the scripts used to retrieve bibliographic and actor-related data, organise intermediate outputs, and generate the main raw datasets used by later workflow steps.

## Documentation Structure

Each main directory includes its own internal `README.md` file with more detailed technical documentation about:

- purpose
- internal structure
- execution behaviour
- inputs and outputs
- tests and monitoring, where applicable

The present README only provides the general project-level overview.

---

## Last Updates

### 1. Sampling Stage (`02_sampling`)
- **Structure & Utilities**: Restructured the module to use a centralized utility file ([sampling_utils.py](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/02_sampling/sampling_utils.py)) and distinct, focused scripts (`01_zip_tree.py` to `04_column_value_sample.py`) for inspecting raw zipped data.
- **Harmonisation Decisions**: Completed initial sampling to categorize fields into those requiring active cleaning/normalization and those needing only quantitative validation.
- **Where to look**: 
  - Consult the **Transition Table** in [02_sampling/README.md](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/02_sampling/README.md#transition-to-analysis-data-harmonisation-findings) for the detailed list of fields requiring harmonisation vs. verification.

### 2. Analysis Stage (`03_analysis`)
- **Module Documentation**: Created [03_analysis/README.md](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/03_analysis/README.md) describing the script inventory (filtering, unique values, row subsetting, actor field cardinality) and sub-packages (`actors/`, `bib_resources/`, and the AI-assisted `names/` toolkit).
- **Non-Harmonised Fields Report**: Created the standalone [03_analysis/no_harmonisation_fields_report.md](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/03_analysis/no_harmonisation_fields_report.md) report detailing fields that require only profiling and integrity checks (no string or structural changes).
- **New Dataset Profiler**: Implemented [03_analysis/05_dataset_profiler.py](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/03_analysis/05_dataset_profiler.py) to calculate comprehensive metrics for all fields in a ZIP dataset:
  - Total non-empty counts, unique value counts, and fill rate percentage.
  - Frequency-sorted top 10 most common values.
  - *Null Handling*: Excludes empty cells (`""`), `None`, and common placeholders (`NA`, `N/A`, `null`, etc.) from count metrics.
- **Execution & Output**:
  - Run commands:
    ```bash
    # Actor Dataset:
    python 03_analysis/05_dataset_profiler.py 01_data_retrieval/02_actors/data/old_zip/actor_data.zip --output-dir 03_analysis/data

    # Bibliographic Dataset:
    python 03_analysis/05_dataset_profiler.py 01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip --output-dir 03_analysis/data
    ```
  - **Output Reports**: Generated JSONs containing the metrics are stored in the [03_analysis/data/](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/03_analysis/data/) directory with meaningful names:
    - `05_dataset_profiler_dataset-ACTOR_<timestamp>.json`
    - `05_dataset_profiler_dataset-BIB_RES_<timestamp>.json`

---

## Next Steps & Harmonisation Roadmap

The next phase of the workflow (`04_harmonisation`) will focus on developing dedicated cleaning and normalization modules. Based on the findings from the sampling phase (`02_sampling`), we will implement one script/module for each field requiring harmonisation.

### 1. New Harmonisation Scripts to Add (`04_harmonisation/`)

| Target Field(s) | Planned Script | Core Responsibilities |
| :--- | :--- | :--- |
| **`actor_birth`**, **`actor_death`**, **`actor_start`**, **`actor_end`**, **`year_first`** | `actor_dates_harmoniser.py` | - Trim non-date characters.<br>- Validate standard formats (`YYYY-MM-DD` and `YYYY`).<br>- Normalize leading zeros.<br>- Extract uncertainty flags (e.g. from `...` or `?`). |
| **`actor_country`** | `actor_country_harmoniser.py` | - Resolve URIs and standard vocabularies.<br>- Fetch/append country names (e.g. `[France]`). |
| **`actor_language`**, **`language`** (bib) | `language_harmoniser.py` | - Resolve ISO-639-2 URIs.<br>- Append normalized language strings in square brackets. |
| **`actor_first_name`**, **`actor_last_name`**, **`actor_name`** | `actor_name_harmoniser.py` | - Trim whitespaces and clean punctuation.<br>- Strip titles/epithets (e.g. "dit").<br>- Generate certainty scores for initials. |
| **`actor_profession`** | `actor_profession_harmoniser.py` | - Clean free-text professions.<br>- Tokenize and map to a controlled vocabulary. |
| **`actor_link_close`**, **`actor_link_exact`** | `actor_links_harmoniser.py` | - Standardize URL protocols (`http`/`https`).<br>- Remove absence placeholders and check for uniqueness. |
| **`description`** (bib) | `bib_description_harmoniser.py` | - Clean free text.<br>- Parse pagination and volume structures (e.g., `VIII-316 p.`). |
| **`place`** (bib) | `bib_place_harmoniser.py` | - Normalize location strings.<br>- Flag uncertainty markers like `(S. l. n. d.)` or `(inconnu)`. |
| **`publisher`** (bib) | `bib_publisher_harmoniser.py` | - Clean publisher text strings.<br>- Cross-reconcile free text with URIs in `publisher_2`. |
| **`title`** (bib) | `bib_title_harmoniser.py` | - Clean extra characters/brackets.<br>- Extract material/document type tags (e.g. `[estampe]`). |

### 2. Migration of Existing Scripts from `03_analysis` to `04_harmonisation`

Several scripts currently located in the analysis module perform active data cleaning, matching, or deduplication and should be migrated to `04_harmonisation`:

1. **Names Toolkit (`03_analysis/actors/names/` $\rightarrow$ `04_harmonisation/actors/names/`)**
   - *Scripts*: `detect_real_names.py`, `enhanced_detect_names.py`, `enhanced_detect_names_cleaner.py`, `csv_analysis_maker.py`
   - *Reason*: These scripts actively filter personal names, detect noise using Flair NER, and generate tables for manual cleaning.
2. **Actor Merging & Deduplication (`reduce_actors_dataset.py` $\rightarrow$ `04_harmonisation/actors/reduce_actors.py`)**
   - *Reason*: This script performs record deduplication, merges rows, and flags conflicting actor properties, which is a core harmonisation task.
3. **Actor Entity Matching (`actors_id_matching.py` and `actors_name_matching.py` $\rightarrow$ `04_harmonisation/actors/`)**
   - *Reason*: These scripts handle entity resolution and ID/name mapping to align records, aligning with the harmonisation stage rather than post-clean profiling.