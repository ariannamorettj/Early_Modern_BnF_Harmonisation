# 01_data_retrieval/recover_missing_acquisitions.R
#
# Precautionary third stage of the acquisition pipeline. Run this after both
# query_editions.R and query_agents.R have completed (or after either was
# interrupted and resumed) to detect and re-acquire anything that was
# silently skipped, then reflect what happened in the shared monitor report.
#
# Editions and actors need different detection strategies:
#
# - editions: get_bnf_edition_data() ALWAYS writes a yearly CSV, even when
#   the SPARQL result is empty, and the editions loop has no per-year
#   tryCatch (a query error crashes the whole Rscript, which
#   run_query_editions_batched.ps1 then retries at the block level). So a
#   missing yearly CSV file is unambiguous proof that the year was never
#   completed - simple file-existence gap detection is enough.
#
# - actors: get_bnf_data_for_actor() only writes a CSV when the SPARQL
#   result is non-empty (see query_agents.R), and the actor loop wraps each
#   query in tryCatch so a failure is swallowed and the loop moves on
#   without ever revisiting that index (see run_query_agents/get_start_index
#   in query_agents.R). A missing actor_file_N.csv is therefore NOT proof of
#   a skipped actor - it may just be a legitimate zero-result actor. The
#   only reliable signal is the "Failed acquisition for actor index N" line
#   the monitor writes to 00_monitor/report/query_agents_*_R.txt for that
#   index. Gap detection for actors is log-based, not file-based.
#
# Recovering a missing edition year can introduce actors that were never in
# distinct_actors_cache.csv. extract_distinct_actors() orders actors by
# first occurrence while scanning editions_df column by column, so simply
# recomputing the cache from the updated editions data could shift the
# position of actors already downloaded, silently misaligning existing
# actor_file_N.csv files against the wrong actor. sync_actor_cache_append_only()
# avoids this: it never reorders or renumbers existing cache rows, it only
# appends actors that are genuinely new, at new indices past the old end of
# the cache. Every appended row is also recorded, with a timestamp and the
# recovering script's name, in actor_cache_additions_log.csv - a durable
# trace of what was added after the fact, independent of the monitor report.

sys.source("01_data_retrieval/01_editions/query_editions.R", envir = globalenv())
sys.source("01_data_retrieval/02_actors/query_agents.R", envir = globalenv())

find_missing_edition_years <- function(yearly_output_dir, first_year, last_year) {
  existing_files <- list.files(
    yearly_output_dir,
    pattern = "^raw_edition_data_for_the_year_[0-9]{4}\\.csv$",
    full.names = FALSE
  )

  existing_years <- suppressWarnings(as.integer(
    sub("^raw_edition_data_for_the_year_([0-9]{4})\\.csv$", "\\1", existing_files)
  ))
  existing_years <- existing_years[!is.na(existing_years)]

  sort(setdiff(first_year:last_year, existing_years))
}

# Extracts the integer captured by line_regex's first group from every line
# of every file in report_dir matching file_pattern. Used both to find
# actor indices logged as failed by query_agents.R, and to find indices this
# script already recovered in a previous run (see recover_missing_actor_indices).
find_context_indices <- function(report_dir, file_pattern, line_regex) {
  if (!dir.exists(report_dir)) {
    return(integer(0))
  }

  report_files <- list.files(report_dir, pattern = file_pattern, full.names = TRUE)

  if (length(report_files) == 0) {
    return(integer(0))
  }

  all_indices <- integer(0)

  for (report_file in report_files) {
    lines <- tryCatch(readLines(report_file, warn = FALSE), error = function(e) character(0))
    hits <- regmatches(lines, regexec(line_regex, lines))
    captured <- vapply(hits, function(h) if (length(h) >= 2) h[2] else NA_character_, character(1))
    all_indices <- c(all_indices, suppressWarnings(as.integer(captured[!is.na(captured)])))
  }

  sort(unique(all_indices[!is.na(all_indices)]))
}

# Recomputes the full distinct-actor list from the current editions data and
# appends to distinct_actors_cache.csv any actor not already present in it,
# leaving every existing row (index and value) untouched. Returns the
# updated cache and the indices of the rows it appended, if any.
sync_actor_cache_append_only <- function(editions_input, output_dir) {
  cache_path <- get_actor_cache_path(output_dir)

  existing_cache <- if (file.exists(cache_path)) {
    read.csv(cache_path, stringsAsFactors = FALSE)
  } else {
    data.frame(actor = character(0), stringsAsFactors = FALSE)
  }

  editions_df <- read_editions_input(editions_input)
  full_actors <- extract_distinct_actors(editions_df)

  new_actor_values <- setdiff(full_actors$actor, existing_cache$actor)

  if (length(new_actor_values) == 0) {
    return(list(cache = existing_cache, new_indices = integer(0)))
  }

  updated_cache <- rbind(existing_cache, data.frame(actor = new_actor_values, stringsAsFactors = FALSE))
  write.csv(updated_cache, cache_path, row.names = FALSE)

  list(
    cache = updated_cache,
    new_indices = seq(nrow(existing_cache) + 1, nrow(updated_cache))
  )
}

# Durable, structured trace of every actor appended by sync_actor_cache_append_only(),
# kept separate from the (timestamped, per-run) monitor reports so "what was
# added later and why" survives independently of report rotation/lookup.
log_actor_cache_additions <- function(output_dir, new_indices, cache, script_label, source_note) {
  if (length(new_indices) == 0) {
    return(invisible(NULL))
  }

  log_path <- file.path(output_dir, "actor_cache_additions_log.csv")

  new_entries <- data.frame(
    actor_index = new_indices,
    actor = cache$actor[new_indices],
    added_at = format(Sys.time(), "%Y-%m-%d %H:%M:%S"),
    added_via = script_label,
    source = source_note,
    stringsAsFactors = FALSE
  )

  write.table(
    new_entries,
    file = log_path,
    sep = ",",
    row.names = FALSE,
    col.names = !file.exists(log_path),
    append = file.exists(log_path)
  )

  invisible(log_path)
}

recover_missing_edition_years <- function(
  missing_years,
  yearly_output_dir,
  query_fun,
  sleep,
  max_attempts,
  retry_delay_seconds,
  script_label,
  checkpoint
) {
  recovered <- integer(0)
  still_missing <- integer(0)

  for (year in missing_years) {
    step_start <- Sys.time()
    success <- FALSE

    for (attempt in seq_len(max_attempts)) {
      result <- tryCatch(
        {
          get_bnf_edition_data(year = year, yearly_output_dir = yearly_output_dir, query_fun = query_fun, sleep = sleep)
          TRUE
        },
        error = function(e) {
          message(sprintf("Recovery attempt %d/%d failed for edition year %d: %s", attempt, max_attempts, year, conditionMessage(e)))
          FALSE
        }
      )

      if (isTRUE(result)) {
        success <- TRUE
        break
      }

      if (attempt < max_attempts) {
        Sys.sleep(retry_delay_seconds)
      }
    }

    duration <- as.numeric(difftime(Sys.time(), step_start, units = "secs"))

    if (success) {
      recovered <- c(recovered, year)
      checkpoint(sprintf("RECOVERED edition year %d (previously missing) via %s | duration: %s", year, script_label, format_duration(duration)))
    } else {
      still_missing <- c(still_missing, year)
      checkpoint(sprintf("RECOVERY FAILED for edition year %d via %s after %d attempt(s) | duration: %s", year, script_label, max_attempts, format_duration(duration)))
    }
  }

  list(recovered = recovered, still_missing = still_missing)
}

# Indices that already have a CSV (query_agents.R was re-run manually and
# happened to cover them) are logged as recovered without re-querying the
# endpoint. Every other recovered index - including ones whose retry legitimately
# returns zero rows and so still has no CSV - is logged as "RECOVERED actor
# index N" too, so find_context_indices() can treat it as handled on the next
# run. Without this ledger a zero-result actor would look "missing" forever.
recover_missing_actor_indices <- function(
  indices,
  actors_df,
  intermediate_output_dir,
  query_fun,
  sleep,
  max_attempts,
  retry_delay_seconds,
  script_label,
  checkpoint,
  new_indices = integer(0)
) {
  recovered <- integer(0)
  still_failing <- integer(0)

  for (idx in indices) {
    actor_uri <- as.character(actors_df$actor[idx])
    file_name <- paste0("actor_file_", idx)
    out_path <- file.path(intermediate_output_dir, paste0(file_name, ".csv"))
    reason_label <- if (idx %in% new_indices) "new actor introduced by recovered edition year(s)" else "previously failed"

    if (file.exists(out_path)) {
      recovered <- c(recovered, idx)
      checkpoint(sprintf("RECOVERED actor index %d - %s (%s, file already present, no re-query needed) via %s", idx, actor_uri, reason_label, script_label))
      next
    }

    step_start <- Sys.time()
    success <- FALSE

    for (attempt in seq_len(max_attempts)) {
      result <- tryCatch(
        {
          get_bnf_data_for_actor(
            actor = actor_uri,
            file_name = file_name,
            intermediate_output_dir = intermediate_output_dir,
            query_fun = query_fun,
            sleep = sleep
          )
        },
        error = function(e) {
          message(sprintf("Recovery attempt %d/%d failed for actor index %d: %s", attempt, max_attempts, idx, conditionMessage(e)))
          FALSE
        }
      )

      if (isTRUE(result)) {
        success <- TRUE
        break
      }

      if (attempt < max_attempts) {
        Sys.sleep(retry_delay_seconds)
      }
    }

    duration <- as.numeric(difftime(Sys.time(), step_start, units = "secs"))

    if (success) {
      recovered <- c(recovered, idx)
      checkpoint(sprintf("RECOVERED actor index %d - %s (%s) via %s | duration: %s", idx, actor_uri, reason_label, script_label, format_duration(duration)))
    } else {
      still_failing <- c(still_failing, idx)
      checkpoint(sprintf("RECOVERY FAILED for actor index %d - %s (%s) via %s after %d attempt(s) | duration: %s", idx, actor_uri, reason_label, script_label, max_attempts, format_duration(duration)))
    }
  }

  list(recovered = recovered, still_failing = still_failing)
}

run_recovery <- function(
  editions_base_dir = "01_data_retrieval/01_editions",
  actors_base_dir = "01_data_retrieval/02_actors",
  editions_input = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv",
  first_year = 1454,
  last_year = 1799,
  report_dir = "00_monitor/report",
  monitor_script = "00_monitor/monitor.R",
  use_monitor = TRUE,
  max_attempts = 3,
  retry_delay_seconds = 5,
  edition_query_fun = run_sparql_query,
  actor_query_fun = run_actor_sparql_query,
  sleep = TRUE
) {
  overall_start <- Sys.time()

  editions_paths <- make_paths(editions_base_dir)
  ensure_output_dirs(editions_paths)

  actors_paths <- make_actor_paths(base_dir = actors_base_dir, editions_input = editions_input)
  ensure_actor_output_dirs(actors_paths)

  monitor_env <- NULL
  monitor_state <- NULL

  if (use_monitor) {
    monitor_env <- load_monitor_env(monitor_script)

    monitor_state <- monitor_env$start_monitor_state(
      sampling_mode = "checkpoint-based updates during recover_missing_acquisitions.R execution",
      print_start_message = TRUE
    )

    on.exit(
      {
        if (!is.null(monitor_state) && !isTRUE(monitor_state$closed)) {
          monitor_env$stop_monitor_state(
            state = monitor_state,
            print_stop_message = TRUE,
            status = "INTERRUPTED"
          )
        }
      },
      add = TRUE
    )
  }

  script_label <- if (use_monitor) monitor_env$get_entry_script_name() else "recover_missing_acquisitions"

  checkpoint <- function(context) {
    if (use_monitor) {
      monitor_state <<- monitor_env$update_monitor_state(state = monitor_state, context = context, print_console = TRUE)
    } else {
      cat(context, "\n")
    }
  }

  ## ---- Stage 1: editions ("entita`") ----

  missing_years <- find_missing_edition_years(editions_paths$yearly_output_dir, first_year, last_year)

  checkpoint(sprintf(
    "Recovery scan: %d missing edition year(s) out of %d (%s)",
    length(missing_years), last_year - first_year + 1,
    if (length(missing_years) > 0) paste(missing_years, collapse = ", ") else "none"
  ))

  edition_recovery <- recover_missing_edition_years(
    missing_years = missing_years,
    yearly_output_dir = editions_paths$yearly_output_dir,
    query_fun = edition_query_fun,
    sleep = sleep,
    max_attempts = max_attempts,
    retry_delay_seconds = retry_delay_seconds,
    script_label = script_label,
    checkpoint = checkpoint
  )

  new_actor_indices <- integer(0)

  if (length(edition_recovery$recovered) > 0) {
    compiled <- compile_edition_data(editions_paths$yearly_output_dir)
    compiled_out_file <- write_compiled_edition_data(compiled, editions_paths$output_dir)
    checkpoint(sprintf("Recompiled %s after recovering %d edition year(s)", compiled_out_file, length(edition_recovery$recovered)))

    # Only sync the actor cache when editions actually changed - the sync
    # re-reads the full compiled editions CSV, which is otherwise wasted
    # work identical to what get_or_extract_distinct_actors() already
    # avoids by caching.
    sync_result <- sync_actor_cache_append_only(actors_paths$editions_input, actors_paths$output_dir)
    new_actor_indices <- sync_result$new_indices

    if (length(new_actor_indices) > 0) {
      log_actor_cache_additions(
        output_dir = actors_paths$output_dir,
        new_indices = new_actor_indices,
        cache = sync_result$cache,
        script_label = script_label,
        source_note = sprintf("edition year recovery: %s", paste(edition_recovery$recovered, collapse = ";"))
      )
    }

    checkpoint(sprintf(
      "Actor cache sync after edition recovery: %d new actor(s) appended to distinct_actors_cache.csv (indices %s), logged to actor_cache_additions_log.csv",
      length(new_actor_indices),
      if (length(new_actor_indices) > 0) paste(range(new_actor_indices), collapse = "-") else "none"
    ))
  }

  ## ---- Stage 2: actors ----
  # get_or_extract_distinct_actors() re-reads distinct_actors_cache.csv here,
  # which by this point already reflects any append made above - existing
  # indices are untouched, so already-downloaded actor_file_N.csv files stay
  # correctly aligned.

  actors_df <- get_or_extract_distinct_actors(actors_paths$editions_input, actors_paths$output_dir)

  failed_actor_indices <- find_context_indices(
    report_dir, "^query_agents_.*_R\\.txt$",
    "Failed acquisition for actor index ([0-9]+)"
  )
  # A previous recovery attempt can itself have failed after retries (see
  # RECOVERY FAILED lines below) - those indices need to stay eligible too,
  # or they would never be retried again.
  recovery_failed_actor_indices <- find_context_indices(
    report_dir, "^recover_missing_acquisitions_.*_R\\.txt$",
    "RECOVERY FAILED for actor index ([0-9]+)"
  )
  already_recovered_actor_indices <- find_context_indices(
    report_dir, "^recover_missing_acquisitions_.*_R\\.txt$",
    "RECOVERED actor index ([0-9]+)"
  )

  candidate_actor_indices <- setdiff(
    union(failed_actor_indices, recovery_failed_actor_indices),
    already_recovered_actor_indices
  )
  candidate_actor_indices <- candidate_actor_indices[candidate_actor_indices <= nrow(actors_df)]

  all_recovery_indices <- sort(unique(c(candidate_actor_indices, new_actor_indices)))

  checkpoint(sprintf(
    "Recovery scan: %d actor index(es) to process (%d previously failed, not yet recovered; %d newly introduced by edition recovery)",
    length(all_recovery_indices), length(candidate_actor_indices), length(new_actor_indices)
  ))

  actor_recovery <- recover_missing_actor_indices(
    indices = all_recovery_indices,
    actors_df = actors_df,
    intermediate_output_dir = actors_paths$intermediate_output_dir,
    query_fun = actor_query_fun,
    sleep = sleep,
    max_attempts = max_attempts,
    retry_delay_seconds = retry_delay_seconds,
    script_label = script_label,
    checkpoint = checkpoint,
    new_indices = new_actor_indices
  )

  if (length(actor_recovery$recovered) > 0) {
    merged <- merge_actor_csvs(actors_paths$intermediate_output_dir, actors_paths$output_dir)
    checkpoint(sprintf("Re-merged %s after recovering %d actor index(es)", merged$out_file, length(actor_recovery$recovered)))
  }

  total_duration <- as.numeric(difftime(Sys.time(), overall_start, units = "secs"))

  checkpoint(sprintf(
    "Recovery summary via %s: editions %d/%d recovered; %d new actor(s) discovered from recovered editions; actors %d/%d recovered (%d still failing after %d attempt(s) each); total duration %s",
    script_label,
    length(edition_recovery$recovered), length(missing_years),
    length(new_actor_indices),
    length(actor_recovery$recovered), length(all_recovery_indices), length(actor_recovery$still_failing),
    max_attempts, format_duration(total_duration)
  ))

  if (use_monitor) {
    monitor_state <- monitor_env$stop_monitor_state(state = monitor_state, print_stop_message = TRUE)
  }

  invisible(list(
    missing_years = missing_years,
    edition_recovery = edition_recovery,
    new_actor_indices = new_actor_indices,
    candidate_actor_indices = all_recovery_indices,
    actor_recovery = actor_recovery,
    duration_seconds = total_duration,
    monitor_report = if (use_monitor) monitor_state$report_path else NULL
  ))
}

if (sys.nframe() == 0) {
  cli_args <- commandArgs(trailingOnly = TRUE)

  cli_first_year <- if (length(cli_args) >= 1 && nzchar(cli_args[1])) as.integer(cli_args[1]) else 1454
  cli_last_year <- if (length(cli_args) >= 2 && nzchar(cli_args[2])) as.integer(cli_args[2]) else 1799
  cli_max_attempts <- if (length(cli_args) >= 3 && nzchar(cli_args[3])) as.integer(cli_args[3]) else 3
  cli_retry_delay_seconds <- if (length(cli_args) >= 4 && nzchar(cli_args[4])) as.integer(cli_args[4]) else 5

  run_recovery(
    first_year = cli_first_year,
    last_year = cli_last_year,
    max_attempts = cli_max_attempts,
    retry_delay_seconds = cli_retry_delay_seconds,
    use_monitor = TRUE
  )
}
