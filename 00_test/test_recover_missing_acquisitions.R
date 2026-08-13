# 00_test/test_recover_missing_acquisitions.R

library(testthat)

script_path <- normalizePath(
  file.path("..", "01_data_retrieval", "recover_missing_acquisitions.R"),
  mustWork = TRUE
)

# recover_missing_acquisitions.R loads query_editions.R and query_agents.R via
# sys.source(..., envir = globalenv()) - hardcoded, see its header comment -
# so their functions are directly callable from run_recovery() and friends.
# That means, unlike test_query_editions.R's isolated test_env, this file's
# top-level library(SPARQL) call runs against the real global environment
# once sourced. Shim library() there just long enough to source the script,
# so tests do not require the archived {SPARQL} package to be installed,
# then remove the shim immediately after - mirrors the same trick in
# test_query_editions.R, just applied to globalenv() instead of a local env.
.real_library <- base::library

assign(
  "library",
  function(package, ..., character.only = FALSE, logical.return = FALSE,
           warn.conflicts = TRUE, quietly = FALSE, verbose = getOption("verbose")) {
    pkg_name <- if (character.only) package else deparse(substitute(package))

    if (identical(pkg_name, "SPARQL")) {
      return(invisible(TRUE))
    }

    .real_library(
      pkg_name, ...,
      character.only = TRUE, logical.return = logical.return,
      warn.conflicts = warn.conflicts, quietly = quietly, verbose = verbose
    )
  },
  envir = globalenv()
)

# recover_missing_acquisitions.R's own sys.source() calls use paths relative
# to "01_data_retrieval/..." (project root), matching every other path
# convention in this codebase (see 01_data_retrieval/README.md: "must be run
# from the project root directory"). testthat::test_file() runs with the
# working directory set to 00_test/, so cwd is switched to the project root
# just for the duration of this source() call, then restored - every
# test_that() block below uses only tempdir()-based or already-resolved
# fixture paths, so it does not depend on which of the two is active.
.orig_wd <- getwd()
setwd(normalizePath(".."))
tryCatch(source(script_path), finally = setwd(.orig_wd))

rm(list = "library", envir = globalenv())

test_base_dir <- "."

# ---------------------------------------------------------------------------
# find_missing_edition_years
# ---------------------------------------------------------------------------

test_that("find_missing_edition_years finds gaps in a yearly output directory", {
  tmp_dir <- file.path(tempdir(), "recover_missing_years")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  for (y in c(1454, 1455, 1457)) {
    file.create(file.path(tmp_dir, sprintf("raw_edition_data_for_the_year_%d.csv", y)))
  }

  missing <- find_missing_edition_years(tmp_dir, first_year = 1454, last_year = 1457)

  expect_equal(missing, 1456L)
})

test_that("find_missing_edition_years returns an empty vector when nothing is missing", {
  yearly_dir <- file.path("data", "edition_raw_data_by_year")

  missing <- find_missing_edition_years(yearly_dir, first_year = 1454, last_year = 1455)

  expect_equal(missing, integer(0))
})

test_that("find_missing_edition_years ignores files that do not match the year pattern", {
  tmp_dir <- file.path(tempdir(), "recover_missing_years_malformed")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  file.create(file.path(tmp_dir, "not_a_year_file.csv"))

  missing <- find_missing_edition_years(tmp_dir, first_year = 1, last_year = 2)

  expect_equal(missing, c(1L, 2L))
})

# ---------------------------------------------------------------------------
# find_context_indices
# ---------------------------------------------------------------------------

test_that("find_context_indices extracts indices from matching report files", {
  tmp_dir <- file.path(tempdir(), "recover_context_indices")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  writeLines(
    c(
      "  Context: Completed acquisition for actor index 10 - <actor10>",
      "  Context: Failed acquisition for actor index 42 - <actor42>",
      "  Context: Failed acquisition for actor index 7 - <actor7>"
    ),
    file.path(tmp_dir, "query_agents_20260101_000000_R.txt")
  )
  writeLines(
    "  Context: Failed acquisition for actor index 42 - <actor42>",
    file.path(tmp_dir, "query_agents_20260102_000000_R.txt")
  )
  writeLines(
    "  Context: RECOVERED actor index 999 - <actor999> via recover_missing_acquisitions",
    file.path(tmp_dir, "recover_missing_acquisitions_20260103_000000_R.txt")
  )

  failed <- find_context_indices(
    tmp_dir, "^query_agents_.*_R\\.txt$",
    "Failed acquisition for actor index ([0-9]+)"
  )

  expect_equal(failed, c(7L, 42L))  # sorted, de-duplicated across files

  recovered <- find_context_indices(
    tmp_dir, "^recover_missing_acquisitions_.*_R\\.txt$",
    "RECOVERED actor index ([0-9]+)"
  )

  expect_equal(recovered, 999L)
})

test_that("find_context_indices returns an empty vector when the report directory does not exist", {
  result <- find_context_indices(
    file.path(tempdir(), "does_not_exist_dir"),
    "^query_agents_.*_R\\.txt$",
    "Failed acquisition for actor index ([0-9]+)"
  )

  expect_equal(result, integer(0))
})

test_that("find_context_indices returns an empty vector when no file matches the pattern", {
  tmp_dir <- file.path(tempdir(), "recover_context_indices_empty")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  writeLines("nothing relevant here", file.path(tmp_dir, "unrelated.txt"))

  result <- find_context_indices(tmp_dir, "^query_agents_.*_R\\.txt$", "Failed acquisition for actor index ([0-9]+)")

  expect_equal(result, integer(0))
})

# ---------------------------------------------------------------------------
# sync_actor_cache_append_only
# ---------------------------------------------------------------------------

test_that("sync_actor_cache_append_only appends new actors without disturbing existing rows", {
  tmp_dir <- file.path(tempdir(), "recover_sync_cache")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  write.csv(data.frame(actor = c("<a1>", "<a2>")), file.path(tmp_dir, "distinct_actors_cache.csv"), row.names = FALSE)

  editions_input <- file.path(tmp_dir, "fake_editions.csv")
  write.csv(
    data.frame(
      author = c("<a2>", "<a3>"),
      editor = c("<a1>", "<a4>"),
      illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_
    ),
    editions_input, row.names = FALSE
  )

  result <- sync_actor_cache_append_only(editions_input, tmp_dir)

  expect_equal(result$cache$actor[1:2], c("<a1>", "<a2>"))  # untouched, original order/index
  expect_equal(result$new_indices, c(3L, 4L))
  expect_setequal(result$cache$actor[result$new_indices], c("<a3>", "<a4>"))

  on_disk <- read.csv(file.path(tmp_dir, "distinct_actors_cache.csv"), stringsAsFactors = FALSE)
  expect_equal(on_disk$actor, result$cache$actor)
})

test_that("sync_actor_cache_append_only is a no-op when no new actors are found", {
  tmp_dir <- file.path(tempdir(), "recover_sync_cache_noop")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  write.csv(data.frame(actor = c("<a1>", "<a2>")), file.path(tmp_dir, "distinct_actors_cache.csv"), row.names = FALSE)

  editions_input <- file.path(tmp_dir, "fake_editions.csv")
  write.csv(
    data.frame(author = "<a1>", editor = "<a2>", illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    editions_input, row.names = FALSE
  )

  result <- sync_actor_cache_append_only(editions_input, tmp_dir)

  expect_equal(result$new_indices, integer(0))
  expect_equal(result$cache$actor, c("<a1>", "<a2>"))
})

test_that("sync_actor_cache_append_only creates the cache from scratch when it does not exist yet", {
  tmp_dir <- file.path(tempdir(), "recover_sync_cache_fresh")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  editions_input <- file.path(tmp_dir, "fake_editions.csv")
  write.csv(
    data.frame(author = "<a1>", editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    editions_input, row.names = FALSE
  )

  result <- sync_actor_cache_append_only(editions_input, tmp_dir)

  expect_equal(result$new_indices, 1L)
  expect_equal(result$cache$actor, "<a1>")
})

# ---------------------------------------------------------------------------
# log_actor_cache_additions
# ---------------------------------------------------------------------------

test_that("log_actor_cache_additions writes a header on first write and appends without duplicating it", {
  tmp_dir <- file.path(tempdir(), "recover_additions_log")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  cache <- data.frame(actor = c("<a1>", "<a2>", "<a3>"), stringsAsFactors = FALSE)

  log_actor_cache_additions(tmp_dir, new_indices = 3L, cache = cache, script_label = "recover_missing_acquisitions", source_note = "edition year recovery: 1512")
  log_actor_cache_additions(tmp_dir, new_indices = integer(0), cache = cache, script_label = "recover_missing_acquisitions", source_note = "no-op call")

  log_path <- file.path(tmp_dir, "actor_cache_additions_log.csv")
  content <- readLines(log_path)

  expect_equal(length(content), 2)  # header + exactly one data row, the no-op call added nothing
  expect_true(grepl('^"actor_index","actor","added_at","added_via","source"$', content[1]))

  log_df <- read.csv(log_path, stringsAsFactors = FALSE)
  expect_equal(log_df$actor_index, 3)
  expect_equal(log_df$actor, "<a3>")
  expect_equal(log_df$added_via, "recover_missing_acquisitions")
})

test_that("log_actor_cache_additions appends further rows without rewriting the header", {
  tmp_dir <- file.path(tempdir(), "recover_additions_log_append")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  cache <- data.frame(actor = c("<a1>", "<a2>", "<a3>", "<a4>"), stringsAsFactors = FALSE)

  log_actor_cache_additions(tmp_dir, new_indices = 3L, cache = cache, script_label = "recover_missing_acquisitions", source_note = "batch 1")
  log_actor_cache_additions(tmp_dir, new_indices = 4L, cache = cache, script_label = "recover_missing_acquisitions", source_note = "batch 2")

  log_df <- read.csv(file.path(tmp_dir, "actor_cache_additions_log.csv"), stringsAsFactors = FALSE)

  expect_equal(nrow(log_df), 2)
  expect_equal(log_df$actor, c("<a3>", "<a4>"))
})

# ---------------------------------------------------------------------------
# recover_missing_edition_years
# ---------------------------------------------------------------------------

test_that("recover_missing_edition_years recovers a year on the first attempt", {
  tmp_dir <- file.path(tempdir(), "recover_edition_years_ok")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  mock_query_fun <- function(query) data.frame(edition = "http://example.org/edition/1454")

  contexts <- character(0)
  checkpoint <- function(context) contexts <<- c(contexts, context)

  result <- recover_missing_edition_years(
    missing_years = 1454, yearly_output_dir = tmp_dir, query_fun = mock_query_fun,
    sleep = FALSE, max_attempts = 3, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = checkpoint
  )

  expect_equal(result$recovered, 1454)
  expect_equal(result$still_missing, integer(0))
  expect_true(file.exists(file.path(tmp_dir, "raw_edition_data_for_the_year_1454.csv")))
  expect_true(any(grepl("^RECOVERED edition year 1454", contexts)))
})

test_that("recover_missing_edition_years retries and eventually succeeds", {
  tmp_dir <- file.path(tempdir(), "recover_edition_years_retry")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  attempt_count <- 0
  mock_query_fun <- function(query) {
    attempt_count <<- attempt_count + 1
    if (attempt_count < 2) stop("simulated transient failure")
    data.frame(edition = "http://example.org/edition/1454")
  }

  result <- recover_missing_edition_years(
    missing_years = 1454, yearly_output_dir = tmp_dir, query_fun = mock_query_fun,
    sleep = FALSE, max_attempts = 3, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = function(context) invisible(NULL)
  )

  expect_equal(result$recovered, 1454)
  expect_equal(attempt_count, 2)
})

test_that("recover_missing_edition_years reports still_missing after exhausting retries", {
  tmp_dir <- file.path(tempdir(), "recover_edition_years_fail")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  mock_query_fun <- function(query) stop("simulated permanent failure")

  contexts <- character(0)
  checkpoint <- function(context) contexts <<- c(contexts, context)

  result <- recover_missing_edition_years(
    missing_years = 1454, yearly_output_dir = tmp_dir, query_fun = mock_query_fun,
    sleep = FALSE, max_attempts = 2, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = checkpoint
  )

  expect_equal(result$recovered, integer(0))
  expect_equal(result$still_missing, 1454)
  expect_false(file.exists(file.path(tmp_dir, "raw_edition_data_for_the_year_1454.csv")))
  expect_true(any(grepl("^RECOVERY FAILED for edition year 1454.*after 2 attempt\\(s\\)", contexts)))
})

# ---------------------------------------------------------------------------
# recover_missing_actor_indices
# ---------------------------------------------------------------------------

test_that("recover_missing_actor_indices recovers a previously-failed index and labels it as such", {
  tmp_dir <- file.path(tempdir(), "recover_actor_indices_ok")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  actors_df <- data.frame(actor = c("<a1>", "<a2>"), stringsAsFactors = FALSE)
  mock_query_fun <- function(query) data.frame(actor_name = "Test")

  contexts <- character(0)
  checkpoint <- function(context) contexts <<- c(contexts, context)

  result <- recover_missing_actor_indices(
    indices = 2, actors_df = actors_df, intermediate_output_dir = tmp_dir,
    query_fun = mock_query_fun, sleep = FALSE, max_attempts = 3, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = checkpoint
  )

  expect_equal(result$recovered, 2)
  expect_true(file.exists(file.path(tmp_dir, "actor_file_2.csv")))
  expect_true(any(grepl("^RECOVERED actor index 2 - <a2> \\(previously failed\\)", contexts)))
})

test_that("recover_missing_actor_indices labels a new index as such, not as previously failed", {
  tmp_dir <- file.path(tempdir(), "recover_actor_indices_new")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  actors_df <- data.frame(actor = c("<a1>", "<a2>"), stringsAsFactors = FALSE)
  mock_query_fun <- function(query) data.frame(actor_name = "Test")

  contexts <- character(0)
  checkpoint <- function(context) contexts <<- c(contexts, context)

  result <- recover_missing_actor_indices(
    indices = 2, actors_df = actors_df, intermediate_output_dir = tmp_dir,
    query_fun = mock_query_fun, sleep = FALSE, max_attempts = 3, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = checkpoint,
    new_indices = 2
  )

  expect_equal(result$recovered, 2)
  expect_true(any(grepl("new actor introduced by recovered edition year\\(s\\)", contexts)))
  expect_false(any(grepl("previously failed", contexts)))
})

test_that("recover_missing_actor_indices skips re-querying when a CSV already exists", {
  tmp_dir <- file.path(tempdir(), "recover_actor_indices_existing")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  write.csv(data.frame(actor = "<a2>", actor_name = "Already there"), file.path(tmp_dir, "actor_file_2.csv"), row.names = FALSE)

  actors_df <- data.frame(actor = c("<a1>", "<a2>"), stringsAsFactors = FALSE)
  query_called <- FALSE
  mock_query_fun <- function(query) {
    query_called <<- TRUE
    data.frame(actor_name = "Should not be called")
  }

  result <- recover_missing_actor_indices(
    indices = 2, actors_df = actors_df, intermediate_output_dir = tmp_dir,
    query_fun = mock_query_fun, sleep = FALSE, max_attempts = 3, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = function(context) invisible(NULL)
  )

  expect_equal(result$recovered, 2)
  expect_false(query_called)
})

test_that("recover_missing_actor_indices reports still_failing after exhausting retries", {
  tmp_dir <- file.path(tempdir(), "recover_actor_indices_fail")
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)

  actors_df <- data.frame(actor = "<a1>", stringsAsFactors = FALSE)
  mock_query_fun <- function(query) stop("simulated permanent failure")

  result <- recover_missing_actor_indices(
    indices = 1, actors_df = actors_df, intermediate_output_dir = tmp_dir,
    query_fun = mock_query_fun, sleep = FALSE, max_attempts = 2, retry_delay_seconds = 0,
    script_label = "recover_missing_acquisitions", checkpoint = function(context) invisible(NULL)
  )

  expect_equal(result$still_failing, 1)
  expect_equal(result$recovered, integer(0))
  expect_false(file.exists(file.path(tmp_dir, "actor_file_1.csv")))
})

# ---------------------------------------------------------------------------
# run_recovery: end-to-end
# ---------------------------------------------------------------------------

test_that("run_recovery recovers a missing edition year, extends the actor cache, and recovers actors end-to-end", {
  root <- file.path(tempdir(), "run_recovery_e2e")
  unlink(root, recursive = TRUE)

  editions_base_dir <- file.path(root, "editions")
  actors_base_dir <- file.path(root, "actors")
  report_dir <- file.path(root, "report")

  dir.create(file.path(editions_base_dir, "data", "edition_raw_data_by_year"), recursive = TRUE)
  dir.create(file.path(actors_base_dir, "data", "actor_queries_results"), recursive = TRUE)
  dir.create(report_dir, recursive = TRUE)

  role_cols <- function(author) {
    data.frame(author = author, editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_, stringsAsFactors = FALSE)
  }

  # Years 1454-1455 exist; 1456 is missing (simulates an interrupted run).
  for (y in c(1454, 1455)) {
    write.csv(role_cols(sprintf("<actor_%d>", y)), file.path(editions_base_dir, "data", "edition_raw_data_by_year", sprintf("raw_edition_data_for_the_year_%d.csv", y)), row.names = FALSE)
  }

  editions_input <- file.path(editions_base_dir, "data", "bnf_edition_data_raw.csv")
  write.csv(do.call(rbind, lapply(c(1454, 1455), function(y) role_cols(sprintf("<actor_%d>", y)))), editions_input, row.names = FALSE)

  # Actor cache/state before recovery: actor_1454 already downloaded;
  # actor_1455 previously logged as a failed acquisition (no CSV).
  write.csv(data.frame(actor = c("<actor_1454>", "<actor_1455>")), file.path(actors_base_dir, "data", "distinct_actors_cache.csv"), row.names = FALSE)
  write.csv(data.frame(actor = "<actor_1454>", actor_name = "A"), file.path(actors_base_dir, "data", "actor_queries_results", "actor_file_1.csv"), row.names = FALSE)

  writeLines(
    c("Entry Script: query_agents", "  Context: Failed acquisition for actor index 2 - <actor_1455>"),
    file.path(report_dir, "query_agents_20260101_000000_R.txt")
  )

  fake_edition_query <- function(query) role_cols("<actor_1456>")
  fake_actor_query <- function(query) data.frame(actor_name = "Recovered")

  result <- run_recovery(
    editions_base_dir = editions_base_dir, actors_base_dir = actors_base_dir, editions_input = editions_input,
    first_year = 1454, last_year = 1456, report_dir = report_dir, use_monitor = FALSE,
    max_attempts = 2, retry_delay_seconds = 0,
    edition_query_fun = fake_edition_query, actor_query_fun = fake_actor_query, sleep = FALSE
  )

  expect_equal(result$missing_years, 1456)
  expect_equal(result$edition_recovery$recovered, 1456)
  expect_true(file.exists(file.path(editions_base_dir, "data", "edition_raw_data_by_year", "raw_edition_data_for_the_year_1456.csv")))

  # actor_1456, introduced only by the just-recovered year, must be appended
  # append-only (existing indices 1-2 untouched) ...
  updated_cache <- read.csv(file.path(actors_base_dir, "data", "distinct_actors_cache.csv"), stringsAsFactors = FALSE)
  expect_equal(updated_cache$actor[1:2], c("<actor_1454>", "<actor_1455>"))
  expect_equal(updated_cache$actor[3], "<actor_1456>")
  expect_equal(result$new_actor_indices, 3)

  # ... and traced in the additions ledger.
  ledger <- read.csv(file.path(actors_base_dir, "data", "actor_cache_additions_log.csv"), stringsAsFactors = FALSE)
  expect_equal(nrow(ledger), 1)
  expect_equal(ledger$actor, "<actor_1456>")
  expect_match(ledger$source, "1456")

  # Both the previously-failed actor (index 2) and the newly-introduced one
  # (index 3) must have been queried and recovered.
  expect_setequal(result$actor_recovery$recovered, c(2, 3))
  expect_true(file.exists(file.path(actors_base_dir, "data", "actor_queries_results", "actor_file_2.csv")))
  expect_true(file.exists(file.path(actors_base_dir, "data", "actor_queries_results", "actor_file_3.csv")))

  merged <- read.csv(file.path(actors_base_dir, "data", "actor_data.csv"), stringsAsFactors = FALSE)
  expect_equal(nrow(merged), 3)

  unlink(root, recursive = TRUE)
})

test_that("run_recovery is a cheap no-op when nothing was skipped", {
  root <- file.path(tempdir(), "run_recovery_noop")
  unlink(root, recursive = TRUE)

  editions_base_dir <- file.path(root, "editions")
  actors_base_dir <- file.path(root, "actors")
  report_dir <- file.path(root, "report")

  dir.create(file.path(editions_base_dir, "data", "edition_raw_data_by_year"), recursive = TRUE)
  dir.create(file.path(actors_base_dir, "data", "actor_queries_results"), recursive = TRUE)
  dir.create(report_dir, recursive = TRUE)

  write.csv(
    data.frame(author = "<actor_1454>", editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    file.path(editions_base_dir, "data", "edition_raw_data_by_year", "raw_edition_data_for_the_year_1454.csv"),
    row.names = FALSE
  )
  editions_input <- file.path(editions_base_dir, "data", "bnf_edition_data_raw.csv")
  write.csv(
    data.frame(author = "<actor_1454>", editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    editions_input, row.names = FALSE
  )

  write.csv(data.frame(actor = "<actor_1454>"), file.path(actors_base_dir, "data", "distinct_actors_cache.csv"), row.names = FALSE)
  write.csv(data.frame(actor = "<actor_1454>", actor_name = "A"), file.path(actors_base_dir, "data", "actor_queries_results", "actor_file_1.csv"), row.names = FALSE)

  query_called <- FALSE
  fail_if_called <- function(query) {
    query_called <<- TRUE
    stop("should not be called when there is nothing to recover")
  }

  result <- run_recovery(
    editions_base_dir = editions_base_dir, actors_base_dir = actors_base_dir, editions_input = editions_input,
    first_year = 1454, last_year = 1454, report_dir = report_dir, use_monitor = FALSE,
    edition_query_fun = fail_if_called, actor_query_fun = fail_if_called, sleep = FALSE
  )

  expect_false(query_called)
  expect_equal(result$missing_years, integer(0))
  expect_equal(result$new_actor_indices, integer(0))
  expect_equal(result$candidate_actor_indices, integer(0))
  expect_false(file.exists(file.path(actors_base_dir, "data", "actor_cache_additions_log.csv")))

  unlink(root, recursive = TRUE)
})

test_that("run_recovery does not re-recover an actor index already marked recovered in a previous report", {
  root <- file.path(tempdir(), "run_recovery_ledger")
  unlink(root, recursive = TRUE)

  editions_base_dir <- file.path(root, "editions")
  actors_base_dir <- file.path(root, "actors")
  report_dir <- file.path(root, "report")

  dir.create(file.path(editions_base_dir, "data", "edition_raw_data_by_year"), recursive = TRUE)
  dir.create(file.path(actors_base_dir, "data", "actor_queries_results"), recursive = TRUE)
  dir.create(report_dir, recursive = TRUE)

  write.csv(
    data.frame(author = "<actor_1454>", editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    file.path(editions_base_dir, "data", "edition_raw_data_by_year", "raw_edition_data_for_the_year_1454.csv"),
    row.names = FALSE
  )
  editions_input <- file.path(editions_base_dir, "data", "bnf_edition_data_raw.csv")
  write.csv(
    data.frame(author = "<actor_1454>", editor = NA_character_, illustrator = NA_character_, publisher_2 = NA_character_, translator = NA_character_),
    editions_input, row.names = FALSE
  )

  write.csv(data.frame(actor = "<actor_1454>"), file.path(actors_base_dir, "data", "distinct_actors_cache.csv"), row.names = FALSE)
  # No actor_file_1.csv - a legitimate zero-result actor from a previous recovery.

  writeLines(
    c("Entry Script: query_agents", "  Context: Failed acquisition for actor index 1 - <actor_1454>"),
    file.path(report_dir, "query_agents_20260101_000000_R.txt")
  )
  writeLines(
    c("Entry Script: recover_missing_acquisitions", "  Context: RECOVERED actor index 1 - <actor_1454> (previously failed, file already present, no re-query needed) via recover_missing_acquisitions"),
    file.path(report_dir, "recover_missing_acquisitions_20260102_000000_R.txt")
  )

  query_called <- FALSE
  fail_if_called <- function(query) {
    query_called <<- TRUE
    stop("should not be called - index 1 is already marked recovered")
  }

  result <- run_recovery(
    editions_base_dir = editions_base_dir, actors_base_dir = actors_base_dir, editions_input = editions_input,
    first_year = 1454, last_year = 1454, report_dir = report_dir, use_monitor = FALSE,
    edition_query_fun = fail_if_called, actor_query_fun = fail_if_called, sleep = FALSE
  )

  expect_false(query_called)
  expect_equal(result$candidate_actor_indices, integer(0))

  unlink(root, recursive = TRUE)
})
