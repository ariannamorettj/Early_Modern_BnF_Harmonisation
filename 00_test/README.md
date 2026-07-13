# Test Suite

This directory contains the test suite for the project. Tests are organised by script or module and cover both R and Python components.

---

## Test Files

| File | Language | Covers |
|---|---|---|
| `test_monitor_R.R` | R | `00_monitor/monitor.R` |
| `test_query_editions.R` | R | `01_data_retrieval/01_editions/query_editions.R` |
| `test_query_actors.R` | R | `01_data_retrieval/02_actors/query_agents.R` |
| `test_monitor_py.py` | Python | `00_monitor/monitor.py` |
| `test_place_harmonisation.py` | Python | `04_harmonisation_and_evaluation/.../bnf_place_harmonisation.py` |

---

## Running the Tests

All commands must be run from the **project root directory**.

### Run all R tests

```bash
Rscript -e 'testthat::test_dir("00_test", reporter = testthat::ProgressReporter$new(show_praise = FALSE))'
```

### Run all Python tests (monitor only)

```bash
pytest 00_test/test_monitor_py.py -v
```

### Run all R and Python tests together

```bash
Rscript -e 'testthat::test_dir("00_test", reporter = testthat::ProgressReporter$new(show_praise = FALSE))' && pytest 00_test/test_monitor_py.py -v
```

---

## Running a Single Test File

### R

```bash
Rscript -e 'testthat::test_file("00_test/test_monitor_R.R")'
Rscript -e 'testthat::test_file("00_test/test_query_editions.R")'
Rscript -e 'testthat::test_file("00_test/test_query_actors.R")'
```

### Python

```bash
pytest 00_test/test_monitor_py.py -v
pytest 00_test/test_place_harmonisation.py -v
```

---

## Running a Single Test by Name

### R

Use `filter` to match a substring of the test name:

```bash
Rscript -e 'testthat::test_file("00_test/test_monitor_R.R", filter = "parse_resume_log")'
```

### Python

Use `-k` to match a substring of the test name:

```bash
pytest 00_test/test_monitor_py.py -v -k "stop_monitor"
```

---

## Notes on Warnings

The R test suite produces warnings of the form:

```
incomplete final line found by readTableHeader on '...'
```

These warnings come from CSV fixture files that lack a trailing newline. They do not affect test results and can be ignored.

---

## Notes on `test_place_harmonisation.py`

Several tests in `test_place_harmonisation.py` require data files that are not included in the repository. Those tests will fail if the expected input files are not present at their configured paths. This is a pre-existing condition unrelated to the test code itself.
