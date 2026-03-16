# 01_data_retrieval/01_editions/query_editions.R

library(SPARQL)
library(tidyverse)

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

write_session_info_file <- function(output_dir) {
  writeLines(
    capture.output(sessionInfo()),
    file.path(
      output_dir,
      paste0("sessionInfo_of_the_bnf_data_acquisition_run_of_", as.character(Sys.Date()), ".txt")
    )
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
  monitor_script = "00_monitor/monitor.R"
) {
  paths <- make_paths(base_dir)
  ensure_output_dirs(paths)

  if (write_session_info) {
    write_session_info_file(paths$output_dir)
  }

  start_year <- get_start_year(paths$yearly_output_dir, first_year = first_year)

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
            print_stop_message = TRUE
          )
        }
      },
      add = TRUE
    )
  }

  for (i in start_year:last_year) {
    get_bnf_edition_data(
      year = i,
      yearly_output_dir = paths$yearly_output_dir,
      query_fun = query_fun,
      sleep = sleep
    )

    print(i)
    gc()

    if (use_monitor) {
      monitor_state <- monitor_env$update_monitor_state(
        state = monitor_state,
        context = paste("Completed acquisition for year", i),
        print_console = TRUE
      )
    }
  }

  compiled <- compile_edition_data(paths$yearly_output_dir)
  compiled_out_file <- write_compiled_edition_data(compiled, paths$output_dir)
  stats <- compute_edition_stats(compiled)

  if (use_monitor) {
    monitor_state <- monitor_env$update_monitor_state(
      state = monitor_state,
      context = "Completed compiled CSV writing and statistics computation",
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
  run_query_editions(use_monitor = TRUE)
}