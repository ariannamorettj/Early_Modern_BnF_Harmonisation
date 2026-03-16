# 00_test/test_query_actors.R

library(testthat)

script_path <- normalizePath(
  file.path("..", "01_data_retrieval", "02_actors", "query_agents.R"),
  mustWork = TRUE
)

source(script_path)

test_base_dir <- "."

test_that("make_actor_paths creates the expected directory layout", {
  paths <- make_actor_paths(
    base_dir = test_base_dir,
    editions_input = file.path("data", "actors_data", "bnf_edition_data_raw.csv")
  )

  expect_equal(paths$base_dir, ".")
  expect_equal(paths$output_dir, file.path(".", "data"))
  expect_equal(paths$intermediate_output_dir, file.path(".", "data", "actor_queries_results"))
  expect_equal(paths$editions_input, file.path("data", "actors_data", "bnf_edition_data_raw.csv"))
  expect_equal(paths$progress_file, file.path(".", "data", "last_processed_index.txt"))
})

test_that("get_start_index returns 1 when progress file does not exist", {
  missing_file <- file.path(tempdir(), "missing_progress.txt")
  expect_equal(get_start_index(missing_file), 1)
})

test_that("get_start_index returns the next index when progress file exists", {
  progress_file <- file.path(tempdir(), "progress_valid.txt")
  writeLines("7", progress_file)

  expect_equal(get_start_index(progress_file), 8)
})

test_that("get_start_index returns 1 when progress file is invalid", {
  progress_file <- file.path(tempdir(), "progress_invalid.txt")
  writeLines("not_an_integer", progress_file)

  expect_equal(get_start_index(progress_file), 1)
})

test_that("build_actor_query includes the actor and expected variables", {
  q <- build_actor_query("<http://example.org/actor/1>")

  expect_match(q, "http://example.org/actor/1")
  expect_match(q, "SELECT DISTINCT")
  expect_match(q, "\\?actor_name")
  expect_match(q, "\\?actor_link_exact")
})

test_that("read_editions_input loads the fixture file", {
  editions_df <- read_editions_input(file.path("data", "actors_data", "bnf_edition_data_raw.csv"))

  expect_true(is.data.frame(editions_df))
  expect_true("author" %in% colnames(editions_df))
})

test_that("extract_distinct_actors returns unique non-empty actors", {
  editions_df <- read_editions_input(file.path("data", "actors_data", "bnf_edition_data_raw.csv"))
  actors_df <- extract_distinct_actors(editions_df)

  expect_true(is.data.frame(actors_df))
  expect_true("actor" %in% colnames(actors_df))
  expect_equal(nrow(actors_df), 2)
  expect_true(all(actors_df$actor != ""))
})

test_that("get_bnf_data_for_actor writes an intermediate CSV using a mock query function", {
  tmp_base <- file.path(tempdir(), "query_agents_single")
  paths <- make_actor_paths(
    base_dir = tmp_base,
    editions_input = file.path("data", "actors_data", "bnf_edition_data_raw.csv")
  )
  ensure_actor_output_dirs(paths)

  mock_query_fun <- function(query) {
    data.frame(
      actor_birth = "1700",
      actor_name = "Test Actor",
      actor_first_name = "Test",
      actor_last_name = "Actor",
      entity_type = "Person",
      first_year = "1720",
      actor_country = "France",
      actor_language = "fr",
      actor_gender = "unknown",
      actor_profession = "Writer",
      actor_death = "1760",
      actor_start = "1720",
      actor_end = "1760",
      actor_link_exact = "http://example.org/exact/1",
      actor_link_close = "http://example.org/close/1",
      stringsAsFactors = FALSE
    )
  }

  result <- get_bnf_data_for_actor(
    actor = "<http://example.org/actor/1>",
    file_name = "actor_file_1",
    intermediate_output_dir = paths$intermediate_output_dir,
    query_fun = mock_query_fun,
    sleep = FALSE
  )

  expect_true(isTRUE(result))
  expect_true(file.exists(file.path(paths$intermediate_output_dir, "actor_file_1.csv")))
})

test_that("merge_actor_csvs merges all intermediate actor CSVs", {
  tmp_base <- file.path(tempdir(), "query_agents_merge")
  paths <- make_actor_paths(
    base_dir = tmp_base,
    editions_input = file.path("data", "actors_data", "bnf_edition_data_raw.csv")
  )
  ensure_actor_output_dirs(paths)

  df1 <- data.frame(
    actor = "<http://example.org/actor/1>",
    actor_name = "Actor One",
    stringsAsFactors = FALSE
  )

  df2 <- data.frame(
    actor = "<http://example.org/actor/2>",
    actor_name = "Actor Two",
    stringsAsFactors = FALSE
  )

  write.csv(df1, file.path(paths$intermediate_output_dir, "actor_file_1.csv"), row.names = FALSE)
  write.csv(df2, file.path(paths$intermediate_output_dir, "actor_file_2.csv"), row.names = FALSE)

  merged <- merge_actor_csvs(paths$intermediate_output_dir, paths$output_dir)

  expect_true(file.exists(file.path(paths$output_dir, "actor_data.csv")))
  expect_equal(nrow(merged$data), 2)
})

test_that("load_monitor_env loads a monitor script into an environment", {
  tmp_dir <- file.path(tempdir(), "query_agents_monitor_loader")
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

test_that("run_query_agents performs an end-to-end full run with mocked queries", {
  tmp_base <- file.path(tempdir(), "query_agents_e2e_full")
  editions_input <- normalizePath(
    file.path("data", "actors_data", "bnf_edition_data_raw.csv"),
    mustWork = TRUE
  )

  call_count <- 0

  mock_query_fun <- function(query) {
    call_count <<- call_count + 1
    data.frame(
      actor_birth = "1700",
      actor_name = paste("Actor", call_count),
      actor_first_name = "Test",
      actor_last_name = as.character(call_count),
      entity_type = "Person",
      first_year = "1720",
      actor_country = "France",
      actor_language = "fr",
      actor_gender = "unknown",
      actor_profession = "Writer",
      actor_death = "1760",
      actor_start = "1720",
      actor_end = "1760",
      actor_link_exact = paste0("http://example.org/exact/", call_count),
      actor_link_close = paste0("http://example.org/close/", call_count),
      stringsAsFactors = FALSE
    )
  }

  result <- run_query_agents(
    base_dir = tmp_base,
    editions_input = editions_input,
    query_fun = mock_query_fun,
    sleep = FALSE
  )

  expect_true(file.exists(file.path(tmp_base, "data", "actor_data.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "actor_queries_results", "actor_file_1.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "actor_queries_results", "actor_file_2.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "last_processed_index.txt")))

  expect_equal(result$start_index, 1)
  expect_equal(nrow(result$actors), 2)
  expect_equal(nrow(result$data), 2)
  expect_null(result$monitor_report)
})

test_that("run_query_agents resumes automatically from the next actor index", {
  tmp_base <- file.path(tempdir(), "query_agents_e2e_resume")
  editions_input <- normalizePath(
    file.path("data", "actors_data", "bnf_edition_data_raw.csv"),
    mustWork = TRUE
  )

  paths <- make_actor_paths(base_dir = tmp_base, editions_input = editions_input)
  ensure_actor_output_dirs(paths)

  existing_df <- data.frame(
    actor = "<http://example.org/actor/1>",
    actor_birth = "1700",
    actor_name = "Actor One",
    actor_first_name = "Actor",
    actor_last_name = "One",
    entity_type = "Person",
    first_year = "1720",
    actor_country = "France",
    actor_language = "fr",
    actor_gender = "unknown",
    actor_profession = "Writer",
    actor_death = "1760",
    actor_start = "1720",
    actor_end = "1760",
    actor_link_exact = "http://example.org/exact/1",
    actor_link_close = "http://example.org/close/1",
    stringsAsFactors = FALSE
  )

  write.csv(
    existing_df,
    file.path(paths$intermediate_output_dir, "actor_file_1.csv"),
    row.names = FALSE
  )

  writeLines("1", paths$progress_file)

  mock_query_fun <- function(query) {
    data.frame(
      actor_birth = "1710",
      actor_name = "Actor Two",
      actor_first_name = "Actor",
      actor_last_name = "Two",
      entity_type = "Person",
      first_year = "1730",
      actor_country = "Italy",
      actor_language = "it",
      actor_gender = "unknown",
      actor_profession = "Translator",
      actor_death = "1770",
      actor_start = "1730",
      actor_end = "1770",
      actor_link_exact = "http://example.org/exact/2",
      actor_link_close = "http://example.org/close/2",
      stringsAsFactors = FALSE
    )
  }

  result <- run_query_agents(
    base_dir = tmp_base,
    editions_input = editions_input,
    query_fun = mock_query_fun,
    sleep = FALSE
  )

  expect_equal(result$start_index, 2)
  expect_true(file.exists(file.path(tmp_base, "data", "actor_queries_results", "actor_file_2.csv")))
  expect_true(file.exists(file.path(tmp_base, "data", "actor_data.csv")))
  expect_equal(nrow(result$data), 2)
  expect_equal(readLines(file.path(tmp_base, "data", "last_processed_index.txt"), warn = FALSE), "2")
  expect_null(result$monitor_report)
})

test_that("run_query_agents can use the embedded monitor API", {
  tmp_base <- file.path(tempdir(), "query_agents_e2e_monitor")
  editions_input <- normalizePath(
    file.path("data", "actors_data", "bnf_edition_data_raw.csv"),
    mustWork = TRUE
  )

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
      '  write("start", file = monitor_log_path, append = TRUE)',
      '  list(report_path = monitor_report_path, closed = FALSE, cycle = 0)',
      '}',
      'update_monitor_state <- function(state, context = NULL, print_console = TRUE) {',
      '  write(paste0("update:", state$cycle + 1), file = monitor_log_path, append = TRUE)',
      '  state$cycle <- state$cycle + 1',
      '  state',
      '}',
      'stop_monitor_state <- function(state, print_stop_message = TRUE) {',
      '  write("stop", file = monitor_log_path, append = TRUE)',
      '  file.create(state$report_path)',
      '  state$closed <- TRUE',
      '  state',
      '}'
    ),
    monitor_script
  )

  call_count <- 0

  mock_query_fun <- function(query) {
    call_count <<- call_count + 1
    data.frame(
      actor_birth = "1700",
      actor_name = paste("Actor", call_count),
      actor_first_name = "Test",
      actor_last_name = as.character(call_count),
      entity_type = "Person",
      first_year = "1720",
      actor_country = "France",
      actor_language = "fr",
      actor_gender = "unknown",
      actor_profession = "Writer",
      actor_death = "1760",
      actor_start = "1720",
      actor_end = "1760",
      actor_link_exact = paste0("http://example.org/exact/", call_count),
      actor_link_close = paste0("http://example.org/close/", call_count),
      stringsAsFactors = FALSE
    )
  }

  result <- run_query_agents(
    base_dir = tmp_base,
    editions_input = editions_input,
    query_fun = mock_query_fun,
    sleep = FALSE,
    use_monitor = TRUE,
    monitor_script = monitor_script
  )

  expect_true(file.exists(file.path(tmp_base, "data", "actor_data.csv")))
  expect_true(file.exists(result$monitor_report))
  expect_equal(normalizePath(result$monitor_report), normalizePath(monitor_report))

  log_lines <- readLines(monitor_log, warn = FALSE)
  expect_true("start" %in% log_lines)
  expect_true("stop" %in% log_lines)
  expect_equal(sum(grepl("^update:", log_lines)), 3)
})