# System Monitor Scripts

This directory contains two functionally equivalent system monitoring scripts:

- `monitor.py`
- `monitor.R`

Both scripts implement the same monitoring logic, produce the same class of outputs, and follow the same reporting policy.

They support two usage modes:

- **standalone continuous monitoring**, when executed directly;
- **embedded state-based monitoring**, when imported or sourced by other scripts.

---

## Purpose

These scripts monitor the current machine and the current process and write a textual report to disk.

Their goal is to provide a lightweight, passive monitoring layer for long-running scripts without performing active network benchmarks or other intrusive operations.

The monitoring logic includes:

- system CPU usage
- system memory usage
- root disk usage
- GPU utilisation and GPU memory usage, when available
- network throughput estimated from byte-counter deltas
- current process CPU usage
- current process memory usage

---

## Main Design Choices

The Python and R versions are aligned to the same behaviour and formulas.

The implementation deliberately avoids active speed tests during each cycle. Instead, network download and upload speeds are estimated passively from cumulative byte counters. This approach is more stable, less invasive, and much cheaper computationally than repeatedly launching bandwidth tests.

The scripts also generate persistent text reports with the same naming logic and the same output structure.

In addition to the standalone infinite-loop monitor, both scripts now expose a reusable state-based monitoring API. This allows other long-running scripts to update monitoring checkpoints at meaningful execution stages without duplicating monitoring code.

---

## Report Output Location

Reports are written to:

`00_monitor/report`

This is a **relative path**.

This means that the actual destination depends on the working directory from which the script is launched.

### Typical Case

If the script is launched from the project root, reports will be saved in:

`<project_root>/00_monitor/report`

### Example

If the project root is:

`/Users/username/Documents/GitHub/New-BnF-Data-Analysis-2`

then the reports will be written to:

`/Users/username/Documents/GitHub/New-BnF-Data-Analysis-2/00_monitor/report`

---

## Report File Naming

Each report file is named using:

`<entry_script_name> + <timestamp> + _<language>.txt`

### Python

Format:

`<entry_script_name>_YYYYMMDD_HHMMSS_py.txt`

Example:

`main_20260316_104512_py.txt`

### R

Format:

`<entry_script_name>_YYYYMMDD_HHMMSS_R.txt`

Example:

`main_20260316_104512_R.txt`

---

## Meaning of "Entry Script Name"

The report name is based on the script that started execution.

### Python

In the Python implementation, the name is derived from the top-level script associated with `__main__`.

### R

In the R implementation, the name is derived from the `--file=` argument used by `Rscript`.

If no file can be identified, the fallback name is:

`interactive_session`

---

## Metrics Collected

### 1. System CPU

System CPU is computed from `/proc/stat` by comparing two samples over time.

The scripts read total CPU time and idle CPU time, then compute usage as:

`(1 - delta_idle / delta_total) * 100`

### 2. System Memory

Memory usage is computed from `/proc/meminfo` using:

- `MemTotal`
- `MemAvailable`

The percentage is calculated as:

`(MemTotal - MemAvailable) / MemTotal * 100`

### 3. Disk Usage

Disk usage is read from the root filesystem using:

`df -P /`

The reported value is the percentage used for `/`.

### 4. Network Throughput

Network speed is not measured through active benchmarking.

Instead, the scripts:

1. identify the default interface, if possible;
2. read cumulative byte counters;
3. compute upload and download speed from the difference between two samples.

The reported speeds are in Mbps.

### 5. GPU Metrics

If NVIDIA tooling is available, both scripts query:

- GPU utilisation
- GPU memory used

This is done via:

`nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits`

If GPU information is not available, both values fall back to zero.

### 6. Process CPU

Process CPU is computed from process CPU jiffies and elapsed wall-clock time.

### 7. Process Memory

Process memory is computed as RSS divided by total system memory.

---

## Monitoring Modes

### 1. Standalone Continuous Monitoring

When executed directly, each script starts an infinite monitoring loop.

In this mode:

- a report file is created;
- a header is written;
- the monitor sleeps for the configured interval;
- one metrics block is appended per cycle;
- a footer is written on graceful interruption.

This is the traditional continuous monitor mode.

### 2. Embedded State-Based Monitoring

When imported or sourced by another script, the monitor can be used as a reusable component.

In this mode:

- a report file is created once;
- the caller explicitly triggers monitoring updates at meaningful checkpoints;
- no infinite loop is started automatically;
- the caller decides when to start, update, and stop the monitor.

This is the mode used by scripts such as:

- `01_data_retrieval/01_editions/query_editions.R`
- `01_data_retrieval/02_actors/query_agents.R`

---

## Reusable Monitoring API

Both implementations now expose a reusable monitoring API.

### Python

The Python monitor exposes:

- `start_monitor_state()`
- `collect_monitor_snapshot()`
- `advance_monitor_state()`
- `update_monitor_state()`
- `stop_monitor_state()`

It also provides:

- `safe_close_file()`

### R

The R monitor exposes:

- `start_monitor_state()`
- `collect_monitor_snapshot()`
- `advance_monitor_state()`
- `update_monitor_state()`
- `stop_monitor_state()`

It also provides:

- `safe_close_connection()`

### Purpose of the API

This API allows external scripts to:

- initialise monitoring once;
- collect and write monitoring data without starting an infinite loop;
- attach a textual execution context to a monitoring checkpoint;
- close the report cleanly at the end of the host script.

---

## Report Structure

Each report contains:

- a header with execution metadata;
- one block per monitoring cycle or checkpoint;
- a footer written on graceful interruption or explicit stop.

### Header Fields

The header includes:

- start time
- entry script name
- process ID
- selected network interface
- network speed source

Depending on the usage mode, it may also include:

- sampling interval
- sampling mode

### Per-Cycle / Per-Checkpoint Block

Each cycle or checkpoint writes:

- system CPU, memory, and disk usage
- GPU utilisation and memory usage
- network download and upload throughput
- process CPU and memory usage

It may also include:

- a context line describing the execution stage associated with that checkpoint

### Footer Fields

When the process is interrupted or the monitor is explicitly stopped, the report ends with:

- end time
- total duration
- total number of cycles

---

## Sampling Interval vs Sampling Mode

### Sampling Interval

In standalone continuous monitoring, the report header includes:

`Sampling Interval: <seconds>`

This is the sleep interval between cycles.

### Sampling Mode

In embedded monitoring, the report header may include:

`Sampling Mode: <description>`

This describes how checkpoints are produced.

Example:

`checkpoint-based updates during query_editions.R execution`

This is useful when monitoring is tied to semantic workflow stages rather than a fixed timer loop.

---

## Optional Context per Checkpoint

The reusable monitoring API allows a caller to attach an optional textual context to each written block.

Examples:

- `Completed acquisition for year 1454`
- `Completed actor CSV merge and final output writing`

This context is written into the report block and optionally printed to console.

This feature is especially useful for long-running data pipelines where monitoring checkpoints should be associated with a specific processing stage.

---

## Console Output

In addition to writing a report file, the monitor can also print the current metrics to standard output.

In standalone mode, this happens at every cycle.

In embedded mode, this happens whenever the caller requests an update with console output enabled.

This provides immediate visibility while preserving a persistent log on disk.

---

## Resume Log

If a file named `resume_info.log` exists in the current working directory, its content is printed at startup under a `[RESUME]` label.

This does not alter the monitoring logic. It is purely informational.

---

## Execution

### Python

Run from the project root:

```bash
python 00_monitor/monitor.py
```

### R

Run from the project root:

```bash
Rscript 00_monitor/monitor.R
```

---

## Automatic Execution Behaviour

### Python

The Python script runs the standalone monitor only when executed as the main script:

```python
if __name__ == "__main__":
    monitor_system()
```

This means the file can also be imported safely without starting the infinite monitoring loop.

### R

The R script runs the standalone monitor only when executed directly:

```r
if (sys.nframe() == 0) {
  monitor_system()
}
```

This is important because it allows the R functions to be sourced during tests or reused by other scripts without starting the infinite monitoring loop.

---

## Embedded Usage Pattern

### Python

Typical embedded usage:

```python
state = start_monitor_state(
    sampling_mode="checkpoint-based updates during host script execution"
)

state = update_monitor_state(
    state=state,
    context="Completed checkpoint 1"
)

state = stop_monitor_state(state)
```

### R

Typical embedded usage:

```r
state <- start_monitor_state(
  sampling_mode = "checkpoint-based updates during host script execution"
)

state <- update_monitor_state(
  state = state,
  context = "Completed checkpoint 1"
)

state <- stop_monitor_state(state)
```

---

## Tests

The monitor logic is covered by unit tests located in:

- `00_test/test_monitor_py.py`
- `00_test/test_monitor_R.R`

The tests verify deterministic behaviour and the reusable monitoring API rather than the live infinite monitoring loop itself.

They now cover:

- report-path generation
- report filename format
- system CPU formula
- network throughput formula
- process CPU formula
- safe report closing
- report header writing
- metrics block writing
- monitor state initialisation
- snapshot collection
- state advancement
- state update through snapshot collection
- footer writing and clean shutdown

---

## Run Python Tests

From the project root:

```bash
pytest 00_test/test_monitor_py.py
```

or:

```bash
python -m pytest 00_test/test_monitor_py.py
```

## Run R Tests

From the project root:

```bash
Rscript -e 'testthat::test_file("00_test/test_monitor_R.R")'
```

---

## Platform Constraints

These scripts are designed around Linux-style system interfaces.

In particular, they rely on files such as:

- `/proc/stat`
- `/proc/meminfo`
- `/proc/net/route`
- `/proc/net/dev`
- `/proc/<pid>/stat`
- `/proc/<pid>/status`

As a consequence, they are suitable for Linux environments and Linux-like containers.

They are not portable as-is to macOS or Windows for live execution.

---

## Important Distinction

- the tests can still pass on non-Linux systems, because they target pure computational functions, report-writing logic, and loading behaviour;
- the actual live monitors require Linux-style `/proc` access to run correctly.

---

## Error Handling

Where possible, missing optional resources fall back to safe defaults:

- unavailable GPU metrics return zeroes;
- missing network interface results in zero network throughput;
- parsing failures typically fall back to zero values.

However, the core Linux system files required for live monitoring must be available for correct execution.

---

## Directory Summary

This directory typically contains:

- `monitor.py` — Python implementation
- `monitor.R` — R implementation
- `report/` — generated monitoring reports
- `README.md` — this documentation

---

## Summary

The Python and R implementations are aligned in:

- monitoring scope
- formulas
- report layout
- report naming
- output directory policy
- standalone execution behaviour
- reusable embedded monitoring API
- graceful interruption and shutdown behaviour

The generated report files are written to:

```text
00_monitor/report
```

relative to the directory from which the monitor is launched.

If the scripts are launched from the repository root, the effective destination is:

```text
<root_repo>/00_monitor/report
```