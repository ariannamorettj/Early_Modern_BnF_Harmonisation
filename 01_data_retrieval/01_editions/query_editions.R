# 01_data_retrieval/01_editions/query_editions.R

library(SPARQL)
library(tidyverse)

format_duration <- function(secs) {
  secs <- max(0, round(secs))
  h <- secs %/% 3600
  m <- (secs %% 3600) %/% 60
  s <- secs %% 60
  if (h > 0) sprintf("%dh %02dm %02ds", h, m, s)
  else if (m > 0) sprintf("%dm %02ds", m, s)
  else sprintf("%ds", s)
}

print_progress <- function(current, total, start_time, step_times, label = NULL, force_newline = FALSE) {
  pct <- current / total
  bar_width <- 40
  filled <- round(pct * bar_width)

  if (filled >= bar_width) {
    bar_inner <- strrep("=", bar_width)
  } else if (filled == 0) {
    bar_inner <- paste0(">", strrep(" ", bar_width - 1))
  } else {
    bar_inner <- paste0(strrep("=", filled), ">", strrep(" ", bar_width - filled - 1))
  }
  bar <- paste0("[", bar_inner, "]")

  elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
  elapsed_str <- format_duration(elapsed)

  if (length(step_times) > 0) {
    avg_step <- mean(tail(step_times, 10))
    eta_secs <- avg_step * (total - current)
    eta_str <- format_duration(eta_secs)
  } else {
    eta_str <- "--"
  }

  prefix <- if (!is.null(label) && nzchar(label)) sprintf("%s ", label) else ""

  cat(sprintf(
    "\r%s%s %3.0f%%  %d/%d  elapsed: %s  ETA: %s   ",
    prefix, bar, pct * 100, current, total, elapsed_str, eta_str
  ))

  if (current >= total || force_newline) cat("\n")
  flush.console()
}

make_paths <- function(base_dir = "01_data_retrieval/01_editions") {
  output_dir <- file.path(base_dir, "data")
  yearly_output_dir <- file.path(output_dir, "edition_raw_data_by_year")

  list(
    base_dir = base_dir,
    output_dir = output_dir,
    yearly_output_dir = yearly_output_dir
  )
}

ensure_output_dirs <- function(paths) {
  dir.create(paths$output_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(paths$yearly_output_dir, recursive = TRUE, showWarnings = FALSE)
}

format_session_timestamp <- function(t = Sys.time()) {
  format(t, "%Y%m%d_%H%M%S")
}

get_session_info_path <- function(output_dir, session_timestamp) {
  file.path(output_dir, paste0("sessionInfo_data_acquisition_", session_timestamp, ".txt"))
}

# One session-info file is shared across all sub-batches of a single acquisition
# (see run_query_editions_batched.ps1, which restarts Rscript every N years to
# bound virtual memory growth). The header + sessionInfo() are written once,
# the first time the file is created; every batch, including the first, then
# appends one line to the batch log below so the file documents how the
# acquisition was actually split into restarted Rscript processes.
write_session_info_header <- function(path) {
  writeLines(
    c(
      strrep("=", 70),
      "BnF DATA ACQUISITION - SESSION INFO",
      strrep("=", 70),
      "",
      capture.output(sessionInfo()),
      "",
      strrep("-", 70),
      "Batch log (one entry per completed batch; the acquisition may be split",
      "into several restarted Rscript batches to bound virtual memory growth.",
      "A batch that crashes/is killed before finishing will not appear here -",
      "check the console output or 00_monitor/report/ for those):",
      strrep("-", 70),
      ""
    ),
    path
  )
}

append_batch_log_entry <- function(
  path,
  requested_last_year,
  start_year_used,
  batch_start,
  batch_end,
  status
) {
  duration <- as.numeric(difftime(batch_end, batch_start, units = "secs"))

  con <- file(path, open = "at", encoding = "UTF-8")
  on.exit(close(con), add = TRUE)

  writeLines(
    sprintf(
      "Batch years %d-%d | started %s | ended %s | duration %s | status: %s",
      start_year_used,
      requested_last_year,
      format(batch_start, "%Y-%m-%d %H:%M:%S"),
      format(batch_end, "%Y-%m-%d %H:%M:%S"),
      format_duration(duration),
      status
    ),
    con
  )
}

append_total_time_summary <- function(path, total_start, total_end) {
  duration <- as.numeric(difftime(total_end, total_start, units = "secs"))

  con <- file(path, open = "at", encoding = "UTF-8")
  on.exit(close(con), add = TRUE)

  writeLines(
    c(
      "",
      strrep("-", 70),
      sprintf(
        "TOTAL ACQUISITION TIME: %s (from %s to %s)",
        format_duration(duration),
        format(total_start, "%Y-%m-%d %H:%M:%S"),
        format(total_end, "%Y-%m-%d %H:%M:%S")
      ),
      strrep("-", 70)
    ),
    con
  )
}

get_start_year <- function(yearly_output_dir, first_year = 1454) {
  existing_files <- list.files(
    yearly_output_dir,
    pattern = "^raw_edition_data_for_the_year_[0-9]{4}\\.csv$",
    full.names = FALSE
  )

  if (length(existing_files) == 0) {
    return(first_year)
  }

  extracted_years <- suppressWarnings(as.integer(
    sub("^raw_edition_data_for_the_year_([0-9]{4})\\.csv$", "\\1", existing_files)
  ))

  extracted_years <- extracted_years[!is.na(extracted_years)]

  if (length(extracted_years) == 0) {
    return(first_year)
  }

  max(extracted_years)
}

build_bnf_edition_query <- function(year) {
  paste0("PREFIX bnf-onto: <http://data.bnf.fr/ontology/bnf-onto/>
PREFIX rdarelationships: <http://rdvocab.info/RDARelationshipsWEMI/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdam: <http://rdaregistry.info/Elements/m/#> 
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
SELECT DISTINCT ?edition ?bnf_id ?title ?year_first ?year_range ?description ?place ?publisher ?work ?digital_copy_link ?subject_topic ?expression ?language ?record_type ?author ?editor ?translator ?publisher_2 ?illustrator

WHERE {
 ?edition bnf-onto:firstYear ?year_first.
 OPTIONAL {?edition bnf-onto:FRBNF ?bnf_id.} 
 OPTIONAL {?edition rdam:P30279 ?place.}
 OPTIONAL {?edition dcterms:title ?title.}
 OPTIONAL {?edition rdam:P30176 ?publisher.}
 OPTIONAL {?edition dcterms:description ?description.}
 OPTIONAL {?edition bnf-onto:firstYear ?year_first.}
 OPTIONAL {?edition dcterms:date ?year_range.}
 OPTIONAL {?edition rdarelationships:workManifested ?work.}
 OPTIONAL {?edition rdam:P30016 ?digital_copy_link.}
 OPTIONAL {?edition dcterms:subject ?subject_topic.}
 ?edition rdarelationships:expressionManifested ?expression.
 OPTIONAL {?expression dcterms:language ?language.}
 OPTIONAL {?expression dcterms:type ?record_type.}
 OPTIONAL {?expression marcrel:aut ?author.}
 OPTIONAL {?expression marcrel:edt ?editor.}
 OPTIONAL {?expression marcrel:trl ?translator.}
 OPTIONAL {?expression marcrel:pbl ?publisher_2.}
 OPTIONAL {?expression marcrel:ill ?illustrator.}

 FILTER(?year_first = ", as.character(year), ").
}")
}

run_sparql_query <- function(query, url = "https://data.bnf.fr/sparql") {
  SPARQL(url = url, query = query)$results
}

get_bnf_edition_data <- function(
  year,
  yearly_output_dir,
  query_fun = run_sparql_query,
  sleep = TRUE
) {
  query <- build_bnf_edition_query(year)
  data_table <- query_fun(query)

  out_file <- file.path(
    yearly_output_dir,
    paste0("raw_edition_data_for_the_year_", as.character(year), ".csv")
  )

  write.csv(
    data_table,
    out_file,
    row.names = FALSE
  )

  if (sleep) {
    Sys.sleep(5 + runif(n = 1) * 5)
  }

  rm(data_table)
  gc()

  invisible(out_file)
}

compile_edition_data <- function(yearly_output_dir) {
  list_edition_data <- list.files(
    yearly_output_dir,
    pattern = "^raw_edition_data_for_the_year_[0-9]{4}\\.csv$",
    full.names = TRUE
  )

  if (length(list_edition_data) == 0) {
    stop("No yearly edition CSV files found.")
  }

  do.call(rbind, lapply(list_edition_data, read.csv, stringsAsFactors = FALSE))
}

write_compiled_edition_data <- function(data, output_dir) {
  out_file <- file.path(output_dir, "bnf_edition_data_raw.csv")
  write.csv(data, out_file, row.names = FALSE)
  invisible(out_file)
}

compute_edition_stats <- function(df) {
  list(
    n_unique_editions = df %>% distinct(edition) %>% nrow(),
    n_with_place_information = df %>% filter(!is.na(place) & place != "") %>% distinct(edition) %>% nrow(),
    n_with_record_type_information = df %>% filter(!is.na(record_type) & record_type != "") %>% distinct(edition) %>% nrow(),
    n_with_author_information = df %>% filter(!is.na(author) & author != "") %>% distinct(edition) %>% nrow(),
    n_with_language_information = df %>% filter(!is.na(language) & language != "") %>% distinct(edition) %>% nrow()
  )
}

load_monitor_env <- function(monitor_script = "00_monitor/monitor.R") {
  resolved_monitor_script <- normalizePath(monitor_script, mustWork = TRUE)
  env <- new.env(parent = baseenv())
  sys.source(resolved_monitor_script, envir = env)
  env
}

run_query_editions <- function(
  base_dir = "01_data_retrieval/01_editions",
  first_year = 1454,
  last_year = 1799,
  query_fun = run_sparql_query,
  sleep = TRUE,
  write_session_info = TRUE,
  use_monitor = FALSE,
  monitor_script = "00_monitor/monitor.R",
  compile_output = TRUE,
  session_timestamp = NULL,
  overall_last_year = NULL
) {
  paths <- make_paths(base_dir)
  ensure_output_dirs(paths)

  batch_start_time <- Sys.time()

  if (is.null(session_timestamp)) {
    session_timestamp <- format_session_timestamp(batch_start_time)
  }

  session_info_path <- get_session_info_path(paths$output_dir, session_timestamp)

  if (write_session_info && !file.exists(session_info_path)) {
    write_session_info_header(session_info_path)
  }

  start_year <- get_start_year(paths$yearly_output_dir, first_year = first_year)

  if (start_year > last_year) {
    cat(sprintf(
      "Nothing to do: existing data already covers up to year %d (requested last_year = %d).\n",
      start_year, last_year
    ))

    if (write_session_info) {
      append_batch_log_entry(
        path = session_info_path,
        requested_last_year = last_year,
        start_year_used = start_year,
        batch_start = batch_start_time,
        batch_end = Sys.time(),
        status = "SKIPPED (already up to date)"
      )
    }

    return(invisible(list(
      paths = paths,
      data = NULL,
      stats = NULL,
      start_year = start_year,
      compiled_out_file = NULL,
      monitor_report = NULL
    )))
  }

  monitor_env <- NULL
  monitor_state <- NULL

  if (use_monitor) {
    monitor_env <- load_monitor_env(monitor_script)

    monitor_state <- monitor_env$start_monitor_state(
      sampling_mode = "checkpoint-based updates during query_editions.R execution",
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

  # Block-local bar: progress within *this* Rscript invocation only.
  total_steps <- last_year - start_year + 1
  loop_start <- Sys.time()
  step_times <- numeric(0)

  # Overall bar: progress across the whole acquisition (first_year is the
  # fixed overall start in every batch; overall_last_year is the true final
  # year, e.g. passed by run_query_editions_batched.ps1). Only shown when
  # overall_last_year is supplied, so a plain single-shot run is unaffected.
  show_overall <- !is.null(overall_last_year)
  overall_total <- if (show_overall) overall_last_year - first_year + 1 else NA
  overall_start_time <- tryCatch(
    {
      parsed <- as.POSIXct(session_timestamp, format = "%Y%m%d_%H%M%S")
      if (is.na(parsed)) loop_start else parsed
    },
    error = function(e) loop_start
  )

  for (i in start_year:last_year) {
    step_start <- Sys.time()

    get_bnf_edition_data(
      year = i,
      yearly_output_dir = paths$yearly_output_dir,
      query_fun = query_fun,
      sleep = sleep
    )

    step_times <- c(step_times, as.numeric(difftime(Sys.time(), step_start, units = "secs")))
    print_progress(i - start_year + 1, total_steps, loop_start, step_times, label = "[BLOCK]  ")

    if (show_overall) {
      print_progress(
        current = i - first_year + 1,
        total = overall_total,
        start_time = overall_start_time,
        step_times = step_times,
        label = "[OVERALL]",
        force_newline = TRUE
      )
    }

    gc()

    if (use_monitor) {
      monitor_state <- monitor_env$update_monitor_state(
        state = monitor_state,
        context = paste("Completed acquisition for year", i),
        print_console = TRUE
      )
    }
  }

  if (write_session_info) {
    append_batch_log_entry(
      path = session_info_path,
      requested_last_year = last_year,
      start_year_used = start_year,
      batch_start = batch_start_time,
      batch_end = Sys.time(),
      status = "COMPLETED"
    )
  }

  compiled <- NULL
  compiled_out_file <- NULL
  stats <- NULL

  if (compile_output) {
    compiled <- compile_edition_data(paths$yearly_output_dir)
    compiled_out_file <- write_compiled_edition_data(compiled, paths$output_dir)
    stats <- compute_edition_stats(compiled)

    if (write_session_info) {
      append_total_time_summary(
        path = session_info_path,
        total_start = overall_start_time,
        total_end = Sys.time()
      )
    }
  }

  if (use_monitor) {
    monitor_state <- monitor_env$update_monitor_state(
      state = monitor_state,
      context = if (compile_output) {
        "Completed compiled CSV writing and statistics computation"
      } else {
        paste("Completed acquisition batch up to year", last_year)
      },
      print_console = TRUE
    )

    monitor_state <- monitor_env$stop_monitor_state(
      state = monitor_state,
      print_stop_message = TRUE
    )
  }

  invisible(list(
    paths = paths,
    data = compiled,
    stats = stats,
    start_year = start_year,
    compiled_out_file = compiled_out_file,
    monitor_report = if (use_monitor) monitor_state$report_path else NULL
  ))
}

if (sys.nframe() == 0) {
  cli_args <- commandArgs(trailingOnly = TRUE)

  cli_first_year <- if (length(cli_args) >= 1) as.integer(cli_args[1]) else 1454
  cli_last_year <- if (length(cli_args) >= 2) as.integer(cli_args[2]) else 1799
  cli_compile_output <- if (length(cli_args) >= 3) as.logical(cli_args[3]) else TRUE
  cli_session_timestamp <- if (length(cli_args) >= 4 && nzchar(cli_args[4])) cli_args[4] else NULL
  cli_overall_last_year <- if (length(cli_args) >= 5 && nzchar(cli_args[5])) as.integer(cli_args[5]) else NULL

  run_query_editions(
    first_year = cli_first_year,
    last_year = cli_last_year,
    use_monitor = TRUE,
    compile_output = cli_compile_output,
    session_timestamp = cli_session_timestamp,
    overall_last_year = cli_overall_last_year
  )
}