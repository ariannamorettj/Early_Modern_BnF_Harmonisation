# BnF Data Retrieval Scripts

This directory contains three coordinated R scripts for retrieving and structuring data from the BnF SPARQL endpoint:

- `01_data_retrieval/01_editions/query_editions.R`
- `01_data_retrieval/02_actors/query_agents.R`
- `01_data_retrieval/recover_missing_acquisitions.R`

The first script retrieves **edition-level bibliographic data** year by year.  
The second script uses the compiled editions dataset to extract **distinct actors** and retrieve actor-level metadata.  
The third script detects and re-acquires anything the first two silently skipped, and is meant to be run precautionarily after every editions+actors acquisition.

Both acquisition scripts can optionally use the shared monitor implemented in:

- `00_monitor/monitor.R`

The recovery script always uses it, since the monitor report is both its source of truth for what was skipped and the place it records what it fixed.

---

## General Workflow

The intended execution order is:

1. run `query_editions.R` to retrieve yearly edition data and compile it into a single CSV;
2. run `query_agents.R` to read the compiled edition dataset, extract distinct actors, query actor metadata, and merge the actor results into a single CSV;
3. run `recover_missing_acquisitions.R` to check both stages for skipped years/actors and re-acquire them.

This creates a three-stage acquisition pipeline:

- **stage 1:** edition acquisition
- **stage 2:** actor acquisition based on the edition results
- **stage 3:** recovery of anything stages 1-2 skipped

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

### `format_duration(secs)`

Converts a numeric value in seconds to a human-readable string.

Output format:

- `Xh MMm SSs` when hours are present;
- `Mm SSs` when only minutes and seconds are present;
- `Ss` for durations under one minute.

### `print_progress(current, total, start_time, step_times)`

Prints a single-line progress bar to the console, updated in place via `\r`.

Parameters:

- `current`: position in the full sequence (1-based);
- `total`: total number of steps in the full sequence;
- `start_time`: `Sys.time()` value captured before the loop started;
- `step_times`: numeric vector of elapsed seconds for each completed step in the current session.

Output format:

```
[=============>                          ]  38%  132/346  elapsed: 22m 14s  ETA: 36m 05s
```

The ETA is computed as the mean of the last 10 completed step durations multiplied by the number of remaining steps.

When `current` equals `total`, a final newline is printed to end the overwriting line.

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
5. initialises loop timing variables (`loop_start`, `step_times`);
6. loops through the target years;
7. records per-step elapsed time;
8. prints a progress bar with ETA after each step;
9. writes yearly CSV files;
10. compiles the yearly files;
11. writes the compiled edition dataset;
12. computes descriptive statistics;
13. optionally writes monitor checkpoints and stops the monitor;
14. returns an invisible list with paths, data, stats, start year, compiled output file, and monitor report path if enabled.

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

### `format_duration(secs)`

Converts a numeric value in seconds to a human-readable string.

Output format:

- `Xh MMm SSs` when hours are present;
- `Mm SSs` when only minutes and seconds are present;
- `Ss` for durations under one minute.

### `print_progress(current, total, start_time, step_times)`

Prints a single-line progress bar to the console, updated in place via `\r`.

Parameters:

- `current`: current actor index (`i` in the loop, 1-based in the full actor list);
- `total`: total number of distinct actors (`nrow(actors_df)`);
- `start_time`: `Sys.time()` value captured before the loop started;
- `step_times`: numeric vector of elapsed seconds for each completed step in the current session.

Output format:

```
[=============>                          ]  38%  4201/11000  elapsed: 1h 45m 12s  ETA: 2h 51m 30s
```

The ETA is computed as the mean of the last 10 completed step durations multiplied by the number of remaining steps.

When `current` equals `total`, a final newline is printed to end the overwriting line.

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
7. initialises loop timing variables (`loop_start`, `step_times`);
8. loops over the actors from the resume point onward;
9. records per-step elapsed time;
10. prints a progress bar with ETA after each step;
11. queries one actor at a time;
12. writes progress after successful processing;
13. updates the monitor at each checkpoint;
14. merges all actor CSV files into `actor_data.csv`;
15. writes a final monitor checkpoint and stops the monitor;
16. returns an invisible list with paths, actors, merged data, output file, start index, and monitor report path if enabled.

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
- `stop_monitor_state(status = ...)`

### Interruption status tracking

Both scripts pass an explicit `status` parameter to `stop_monitor_state()` to distinguish normal completion from clean interruption:

- the `on.exit()` hook passes `status = "INTERRUPTED"` — this fires on R errors and Ctrl+C;
- the explicit call at the end of the normal flow uses the default `status = "COMPLETED"`.

If the process is killed brutally (SIGKILL, power loss, OS crash), neither call runs. The monitor's `resume_info.log` retains `status = "RUNNING"`, which the next run detects and reports as `BRUTALLY INTERRUPTED`.

In all three cases, the **next run's report header** includes a "Previous run detected" block with the previous script name, report path, start time, last completed checkpoint, status, and end time (when available). This creates an explicit cross-reference chain between successive runs.

### Monitor output location

The monitor writes its reports to:

`00_monitor/report`

using the report-naming logic defined in `00_monitor/monitor.R`.

---

## Script 3: `recover_missing_acquisitions.R`

### Purpose

`query_editions.R` and `query_agents.R` do not retry an individual item that fails mid-run - see [Actors Resume Behaviour](#actors-resume-behaviour) and the note below on why editions and actors need different detection strategies. `recover_missing_acquisitions.R` is a precautionary third stage: it scans for what stages 1 and 2 skipped, re-acquires it, and updates the monitor report with what it did.

It is meant to be run **after every editions + actors acquisition**, whether or not the run was interrupted - it is a no-op (beyond a quick scan) when nothing was skipped.

### Why detection differs between editions and actors

- **editions**: `get_bnf_edition_data()` always writes a yearly CSV, even when the SPARQL result is empty, and the editions loop has no per-year `tryCatch` - a query error crashes the whole `Rscript` process, which `run_query_editions_batched.ps1` then retries at the block level. So a missing yearly CSV file is unambiguous proof that the year was never completed, and gap detection can simply check for missing files.
- **actors**: `get_bnf_data_for_actor()` only writes a CSV when the SPARQL result is non-empty, and the actor loop wraps each query in `tryCatch` so a failure is swallowed and the loop moves on without ever revisiting that index (see [Actors Resume Behaviour](#actors-resume-behaviour)). A missing `actor_file_N.csv` is therefore **not** proof of a skipped actor - it may be a legitimate zero-result actor. The only reliable signal is the `Failed acquisition for actor index N` line the monitor writes to `00_monitor/report/query_agents_*_R.txt` for that index, so actor gap detection is log-based, not file-based.

### Main responsibilities

The script:

- scans `01_data_retrieval/01_editions/data/edition_raw_data_by_year` for missing yearly CSV files in the requested year range and re-queries each missing year (up to `max_attempts` tries, with a delay between attempts);
- recompiles `bnf_edition_data_raw.csv` if any edition year was recovered;
- if any edition year was recovered, syncs `distinct_actors_cache.csv` append-only (see note below) and logs every newly appended actor to `actor_cache_additions_log.csv`;
- scans all `00_monitor/report/query_agents_*_R.txt` and its own past `recover_missing_acquisitions_*_R.txt` reports for actor indices logged as failed (`Failed acquisition for actor index N` / `RECOVERY FAILED for actor index N`), excluding any already marked `RECOVERED actor index N` in a previous run;
- re-queries every candidate actor index - previously-failed ones and newly-appended ones alike (up to `max_attempts` tries each), or simply relabels it recovered if a CSV already exists for it;
- re-merges `actor_data.csv` if any actor index was recovered;
- writes one monitor checkpoint per recovered/still-failing item, each including the recovering script's name, why it was being recovered, and the item's processing duration, plus a final summary checkpoint with totals and total recovery duration.

### Important note: how editions recovery extends the actor list safely

`get_or_extract_distinct_actors()` in `query_agents.R` caches the distinct actor list to `distinct_actors_cache.csv` the first time actor acquisition runs, and every later run reads that cache instead of recomputing it - because `extract_distinct_actors()` orders actors by first occurrence while scanning the editions data column by column, and recomputing it from an editions dataset with newly-inserted rows could shift the position of actors that were already downloaded, silently misaligning existing `actor_file_N.csv` files against the wrong actor.

`recover_missing_acquisitions.R` avoids this by never recomputing the cache from scratch. When it recovers at least one edition year, `sync_actor_cache_append_only()`:

1. recomputes the full current distinct-actor list from the updated editions data;
2. diffs it against the existing cache by actor value (not position);
3. appends only the actors that are genuinely new, at new indices strictly after the old end of the cache - every existing row keeps its original index and value.

Every appended actor is recorded in `01_data_retrieval/02_actors/data/actor_cache_additions_log.csv` with its index, the actor URI, a timestamp, the recovering script's name, and which edition year(s) triggered it - a durable trace, independent of the (timestamped, per-run) monitor reports. The newly appended indices are then queried the same way as any other recovery candidate.

### `run_recovery(...)`

This is the main orchestration function.

Parameters:

- `editions_base_dir`, `actors_base_dir`, `editions_input`
- `first_year`, `last_year` (editions range to check, defaults `1454`-`1799`)
- `report_dir` (defaults to `00_monitor/report`, must match `monitor.R`'s `OUTPUT_DIR`)
- `monitor_script`, `use_monitor`
- `max_attempts`, `retry_delay_seconds` (per-item retry policy, defaults `3` and `5`)
- `edition_query_fun`, `actor_query_fun`, `sleep`

Returns invisibly a list containing:

- `missing_years`, `edition_recovery` (`recovered` / `still_missing` year vectors)
- `new_actor_indices` (indices appended to `distinct_actors_cache.csv` this run, if any)
- `candidate_actor_indices` (every actor index processed this run - previously-failed and newly-appended combined), `actor_recovery` (`recovered` / `still_failing` index vectors)
- `duration_seconds`
- `monitor_report` when monitoring is enabled

### Recovery Monitor Integration

Like the two acquisition scripts, `recover_missing_acquisitions.R` loads `00_monitor/monitor.R` and uses `start_monitor_state()` / `update_monitor_state()` / `stop_monitor_state()`. Because the monitor's `Entry Script:` header is derived from the running script's own filename, every recovery report is self-identifying as having come from `recover_missing_acquisitions`, and `resume_info.log`'s "Previous run detected" cross-reference picks it up the same way it does for the two acquisition scripts.

Typical context lines written to the report:

```
RECOVERED edition year 1512 (previously missing) via recover_missing_acquisitions | duration: 6s
Actor cache sync after edition recovery: 2 new actor(s) appended to distinct_actors_cache.csv (indices 124696-124697), logged to actor_cache_additions_log.csv
RECOVERED actor index 69151 - <http://data.bnf.fr/ark:/12148/cb124205436#about> (previously failed) via recover_missing_acquisitions | duration: 1s
RECOVERED actor index 124696 - <http://data.bnf.fr/ark:/12148/cbXXXXXXXXX#about> (new actor introduced by recovered edition year(s)) via recover_missing_acquisitions | duration: 1s
RECOVERY FAILED for actor index 9165 - <...> (previously failed) via recover_missing_acquisitions after 3 attempt(s) | duration: 12s
Recovery summary via recover_missing_acquisitions: editions 1/1 recovered; 2 new actor(s) discovered from recovered editions; actors 671/672 recovered (1 still failing after 3 attempt(s) each); total duration 18m 04s
```

---

## Default Execution Behaviour

All three retrieval scripts run automatically only when executed directly.

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

### Recovery

```r
if (sys.nframe() == 0) {
  run_recovery(use_monitor = TRUE)
}
```

This means they can also be safely sourced during tests or reused as libraries without automatically launching the acquisition. `recover_missing_acquisitions.R` itself loads `query_editions.R` and `query_agents.R` via `sys.source(..., envir = globalenv())` at the top of the file - the same mechanism `load_monitor_env()` uses - so their functions become available without triggering their own `if (sys.nframe() == 0)` blocks.

---

## Recommended Execution Order

All commands must be run from the **project root directory**. Step 2 cannot start before Step 1 has completed, because it reads the compiled editions CSV produced by Step 1. Step 3 should run after Step 2, every time, as a precaution - it is cheap when there is nothing to recover.

### Step 1: retrieve edition data

```bash
Rscript 01_data_retrieval/01_editions/query_editions.R
```

Queries the BnF SPARQL endpoint year by year from 1454 to 1799 (346 steps). Each step includes a random sleep of 5–10 seconds. Estimated duration: approximately 40–60 minutes depending on endpoint response time.

During execution the console shows a live progress bar:

```
[=============>                          ]  38%  132/346  elapsed: 22m 14s  ETA: 36m 05s
```

Output written to:

- `01_data_retrieval/01_editions/data/edition_raw_data_by_year/` — one CSV per year
- `01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv` — compiled dataset
- `00_monitor/report/query_editions_<timestamp>_R.txt` — monitoring report

### Step 2: retrieve actor data

```bash
Rscript 01_data_retrieval/02_actors/query_agents.R
```

Reads the compiled editions dataset, extracts distinct actor URIs, and queries the BnF endpoint for each actor. Each step includes a random sleep of 1–2 seconds. Duration depends on the number of distinct actors found in Step 1.

During execution the console shows a live progress bar:

```
[=============>                          ]  38%  4201/11000  elapsed: 1h 45m 12s  ETA: 2h 51m 30s
```

Output written to:

- `01_data_retrieval/02_actors/data/actor_queries_results/` — one CSV per actor
- `01_data_retrieval/02_actors/data/actor_data.csv` — merged actor dataset
- `01_data_retrieval/02_actors/data/last_processed_index.txt` — resume checkpoint
- `00_monitor/report/query_agents_<timestamp>_R.txt` — monitoring report

### Step 3: recover skipped years and actors

```bash
Rscript 01_data_retrieval/recover_missing_acquisitions.R
```

PowerShell, if `Rscript` is not on `PATH`:

```powershell
& "C:\Program Files\R\R-4.6.1\bin\Rscript.exe" 01_data_retrieval/recover_missing_acquisitions.R
```

Scans the editions output directory for missing yearly CSV files and `00_monitor/report/query_agents_*_R.txt` for actor indices logged as failed, then re-queries anything found. **Always run this command to close out an editions + actors acquisition** - whether or not Step 1/2 were interrupted - as the final guarantee that the whole process actually completed and nothing was silently lost; it is cheap when there is nothing to recover.

Output written to:

- (only if editions years were recovered) updated `01_data_retrieval/01_editions/data/edition_raw_data_by_year/` and `bnf_edition_data_raw.csv`
- (only if actor indices were recovered) updated `01_data_retrieval/02_actors/data/actor_queries_results/` and `actor_data.csv`
- `00_monitor/report/recover_missing_acquisitions_<timestamp>_R.txt` — monitoring report, doubling as the recovery ledger read by future recovery runs

### Resuming after interruption

All three scripts resume automatically if interrupted:

- **editions**: resumes from the last detected yearly CSV file
- **actors**: resumes from `last_processed_index + 1`
- **recovery**: re-running it simply re-scans for what is still missing; already-recovered actor indices are skipped via the ledger described in [Script 3](#script-3-recover_missing_acquisitionsr)

Simply re-run the same command from the project root to continue.

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

### `recover_missing_acquisitions.R`

**Inputs**

- existing yearly edition CSV files (to find gaps)
- `01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv` (re-read after any edition recompile, to detect new actors)
- `01_data_retrieval/02_actors/data/distinct_actors_cache.csv` (extended append-only, never reordered - see the note above)
- `00_monitor/report/query_agents_*_R.txt` (to find failed actor indices)
- `00_monitor/report/recover_missing_acquisitions_*_R.txt` (its own ledger, to avoid re-recovering already-handled indices)
- the BnF SPARQL endpoint

**Outputs**

- any missing yearly edition CSV file, plus a recompiled `bnf_edition_data_raw.csv` if at least one was recovered
- `01_data_retrieval/02_actors/data/distinct_actors_cache.csv`, extended with any newly discovered actors (only when at least one edition year was recovered)
- `01_data_retrieval/02_actors/data/actor_cache_additions_log.csv`, one row per newly appended actor (index, actor URI, timestamp, recovering script, triggering edition year(s))
- any missing actor CSV file, plus a re-merged `actor_data.csv` if at least one was recovered
- a monitor report

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

An actor query that returns zero rows still counts as processed if no error occurred. This is exactly why `recover_missing_acquisitions.R` cannot use file-existence to detect skipped actors - see [Script 3](#script-3-recover_missing_acquisitionsr).

### 6. A failed actor acquisition is silently skipped, not retried, by `query_agents.R`

If `get_bnf_data_for_actor()` errors for a given index, the actor loop logs it, moves on, and never revisits that index within the same run - `last_processed_index.txt` only ever advances forward on success, so a later successful index permanently overwrites any chance of resuming at the failed one. `recover_missing_acquisitions.R` (Step 3) exists specifically to close this gap; run it after every actor acquisition.

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

### `recover_missing_acquisitions.R`

Use this script to:

- detect edition years and actor indices that stages 1-2 skipped;
- re-acquire them without disturbing already-processed data;
- record what was recovered, how long it took, and which script did it, in the shared monitor report.

Run it as a precaution after every editions + actors acquisition.

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

### Recovery

```r
source("01_data_retrieval/recover_missing_acquisitions.R")
result <- run_recovery(use_monitor = TRUE)
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

### `run_recovery()`

Returns invisibly a list containing:

- `missing_years`
- `edition_recovery` (a list with `recovered` and `still_missing` year vectors)
- `candidate_actor_indices`
- `actor_recovery` (a list with `recovered` and `still_failing` index vectors)
- `duration_seconds`
- `monitor_report` when monitoring is enabled

---

## Dependency Summary

These scripts rely on:

- `SPARQL`
- `tidyverse` for the editions statistics function
- base R functionality for file management, resume handling, and CSV writing
- `00_monitor/monitor.R` when embedded monitoring is enabled

`recover_missing_acquisitions.R` additionally relies on `query_editions.R` and `query_agents.R` themselves (loaded via `sys.source()` for their helper functions).

They also rely on:

- network access to the BnF SPARQL endpoint
- the expected project-relative directory structure

---

## Final Notes

These three scripts are designed to work together as a reproducible acquisition pipeline:

- `query_editions.R` builds the bibliographic edition dataset;
- `query_agents.R` enriches that pipeline by retrieving metadata for the distinct actors referenced in the editions dataset;
- `recover_missing_acquisitions.R` closes the loop by catching and re-acquiring whatever the first two silently skipped.

The shared monitor integration allows all three scripts to produce system-monitoring reports without embedding duplicate monitoring code inside the acquisition logic.