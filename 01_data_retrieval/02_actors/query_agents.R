# 01_data_retrieval/02_actors/query_agents.R

format_duration <- function(secs) {
  secs <- max(0, round(secs))
  h <- secs %/% 3600
  m <- (secs %% 3600) %/% 60
  s <- secs %% 60
  if (h > 0) sprintf("%dh %02dm %02ds", h, m, s)
  else if (m > 0) sprintf("%dm %02ds", m, s)
  else sprintf("%ds", s)
}

print_progress <- function(current, total, start_time, step_times) {
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

  cat(sprintf(
    "\r%s %3.0f%%  %d/%d  elapsed: %s  ETA: %s   ",
    bar, pct * 100, current, total, elapsed_str, eta_str
  ))

  if (current >= total) cat("\n")
  flush.console()
}

make_actor_paths <- function(
  base_dir = "01_data_retrieval/02_actors",
  editions_input = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv"
) {
  output_dir <- file.path(base_dir, "data")
  intermediate_output_dir <- file.path(output_dir, "actor_queries_results")
  progress_file <- file.path(output_dir, "last_processed_index.txt")

  list(
    base_dir = base_dir,
    output_dir = output_dir,
    intermediate_output_dir = intermediate_output_dir,
    editions_input = editions_input,
    progress_file = progress_file
  )
}

ensure_actor_output_dirs <- function(paths) {
  dir.create(paths$output_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(paths$intermediate_output_dir, recursive = TRUE, showWarnings = FALSE)
}

get_start_index <- function(progress_file) {
  if (!file.exists(progress_file)) {
    return(1)
  }

  last_index <- suppressWarnings(as.integer(readLines(progress_file, warn = FALSE, n = 1)))

  if (is.na(last_index)) {
    return(1)
  }

  last_index + 1
}

build_actor_query <- function(actor) {
  paste0('PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
PREFIX bnf-onto: <http://data.bnf.fr/ontology/bnf-onto/>
PREFIX rdarelationships: <http://rdvocab.info/RDARelationshipsWEMI/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdam: <http://rdaregistry.info/Elements/m/#> 
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/> 
PREFIX bio: <http://vocab.org/bio/0.1/> 
PREFIX skos: <http://www.w3.org/2004/02/skos/core#> 
SELECT DISTINCT ?actor_birth ?actor_name ?actor_first_name ?actor_last_name ?entity_type ?first_year ?actor_country ?actor_language ?actor_gender ?actor_profession ?actor_death ?actor_start ?actor_end ?actor_link_exact ?actor_link_close

WHERE {
 OPTIONAL {', as.character(actor), ' foaf:name ?actor_name.} 
 OPTIONAL {', as.character(actor), ' foaf:givenName ?actor_first_name.}
 OPTIONAL {', as.character(actor), ' foaf:familyName ?actor_last_name.}
 OPTIONAL {', as.character(actor), ' rdf:type ?entity_type.}
 OPTIONAL {', as.character(actor), ' bnf-onto:firstYear ?first_year.}  
 OPTIONAL {', as.character(actor), ' bio:birth ?actor_birth.}
 OPTIONAL {', as.character(actor), ' rdagroup2elements:countryAssociatedWithThePerson ?actor_country.}
 OPTIONAL {', as.character(actor), ' rdagroup2elements:languageOfThePerson ?actor_language.}
 OPTIONAL {', as.character(actor), ' foaf:gender ?actor_gender.}
 OPTIONAL {', as.character(actor), ' rdagroup2elements:biographicalInformation ?actor_profession.}
 OPTIONAL {', as.character(actor), ' bio:death ?actor_death.}
 OPTIONAL {', as.character(actor), ' bnf-onto:firstYear ?actor_start.} 
 OPTIONAL {', as.character(actor), ' bnf-onto:lastYear ?actor_end.}  
 OPTIONAL { 
    ?person foaf:focus ', as.character(actor), '.
    ?person skos:exactMatch ?actor_link_exact.}
 OPTIONAL { 
    ?person foaf:focus ', as.character(actor), '.
    ?person skos:closeMatch ?actor_link_close.}
 }')
}

run_actor_sparql_query <- function(query, url = "https://data.bnf.fr/sparql") {
  if (!requireNamespace("SPARQL", quietly = TRUE)) {
    stop("The 'SPARQL' package is required only for live endpoint queries.")
  }
  SPARQL::SPARQL(url = url, query = query)$results
}

get_bnf_data_for_actor <- function(
  actor,
  file_name,
  intermediate_output_dir,
  query_fun = run_actor_sparql_query,
  sleep = TRUE
) {
  query <- build_actor_query(actor)
  data_table <- query_fun(query)

  if (nrow(data_table) != 0) {
    write.csv(
      cbind.data.frame(actor = actor, data_table),
      file = file.path(intermediate_output_dir, paste0(file_name, ".csv")),
      row.names = FALSE
    )
  }

  if (sleep) {
    Sys.sleep(1 + runif(n = 1) * 1)
  }

  TRUE
}

read_editions_input <- function(editions_input) {
  read.csv(editions_input, stringsAsFactors = FALSE)
}

extract_distinct_actors <- function(editions_df) {
  role_cols <- c("author", "editor", "illustrator", "publisher_2", "translator")
  available_cols <- intersect(role_cols, colnames(editions_df))

  if (length(available_cols) == 0) {
    return(data.frame(actor = character(0), stringsAsFactors = FALSE))
  }

  actor_values <- unlist(editions_df[available_cols], use.names = FALSE)
  actor_values <- trimws(as.character(actor_values))
  actor_values <- actor_values[!is.na(actor_values) & actor_values != ""]
  actor_values <- unique(actor_values)

  data.frame(actor = actor_values, stringsAsFactors = FALSE)
}

merge_actor_csvs <- function(intermediate_output_dir, output_dir) {
  list_actors <- list.files(intermediate_output_dir, pattern = "\\.csv$", full.names = TRUE)

  if (length(list_actors) == 0) {
    stop("No actor CSV files found in the intermediate output directory.")
  }

  list_actors_data <- do.call(rbind, lapply(list_actors, read.csv, stringsAsFactors = FALSE))

  out_file <- file.path(output_dir, "actor_data.csv")
  write.csv(list_actors_data, out_file, row.names = FALSE)

  invisible(list(
    data = list_actors_data,
    out_file = out_file
  ))
}

load_monitor_env <- function(monitor_script = "00_monitor/monitor.R") {
  resolved_monitor_script <- normalizePath(monitor_script, mustWork = TRUE)
  env <- new.env(parent = baseenv())
  sys.source(resolved_monitor_script, envir = env)
  env
}

run_query_agents <- function(
  base_dir = "01_data_retrieval/02_actors",
  editions_input = "01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv",
  query_fun = run_actor_sparql_query,
  sleep = TRUE,
  use_monitor = FALSE,
  monitor_script = "00_monitor/monitor.R"
) {
  paths <- make_actor_paths(base_dir = base_dir, editions_input = editions_input)
  ensure_actor_output_dirs(paths)

  editions_df <- read_editions_input(paths$editions_input)
  actors_df <- extract_distinct_actors(editions_df)

  if (nrow(actors_df) == 0) {
    stop("No actors found in the editions input.")
  }

  start_index <- get_start_index(paths$progress_file)

  monitor_env <- NULL
  monitor_state <- NULL

  if (use_monitor) {
    monitor_env <- load_monitor_env(monitor_script)

    monitor_state <- monitor_env$start_monitor_state(
      sampling_mode = "checkpoint-based updates during query_agents.R execution",
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

  total_actors <- nrow(actors_df)
  loop_start <- Sys.time()
  step_times <- numeric(0)

  if (start_index <= nrow(actors_df)) {
    for (i in start_index:nrow(actors_df)) {
      step_start <- Sys.time()

      success <- tryCatch(
        {
          get_bnf_data_for_actor(
            actor = as.character(actors_df$actor[i]),
            file_name = paste0("actor_file_", as.character(i)),
            intermediate_output_dir = paths$intermediate_output_dir,
            query_fun = query_fun,
            sleep = sleep
          )
        },
        error = function(e) {
          message("Error at index ", i, ": ", conditionMessage(e))
          FALSE
        }
      )

      if (isTRUE(success)) {
        writeLines(as.character(i), paths$progress_file)
      }

      step_times <- c(step_times, as.numeric(difftime(Sys.time(), step_start, units = "secs")))
      print_progress(i, total_actors, loop_start, step_times)

      if (use_monitor) {
        actor_label <- as.character(actors_df$actor[i])

        context <- if (isTRUE(success)) {
          paste("Completed acquisition for actor index", i, "-", actor_label)
        } else {
          paste("Failed acquisition for actor index", i, "-", actor_label)
        }

        monitor_state <- monitor_env$update_monitor_state(
          state = monitor_state,
          context = context,
          print_console = TRUE
        )
      }
    }
  }

  merged <- merge_actor_csvs(paths$intermediate_output_dir, paths$output_dir)

  if (use_monitor) {
    monitor_state <- monitor_env$update_monitor_state(
      state = monitor_state,
      context = "Completed actor CSV merge and final output writing",
      print_console = TRUE
    )

    monitor_state <- monitor_env$stop_monitor_state(
      state = monitor_state,
      print_stop_message = TRUE
    )
  }

  invisible(list(
    paths = paths,
    actors = actors_df,
    data = merged$data,
    out_file = merged$out_file,
    start_index = start_index,
    monitor_report = if (use_monitor) monitor_state$report_path else NULL
  ))
}

if (sys.nframe() == 0) {
  run_query_agents(use_monitor = TRUE)
}