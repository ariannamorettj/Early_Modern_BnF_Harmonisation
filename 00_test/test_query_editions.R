# 00_test/test_query_editions.R

library(testthat)

script_path <- normalizePath(
  file.path("..", "01_data_retrieval", "01_editions", "query_editions.R"),
  mustWork = TRUE
)

# Source the script in a custom environment so that tests can run
# even if the archived {SPARQL} package is not installed.
test_env <- new.env(parent = globalenv())

test_env$library <- function(package, ..., character.only = FALSE,
                             logical.return = FALSE,
                             warn.conflicts = TRUE,
                             quietly = FALSE,
                             verbose = getOption("verbose")) {
  pkg_name <- if (character.only) package else deparse(substitute(package))

  # Ignore SPARQL only at source time: tests use mocked query functions
  if (identical(pkg_name, "SPARQL")) {
    return(invisible(TRUE))
  }

  base::library(
    pkg_name,
    ...,
    character.only = TRUE,
    logical.return = logical.return,
    warn.conflicts = warn.conflicts,
    quietly = quietly,
    verbose = verbose
  )
}

sys.source(script_path, envir = test_env)

make_paths <- test_env$make_paths
ensure_output_dirs <- test_env$ensure_output_dirs
write_session_info_file <- test_env$write_session_info_file
get_start_year <- test_env$get_start_year
build_bnf_edition_query <- test_env$build_bnf_edition_query
get_bnf_edition_data <- test_env$get_bnf_edition_data
compile_edition_data <- test_env$compile_edition_data
write_compiled_edition_data <- test_env$write_compiled_edition_data
compute_edition_stats <- test_env$compute_edition_stats
load_monitor_env <- test_env$load_monitor_env
run_query_editions <- test_env$run_query_editions

test_base_dir <- "."

test_that("make_paths creates the expected directory layout", {
  paths <- make_paths(test_base_dir)

  expect_equal(paths$base_dir, ".")
  expect_equal(paths$output_dir, file.path(".", "data"))
  expect_equal(paths$yearly_output_dir, file.path(".", "data", "edition_raw_data_by_year"))
})

test_that("get_start_year returns first_year if no yearly files exist", {
  tmp_dir <- file.path(tempdir(), "empty_year_dir")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)

  expect_equal(get_start_year(tmp_dir, first_year = 1454), 1454)
})

test_that("get_start_year returns the maximum existing year", {
  yearly_dir <- file.path("data", "edition_raw_data_by_year")
  dir.create(yearly_dir, recursive = TRUE, showWarnings = FALSE)

  expect_equal(get_start_year(yearly_dir, first_year = 1454), 1455)
})

test_that("build_bnf_edition_query includes the requested year", {
  q <- build_bnf_edition_query(1454)

  expect_match(q, "FILTER\\(\\?year_first = 1454\\)")
  expect_match(q, "SELECT DISTINCT")
  expect_match(q, "\\?edition")
  expect_match(q, "\\?author")
})

test_that("compile_edition_data merges yearly CSV fixtures", {
  yearly_dir <- file.path("data", "edition_raw_data_by_year")
  compiled <- compile_edition_data(yearly_dir)

  expect_true(nrow(compiled) >= 2)
  expect_true("edition" %in% colnames(compiled))
  expect_true("author" %in% colnames(compiled))
})

test_that("write_compiled_edition_data writes the compiled CSV", {
  tmp_base <- file.path(tempdir(), "query_editions_write_compiled")
  paths <- make_paths(tmp_base)
  ensure_output_dirs(paths)

  compiled <- data.frame(
    edition = c("http://example.org/edition/1454", "http://example.org/edition/1455"),
    author = c("http://example.org/actor/1454", "http://example.org/actor/1455"),
    stringsAsFactors = FALSE
  )

  out_file <- write_compiled_edition_data(compiled, paths$output_dir)

  expect_true(file.exists(out_file))
  expect_equal(basename(out_file), "bnf_edition_data_raw.csv")
})

test_that("compute_edition_stats returns the expected named list", {
  yearly_dir <- file.path("data", "edition_raw_data_by_year")
  compiled <- compile_edition_data(yearly_dir)
  stats <- compute_edition_stats(compiled)

  expect_true(is.list(stats))
  expect_true("n_unique_editions" %in% names(stats))
  expect_true("n_with_place_information" %in% names(stats))
  expect_true("n_with_record_type_information" %in% names(stats))
  expect_true("n_with_author_information" %in% names(stats))
  expect_true("n_with_language_information" %in% names(stats))
})

test_that("get_bnf_edition_data writes a yearly CSV using a mock query function", {
  tmp_base <- file.path(tempdir(), "query_editions_test")
  paths <- make_paths(tmp_base)
  ensure_output_dirs(paths)

  mock_query_fun <- function(query) {
    data.frame(
      edition = "http://example.org/edition/1",
      bnf_id = "12345",
      title = "Test title",
      year_first = "1454",
      year_range = "1454",
      description = "Test description",
      place = "Paris",
      publisher = "Test publisher",
      work = "http://example.org/work/1",
      digital_copy_link = "http://example.org/digital/1",
      subject_topic = "Topic",
      expression = "http://example.org/expression/1",
      language = "fr",
      record_type = "type1",
      author = "http://example.org/actor/1",
      editor = "",
      translator = "",
      publisher_2 = "",
      illustrator = "",
      stringsAsFactors = FALSE
    )
  }

  out_file <- get_bnf_edition_data(
    year = 1454,
    yearly_output_dir = paths$yearly_output_dir,
    query_fun = mock_query_fun,
    sleep = FALSE
  )

  expect_true(file.exists(out_file))
})

test_that("load_monitor_env loads a monitor script into an environment", {
  tmp_dir <- file.path(tempdir(), "query_editions_monitor_loader")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)

  monitor_script <- file.path(tmp_dir, "mock_monitor.R")

  writeLines(
    c(
      'start_monitor_state <- function(sampling_mode = NULL, print_start_message = TRUE) {',
      '  list(report_path = "mock_report.txt", closed = FALSE, cycle = 0)',
      '}',
      'update_monitor_state <- function(state, context = NULL, print_console = TRUE) {',
      '  state$cycle <- state$cycle + 1',
      '  state',
      '}',
      'stop_monitor_state <- function(state, print_stop_message = TRUE) {',
      '  state$closed <- TRUE',
      '  state',
      '}'
    ),
    monitor_script
  )

  env <- load_monitor_env(monitor_script)

  expect_true(is.environment(env))
  expect_true(exists("start_monitor_state", envir = env, inherits = FALSE))
  expect_true(exists("update_monitor_state", envir = env, inherits = FALSE))
  expect_true(exists("stop_monitor_state", envir = env, inherits = FALSE))
})

test_that("run_query_editions performs an end-to-end run with mocked queries", {
  tmp_base <- file.path(tempdir(), "query_editions_e2e")

  mock_query_fun <- function(query) {
    year <- sub(".*FILTER\\(\\?year_first = ([0-9]{4})\\).*", "\\1", query)
    data.frame(
      edition = paste0("http://example.org/edition/", year),
      bnf_id = paste0("id_", year),
      title = paste("Title", year),
      year_first = year,
      year_range = year,
      description = paste("Description", year),
      place = "Paris",
      publisher = "Publisher",
      work = paste0("http://example.org/work/", year),
      digital_copy_link = paste0("http://example.org/digital/", year),
      subject_topic = "Topic",
      expression = paste0("http://example.org/expression/", year),
      language = "fr",
      record_type = "type1",
      author = paste0("http://example.org/actor/", year),
      editor = "",
      translator = "",
      publisher_2 = "",
      illustrator = "",
      stringsAsFactors = FALSE
    )
  }

  result <- run_query_editions(
    base_dir = tmp_base,
    first_year = 1454,
    last_year = 1455,
    query_fun = mock_query_fun,
    sleep = FALSE,
    write_session_info = TRUE
  )

  expect_true(file.exists(file.path(tmp_base, "data", "bnf_edition_data_raw.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "edition_raw_data_by_year", "raw_edition_data_for_the_year_1454.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "edition_raw_data_by_year", "raw_edition_data_for_the_year_1455.csv")))

  session_files <- list.files(
    file.path(tmp_base, "data"),
    pattern = "^sessionInfo_of_the_bnf_data_acquisition_run_of_.*\\.txt$"
  )
  expect_true(length(session_files) == 1)

  expect_equal(result$start_year, 1454)
  expect_true(nrow(result$data) == 2)
  expect_true(result$stats$n_unique_editions == 2)
  expect_null(result$monitor_report)
})

test_that("run_query_editions can use the embedded monitor API", {
  tmp_base <- file.path(tempdir(), "query_editions_e2e_monitor")

  monitor_dir <- file.path(tmp_base, "monitor")
  dir.create(monitor_dir, recursive = TRUE, showWarnings = FALSE)
  monitor_script <- file.path(monitor_dir, "mock_monitor.R")
  monitor_log <- file.path(monitor_dir, "monitor_calls.txt")
  monitor_report <- file.path(monitor_dir, "mock_report.txt")

  writeLines(
    c(
      sprintf('monitor_log_path <- "%s"', gsub("\\\\", "/", monitor_log)),
      sprintf('monitor_report_path <- "%s"', gsub("\\\\", "/", monitor_report)),
      '',
      'start_monitor_state <- function(sampling_mode = NULL, print_start_message = TRUE) {',
      '  cat("start\\n", file = monitor_log_path, append = TRUE)',
      '  list(report_path = monitor_report_path, closed = FALSE, cycle = 0)',
      '}',
      'update_monitor_state <- function(state, context = NULL, print_console = TRUE) {',
      '  cat(paste0("update:", state$cycle + 1, "\\n"), file = monitor_log_path, append = TRUE)',
      '  state$cycle <- state$cycle + 1',
      '  state',
      '}',
      'stop_monitor_state <- function(state, print_stop_message = TRUE) {',
      '  cat("stop\\n", file = monitor_log_path, append = TRUE)',
      '  file.create(state$report_path)',
      '  state$closed <- TRUE',
      '  state',
      '}'
    ),
    monitor_script
  )

  mock_query_fun <- function(query) {
    year <- sub(".*FILTER\\(\\?year_first = ([0-9]{4})\\).*", "\\1", query)
    data.frame(
      edition = paste0("http://example.org/edition/", year),
      bnf_id = paste0("id_", year),
      title = paste("Title", year),
      year_first = year,
      year_range = year,
      description = paste("Description", year),
      place = "Paris",
      publisher = "Publisher",
      work = paste0("http://example.org/work/", year),
      digital_copy_link = paste0("http://example.org/digital/", year),
      subject_topic = "Topic",
      expression = paste0("http://example.org/expression/", year),
      language = "fr",
      record_type = "type1",
      author = paste0("http://example.org/actor/", year),
      editor = "",
      translator = "",
      publisher_2 = "",
      illustrator = "",
      stringsAsFactors = FALSE
    )
  }

  result <- run_query_editions(
    base_dir = tmp_base,
    first_year = 1454,
    last_year = 1455,
    query_fun = mock_query_fun,
    sleep = FALSE,
    write_session_info = FALSE,
    use_monitor = TRUE,
    monitor_script = monitor_script
  )

  expect_true(file.exists(file.path(tmp_base, "data", "bnf_edition_data_raw.csv")))
  expect_true(file.exists(result$monitor_report))
  expect_equal(normalizePath(result$monitor_report), normalizePath(monitor_report))

  log_lines <- readLines(monitor_log, warn = FALSE)
  expect_true("start" %in% log_lines)
  expect_true("stop" %in% log_lines)
  expect_equal(sum(grepl("^update:", log_lines)), 3)
})