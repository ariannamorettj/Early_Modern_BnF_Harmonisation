# BnF Data Retrieval Scripts

This directory contains two coordinated R scripts for retrieving and structuring data from the BnF SPARQL endpoint:

- `01_data_retrieval/01_editions/query_editions.R`
- `01_data_retrieval/02_actors/query_agents.R`

The first script retrieves **edition-level bibliographic data** year by year.  
The second script uses the compiled editions dataset to extract **distinct actors** and retrieve actor-level metadata.

Both scripts can optionally use the shared monitor implemented in:

- `00_monitor/monitor.R`

---

## General Workflow

The intended execution order is:

1. run `query_editions.R` to retrieve yearly edition data and compile it into a single CSV;
2. run `query_agents.R` to read the compiled edition dataset, extract distinct actors, query actor metadata, and merge the actor results into a single CSV.

This creates a two-stage acquisition pipeline:

- **stage 1:** edition acquisition
- **stage 2:** actor acquisition based on the edition results

---

## Script 1: `query_editions.R`

### Purpose

`query_editions.R` retrieves BnF edition data from the endpoint year by year, saves one CSV per year, then compiles all yearly CSV files into a single dataset.

### Main responsibilities

The script:

- creates the required output directories;
- optionally writes a `sessionInfo()` snapshot for the acquisition run;
- detects the year from which to start or resume;
- builds and executes one SPARQL query per year;
- writes one CSV file per year;
- compiles all yearly CSV files into `bnf_edition_data_raw.csv`;
- computes basic descriptive statistics on the compiled data;
- optionally updates the shared system monitor after each acquisition step.

---

## Editions Output Structure

Running `query_editions.R` produces the following directory structure under:

`01_data_retrieval/01_editions`

### Main output directory

`01_data_retrieval/01_editions/data`

### Yearly raw files directory

`01_data_retrieval/01_editions/data/edition_raw_data_by_year`

### Typical generated files

- one CSV per year, for example:
  - `raw_edition_data_for_the_year_1454.csv`
  - `raw_edition_data_for_the_year_1455.csv`
- one compiled file:
  - `bnf_edition_data_raw.csv`
- one optional session information file:
  - `sessionInfo_of_the_bnf_data_acquisition_run_of_<date>.txt`

---

## Editions Functions

### `make_paths(base_dir = "01_data_retrieval/01_editions")`

Builds the internal path configuration used by the script.

It returns a list containing:

- `base_dir`
- `output_dir`
- `yearly_output_dir`

### `ensure_output_dirs(paths)`

Creates the editions output directories if they do not already exist.

### `write_session_info_file(output_dir)`

Writes the result of `sessionInfo()` to a dated text file in the editions output directory.

This is useful for documenting the execution environment of the acquisition run.

### `get_start_year(yearly_output_dir, first_year = 1454)`

Determines the year from which the script should start querying.

It inspects the yearly output directory for files matching:

`raw_edition_data_for_the_year_YYYY.csv`

Behaviour:

- if no yearly files are found, it returns `first_year`;
- if matching yearly files exist, it extracts the available years and returns the maximum detected year.

### Important resume note

The current implementation returns the **maximum existing year**, not `max + 1`.

This means that if the latest retrieved year is already present, that year may be queried again and its corresponding yearly CSV may be rewritten.

So the script behaves as a **soft resume based on existing files**, but not as a strict skip-to-next-year mechanism.

### `build_bnf_edition_query(year)`

Builds the SPARQL query for a single target year.

The query retrieves edition-level data and related expression-level information, including fields such as:

- edition URI
- BnF identifier
- title
- first year
- date range
- description
- place
- publisher
- work
- digital copy link
- subject topic
- expression
- language
- record type
- author
- editor
- translator
- publisher_2
- illustrator

The query filters on:

`?year_first = <year>`

### `run_sparql_query(query, url = "https://data.bnf.fr/sparql")`

Executes the SPARQL query against the BnF endpoint and returns the result table.

### `get_bnf_edition_data(year, yearly_output_dir, query_fun = run_sparql_query, sleep = TRUE)`

Executes the acquisition for a single year.

It:

1. builds the query for the requested year;
2. executes it through `query_fun`;
3. writes the result to a yearly CSV file;
4. optionally sleeps for a random delay between 5 and 10 seconds;
5. removes the in-memory table and calls `gc()`.

The yearly CSV is written to:

`01_data_retrieval/01_editions/data/edition_raw_data_by_year/raw_edition_data_for_the_year_<year>.csv`

### `compile_edition_data(yearly_output_dir)`

Reads all yearly CSV files and row-binds them into a single data frame.

If no yearly CSV files are found, it raises an error.

### `write_compiled_edition_data(data, output_dir)`

Writes the compiled edition dataset to:

`01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv`

### `compute_edition_stats(df)`

Computes basic descriptive counts on the compiled edition dataset, including:

- number of unique editions;
- number of editions with place information;
- number of editions with record type information;
- number of editions with author information;
- number of editions with language information.

### `load_monitor_env(monitor_script = "00_monitor/monitor.R")`

Loads the shared monitor code into a dedicated environment using `sys.source()`.

This allows the script to call the monitor API without duplicating the monitoring logic.

### `run_query_editions(...)`

This is the main orchestration function.

Parameters:

- `base_dir`
- `first_year`
- `last_year`
- `query_fun`
- `sleep`
- `write_session_info`
- `use_monitor`
- `monitor_script`

The function:

1. builds and creates output directories;
2. optionally writes session info;
3. determines the start year;
4. optionally starts the monitor;
5. loops through the target years;
6. writes yearly CSV files;
7. compiles the yearly files;
8. writes the compiled edition dataset;
9. computes descriptive statistics;
10. optionally writes monitor checkpoints and stops the monitor;
11. returns an invisible list with paths, data, stats, start year, compiled output file, and monitor report path if enabled.

---

## Editions Monitor Integration

If `use_monitor = TRUE`, the script imports `00_monitor/monitor.R` and uses its embedded API:

- `start_monitor_state()`
- `update_monitor_state()`
- `stop_monitor_state()`

The monitor is started once at the beginning of the run.

A monitoring checkpoint is written:

- after each completed yearly acquisition;
- after the compiled CSV and statistics are produced.

The sampling mode written in the monitor report is:

`checkpoint-based updates during query_editions.R execution`

This is not a continuous timed loop.  
It is a **state-based checkpoint monitor**, updated at meaningful stages of the data acquisition pipeline.

---

## Script 2: `query_agents.R`

### Purpose

`query_agents.R` reads the compiled editions dataset, extracts distinct actors from the relevant role columns, queries the BnF endpoint for each actor, saves one intermediate CSV per actor, and merges all actor CSV files into a final actor dataset.

### Main responsibilities

The script:

- creates the required actor output directories;
- reads the compiled edition dataset;
- extracts distinct actor URIs from selected role columns;
- resumes from the last processed actor index if available;
- builds and executes one SPARQL query per actor;
- writes one CSV per actor when results exist;
- records progress in a progress file;
- merges all actor CSV files into a single output dataset;
- optionally updates the shared system monitor after each actor step.

---

## Actors Output Structure

Running `query_agents.R` produces the following directory structure under:

`01_data_retrieval/02_actors`

### Main output directory

`01_data_retrieval/02_actors/data`

### Intermediate actor files directory

`01_data_retrieval/02_actors/data/actor_queries_results`

### Progress file

`01_data_retrieval/02_actors/data/last_processed_index.txt`

### Typical generated files

- many intermediate CSV files such as:
  - `actor_file_1.csv`
  - `actor_file_2.csv`
  - `actor_file_3.csv`
- one merged actor dataset:
  - `actor_data.csv`
- one progress file:
  - `last_processed_index.txt`

---

## Actors Functions

### `make_actor_paths(...)`

Builds the internal path configuration used by the actors script.

It returns a list containing:

- `base_dir`
- `output_dir`
- `intermediate_output_dir`
- `editions_input`
- `progress_file`

By default, `editions_input` points to:

`01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv`

### `ensure_actor_output_dirs(paths)`

Creates the actor output directories if they do not already exist.

### `get_start_index(progress_file)`

Determines from which actor index the script should start.

Behaviour:

- if the progress file does not exist, it returns `1`;
- if the file exists but cannot be parsed as an integer, it returns `1`;
- otherwise it returns `last_index + 1`.

This makes the actor pipeline a true **index-based resume mechanism**.

### `build_actor_query(actor)`

Builds the SPARQL query for one actor URI.

The query requests actor-level metadata, including:

- birth
- name
- first name
- last name
- entity type
- first year
- country
- language
- gender
- profession / biographical information
- death
- start year
- end year
- exact match links
- close match links

### `run_actor_sparql_query(query, url = "https://data.bnf.fr/sparql")`

Executes a live actor query against the BnF endpoint.

It checks that the `SPARQL` package is available before performing the query.

### `get_bnf_data_for_actor(actor, file_name, intermediate_output_dir, query_fun = run_actor_sparql_query, sleep = TRUE)`

Executes the acquisition for a single actor.

It:

1. builds the actor query;
2. executes it through `query_fun`;
3. writes the result to a CSV file if the returned table is non-empty;
4. optionally sleeps for a random delay between 1 and 2 seconds;
5. returns `TRUE`.

Important behaviour:

- if the query result is empty, no actor CSV is written;
- the function still returns `TRUE`.

### `read_editions_input(editions_input)`

Reads the compiled edition dataset from CSV.

### `extract_distinct_actors(editions_df)`

Extracts unique actor values from the following role columns, when present:

- `author`
- `editor`
- `illustrator`
- `publisher_2`
- `translator`

The function:

1. keeps only the role columns that actually exist;
2. flattens all values;
3. trims whitespace;
4. removes `NA` and empty strings;
5. removes duplicates;
6. returns a one-column data frame named `actor`.

### `merge_actor_csvs(intermediate_output_dir, output_dir)`

Reads all actor CSV files from the intermediate output directory, row-binds them, and writes the merged dataset to:

`01_data_retrieval/02_actors/data/actor_data.csv`

If no actor CSV files are found, it raises an error.

### `load_monitor_env(monitor_script = "00_monitor/monitor.R")`

Loads the shared monitor code into a dedicated environment using `sys.source()`.

### `run_query_agents(...)`

This is the main orchestration function.

Parameters:

- `base_dir`
- `editions_input`
- `query_fun`
- `sleep`
- `use_monitor`
- `monitor_script`

The function:

1. builds and creates output directories;
2. reads the compiled editions dataset;
3. extracts distinct actors;
4. checks that at least one actor is available;
5. computes the start index from the progress file;
6. optionally starts the monitor;
7. loops over the actors from the resume point onward;
8. queries one actor at a time;
9. writes progress after successful processing;
10. updates the monitor at each checkpoint;
11. merges all actor CSV files into `actor_data.csv`;
12. writes a final monitor checkpoint and stops the monitor;
13. returns an invisible list with paths, actors, merged data, output file, start index, and monitor report path if enabled.

---

## Actors Resume Behaviour

The actors script has a stricter resume mechanism than the editions script.

### Progress tracking

After each successful actor query, the script writes the current index to:

`01_data_retrieval/02_actors/data/last_processed_index.txt`

At the next execution, the script resumes from:

`last_processed_index + 1`

### Meaning of “successful”

In the current implementation, success means that `get_bnf_data_for_actor()` completed without error.

This includes the case where:

- the actor query returned zero rows;
- no actor CSV file was written;
- but the function still returned `TRUE`.

So the progress file tracks **processed actor indices**, not only actors that produced output rows.

---

## Actors Monitor Integration

If `use_monitor = TRUE`, the script imports `00_monitor/monitor.R` and uses:

- `start_monitor_state()`
- `update_monitor_state()`
- `stop_monitor_state()`

The monitor is started once at the beginning of the run.

A monitoring checkpoint is written:

- after each actor attempt;
- after the final merged actor CSV is produced.

For each actor step, the monitor context records either:

- `Completed acquisition for actor index <i> - <actor>`
- `Failed acquisition for actor index <i> - <actor>`

The sampling mode written in the monitor report is:

`checkpoint-based updates during query_agents.R execution`

---

## Shared Monitor Usage

Both scripts rely on the same monitor module:

`00_monitor/monitor.R`

### How it is loaded

Each script loads the monitor through:

```r
load_monitor_env <- function(monitor_script = "00_monitor/monitor.R") {
  resolved_monitor_script <- normalizePath(monitor_script, mustWork = TRUE)
  env <- new.env(parent = baseenv())
  sys.source(resolved_monitor_script, envir = env)
  env
}
```

This keeps the retrieval scripts independent while still reusing the central monitoring implementation.

### Monitor API used by both retrieval scripts

- `start_monitor_state()`
- `update_monitor_state()`
- `stop_monitor_state()`

### Monitor output location

The monitor writes its reports to:

`00_monitor/report`

using the report-naming logic defined in `00_monitor/monitor.R`.

---

## Default Execution Behaviour

Both retrieval scripts run automatically only when executed directly.

### Editions

```r
if (sys.nframe() == 0) {
  run_query_editions(use_monitor = TRUE)
}
```

### Actors

```r
if (sys.nframe() == 0) {
  run_query_agents(use_monitor = TRUE)
}
```

This means they can also be safely sourced during tests or reused as libraries without automatically launching the acquisition.

---

## Recommended Execution Order

### Step 1: retrieve edition data

From the project root:

```bash
Rscript 01_data_retrieval/01_editions/query_editions.R
```

### Step 2: retrieve actor data

From the project root:

```bash
Rscript 01_data_retrieval/02_actors/query_agents.R
```

---

## Main Input and Output Dependencies

### `query_editions.R`

**Inputs**

- the BnF SPARQL endpoint
- optional pre-existing yearly CSV files in the yearly output directory

**Outputs**

- yearly edition CSV files
- compiled edition CSV
- optional session info file
- optional monitor report

### `query_agents.R`

**Inputs**

- `01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv`
- optional pre-existing actor CSV files
- optional progress file
- the BnF SPARQL endpoint

**Outputs**

- one actor CSV per processed actor with non-empty results
- merged actor CSV
- updated progress file
- optional monitor report

---

## Important Behavioural Notes

### 1. The scripts do not clean output directories

Neither script removes pre-existing CSV files from its output directories.

They create directories if needed and then write new or replacement files.

### 2. Existing files may be rewritten

Some output files may be overwritten if the same path is generated again.

Examples:

- yearly edition CSV files for the same year;
- `bnf_edition_data_raw.csv`;
- `actor_data.csv`;
- actor intermediate CSV files with the same actor index.

### 3. The monitor does not delete old reports

The shared monitor creates a timestamped report file in `00_monitor/report`.  
It does not clean the report directory.

### 4. Editions and actors use different resume logic

- `query_editions.R` resumes by inspecting existing yearly files and starting from the maximum detected year;
- `query_agents.R` resumes from a saved integer index in `last_processed_index.txt`.

### 5. Empty actor query results are considered processed

An actor query that returns zero rows still counts as processed if no error occurred.

---

## Practical Summary

### `query_editions.R`

Use this script to:

- retrieve BnF edition data year by year;
- build the main raw editions dataset;
- create the dataset that feeds actor extraction.

### `query_agents.R`

Use this script to:

- read the compiled editions dataset;
- extract distinct actor URIs;
- retrieve actor-level metadata;
- build the final actor dataset.

### Shared monitor

Use the monitor-enabled default execution when you want:

- a persistent system monitoring report;
- execution checkpoints tied to years or actor indices;
- a reproducible monitoring log in `00_monitor/report`.

---

## Minimal Example

### Editions only

```r
source("01_data_retrieval/01_editions/query_editions.R")
result <- run_query_editions(use_monitor = FALSE)
```

### Editions with monitor

```r
source("01_data_retrieval/01_editions/query_editions.R")
result <- run_query_editions(use_monitor = TRUE)
```

### Actors only

```r
source("01_data_retrieval/02_actors/query_agents.R")
result <- run_query_agents(use_monitor = FALSE)
```

### Actors with monitor

```r
source("01_data_retrieval/02_actors/query_agents.R")
result <- run_query_agents(use_monitor = TRUE)
```

---

## Returned Objects

### `run_query_editions()`

Returns invisibly a list containing:

- `paths`
- `data`
- `stats`
- `start_year`
- `compiled_out_file`
- `monitor_report` when monitoring is enabled

### `run_query_agents()`

Returns invisibly a list containing:

- `paths`
- `actors`
- `data`
- `out_file`
- `start_index`
- `monitor_report` when monitoring is enabled

---

## Dependency Summary

These scripts rely on:

- `SPARQL`
- `tidyverse` for the editions statistics function
- base R functionality for file management, resume handling, and CSV writing
- `00_monitor/monitor.R` when embedded monitoring is enabled

They also rely on:

- network access to the BnF SPARQL endpoint
- the expected project-relative directory structure

---

## Final Notes

These two scripts are designed to work together as a reproducible acquisition pipeline:

- `query_editions.R` builds the bibliographic edition dataset;
- `query_agents.R` enriches that pipeline by retrieving metadata for the distinct actors referenced in the editions dataset.

The shared monitor integration allows both scripts to produce system-monitoring reports without embedding duplicate monitoring code inside the acquisition logic.