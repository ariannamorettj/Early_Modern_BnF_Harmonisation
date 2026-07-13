library(testthat)

script_path <- normalizePath(
  file.path("..", "00_monitor", "monitor.R"),
  mustWork = TRUE
)

load_monitor_env <- function() {
  env <- new.env(parent = baseenv())
  sys.source(script_path, envir = env)
  env
}

test_that("monitor script exists", {
  expect_true(
    file.exists(script_path),
    info = paste("Monitor script not found at:", script_path)
  )
})

test_that("create_report_file uses caller name, timestamp, output dir and R suffix", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_report_test_r_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)

  env$OUTPUT_DIR <- tmp_out
  env$get_entry_script_name <- function() "launcher_script"

  report_path <- env$create_report_file()
  report_name <- basename(report_path)

  expect_equal(dirname(report_path), tmp_out)
  expect_true(grepl("^launcher_script_[0-9]{8}_[0-9]{6}_R\\.txt$", report_name))
})

test_that("compute_system_cpu_percent matches expected formula", {
  env <- load_monitor_env()

  cpu_pct <- env$compute_system_cpu_percent(
    prev_total = 1000,
    prev_idle = 200,
    curr_total = 1200,
    curr_idle = 250
  )

  expect_equal(cpu_pct, 75.0)
})

test_that("compute_network_mbps matches expected formula", {
  env <- load_monitor_env()

  net <- env$compute_network_mbps(
    prev_sent = 100,
    prev_recv = 200,
    curr_sent = 1000100,
    curr_recv = 2000200,
    elapsed_seconds = 2.0
  )

  expect_equal(net$dl, 8.0)
  expect_equal(net$ul, 4.0)
})

test_that("compute_process_cpu_percent matches expected formula", {
  env <- load_monitor_env()

  cpu_pct <- env$compute_process_cpu_percent(
    prev_jiffies = 1000,
    curr_jiffies = 1200,
    clock_ticks = 100,
    elapsed_seconds = 4.0
  )

  expect_equal(cpu_pct, 50.0)
})

test_that("safe_close_connection closes an open connection", {
  env <- load_monitor_env()

  tmp_file <- tempfile(fileext = ".txt")
  con <- file(tmp_file, open = "wt", encoding = "UTF-8")
  writeLines("test", con)

  expect_true(isOpen(con))
  result <- env$safe_close_connection(con)

  expect_true(isTRUE(result))
  expect_false(tryCatch(isOpen(con), error = function(e) FALSE))
})

test_that("write_report_header writes interval, sampling mode and interface", {
  env <- load_monitor_env()

  tmp_file <- tempfile(fileext = ".txt")
  con <- file(tmp_file, open = "wt", encoding = "UTF-8")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  env$get_entry_script_name <- function() "launcher_script"

  env$write_report_header(
    con = con,
    start_time = as.POSIXct("2026-03-16 10:00:00", tz = "UTC"),
    interval_seconds = 5.0,
    interface_name = "eth0",
    sampling_mode = "checkpoint-based updates during test execution"
  )

  flush(con)
  report_text <- paste(readLines(tmp_file, warn = FALSE), collapse = "\n")

  expect_match(report_text, "SYSTEM MONITORING REPORT - R")
  expect_match(report_text, "Entry Script: launcher_script")
  expect_match(report_text, "Sampling Interval: 5\\.00 seconds")
  expect_match(report_text, "Sampling Mode: checkpoint-based updates during test execution")
  expect_match(report_text, "Network Interface: eth0")
})

test_that("write_metrics_to_report writes context and metrics block", {
  env <- load_monitor_env()

  tmp_file <- tempfile(fileext = ".txt")
  con <- file(tmp_file, open = "wt", encoding = "UTF-8")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  env$write_metrics_to_report(
    con = con,
    cycle = 1,
    cpu = 75.0,
    mem = 40.0,
    disk = 50.0,
    gpu_util = 10,
    gpu_mem = 256,
    dl = 8.0,
    ul = 4.0,
    cpu_proc = 50.0,
    mem_proc = 1.25,
    context = "Completed checkpoint test"
  )

  flush(con)
  report_text <- paste(readLines(tmp_file, warn = FALSE), collapse = "\n")

  expect_match(report_text, "Cycle 1:")
  expect_match(report_text, "Context: Completed checkpoint test")
  expect_match(report_text, "System — CPU: 75\\.0% \\| Mem: 40\\.0% \\| Disk: 50\\.0%")
  expect_match(report_text, "GPU    — Util: 10% \\| Mem: 256 MB")
  expect_match(report_text, "Network— DL: 8\\.00 Mbps \\| UL: 4\\.00 Mbps")
  expect_match(report_text, "Process— CPU: 50\\.0% \\| Mem: 1\\.25%")
})

test_that("start_monitor_state creates report and initialises monitor state", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_state_start_r_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)

  env$OUTPUT_DIR <- tmp_out
  env$RESUME_LOG <- tempfile(fileext = ".log")
  env$get_entry_script_name <- function() "launcher_script"
  env$read_resume_log <- function() invisible(NULL)
  env$get_default_interface <- function() "eth0"
  env$get_clock_ticks <- function() 100
  env$read_proc_stat <- function() list(total = 1000, idle = 200)
  env$read_process_cpu_jiffies <- function(pid) 1000
  env$read_net_bytes <- function(interface) list(sent = 100, recv = 200)

  state <- env$start_monitor_state(
    interval_seconds = 5.0,
    sampling_mode = "checkpoint-based updates during test execution",
    print_start_message = FALSE
  )

  on.exit(
    {
      env$stop_monitor_state(state, print_stop_message = FALSE)
    },
    add = TRUE
  )

  expect_equal(state$cycle, 0)
  expect_false(state$closed)
  expect_equal(state$interface, "eth0")
  expect_equal(state$clock_ticks, 100)
  expect_equal(state$prev_cpu$total, 1000)
  expect_equal(state$prev_cpu$idle, 200)
  expect_equal(state$prev_proc_jiffies, 1000)
  expect_equal(state$prev_net$sent, 100)
  expect_equal(state$prev_net$recv, 200)
  expect_true(file.exists(state$report_path))
  expect_equal(state$script_name, "launcher_script")
  expect_null(state$last_context)

  flush(state$report_con)
  report_text <- paste(readLines(state$report_path, warn = FALSE), collapse = "\n")

  expect_match(report_text, "SYSTEM MONITORING REPORT - R")
  expect_match(report_text, "Entry Script: launcher_script")
  expect_match(report_text, "Sampling Interval: 5\\.00 seconds")
  expect_match(report_text, "Sampling Mode: checkpoint-based updates during test execution")
  expect_match(report_text, "Network Interface: eth0")
})

test_that("collect_monitor_snapshot returns expected snapshot structure", {
  env <- load_monitor_env()

  env$read_proc_stat <- function() list(total = 1200, idle = 250)
  env$read_process_cpu_jiffies <- function(pid) 1200
  env$read_net_bytes <- function(interface) list(sent = 1000100, recv = 2000200)
  env$read_mem_percent <- function() 40.0
  env$read_disk_percent <- function() 50.0
  env$read_gpu_metrics <- function() list(util = 10, mem = 256)
  env$read_process_mem_percent <- function(pid) 1.25
  env$compute_network_mbps <- function(prev_sent, prev_recv, curr_sent, curr_recv, elapsed_seconds) {
    list(dl = 8.0, ul = 4.0)
  }
  env$compute_process_cpu_percent <- function(prev_jiffies, curr_jiffies, clock_ticks, elapsed_seconds) {
    50.0
  }

  state <- list(
    pid = 1234,
    interface = "eth0",
    clock_ticks = 100,
    prev_cpu = list(total = 1000, idle = 200),
    prev_proc_jiffies = 1000,
    prev_net = list(sent = 100, recv = 200),
    prev_wall_time = unclass(Sys.time()) - 4.0
  )

  snapshot <- env$collect_monitor_snapshot(state)

  expect_equal(snapshot$cpu, 75.0)
  expect_equal(snapshot$mem, 40.0)
  expect_equal(snapshot$disk, 50.0)
  expect_equal(snapshot$gpu_util, 10)
  expect_equal(snapshot$gpu_mem, 256)
  expect_equal(snapshot$dl, 8.0)
  expect_equal(snapshot$ul, 4.0)
  expect_equal(snapshot$cpu_proc, 50.0)
  expect_equal(snapshot$mem_proc, 1.25)
  expect_equal(snapshot$curr_cpu$total, 1200)
  expect_equal(snapshot$curr_cpu$idle, 250)
  expect_equal(snapshot$curr_proc_jiffies, 1200)
  expect_equal(snapshot$curr_net$sent, 1000100)
  expect_equal(snapshot$curr_net$recv, 2000200)
  expect_true(is.numeric(snapshot$curr_wall_time))
})

test_that("advance_monitor_state writes context and updates state", {
  env <- load_monitor_env()

  report_path <- tempfile(fileext = ".txt")
  con <- file(report_path, open = "wt", encoding = "UTF-8")
  env$RESUME_LOG <- tempfile(fileext = ".log")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  state <- list(
    report_path = report_path,
    report_con = con,
    start_time = Sys.time(),
    pid = 1234,
    interface = "eth0",
    clock_ticks = 100,
    prev_cpu = list(total = 1000, idle = 200),
    prev_proc_jiffies = 1000,
    prev_net = list(sent = 100, recv = 200),
    prev_wall_time = 10.0,
    cycle = 0,
    closed = FALSE,
    script_name = "test_script",
    last_context = NULL
  )

  snapshot <- list(
    cpu = 75.0,
    mem = 40.0,
    disk = 50.0,
    gpu_util = 10,
    gpu_mem = 256,
    dl = 8.0,
    ul = 4.0,
    cpu_proc = 50.0,
    mem_proc = 1.25,
    curr_cpu = list(total = 1200, idle = 250),
    curr_proc_jiffies = 1200,
    curr_net = list(sent = 1000100, recv = 2000200),
    curr_wall_time = 14.0
  )

  updated_state <- env$advance_monitor_state(
    state = state,
    snapshot = snapshot,
    context = "Completed checkpoint test",
    print_console = FALSE
  )

  expect_equal(updated_state$cycle, 1)
  expect_equal(updated_state$prev_cpu$total, 1200)
  expect_equal(updated_state$prev_cpu$idle, 250)
  expect_equal(updated_state$prev_proc_jiffies, 1200)
  expect_equal(updated_state$prev_net$sent, 1000100)
  expect_equal(updated_state$prev_net$recv, 2000200)
  expect_equal(updated_state$prev_wall_time, 14.0)
  expect_equal(updated_state$last_context, "Completed checkpoint test")

  flush(con)
  report_text <- paste(readLines(report_path, warn = FALSE), collapse = "\n")

  expect_match(report_text, "Cycle 1:")
  expect_match(report_text, "Context: Completed checkpoint test")
  expect_match(report_text, "System — CPU: 75\\.0% \\| Mem: 40\\.0% \\| Disk: 50\\.0%")
  expect_match(report_text, "Network— DL: 8\\.00 Mbps \\| UL: 4\\.00 Mbps")
  expect_match(report_text, "Process— CPU: 50\\.0% \\| Mem: 1\\.25%")
})

test_that("update_monitor_state uses collect_monitor_snapshot", {
  env <- load_monitor_env()

  report_path <- tempfile(fileext = ".txt")
  con <- file(report_path, open = "wt", encoding = "UTF-8")
  env$RESUME_LOG <- tempfile(fileext = ".log")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  state <- list(
    report_path = report_path,
    report_con = con,
    start_time = Sys.time(),
    pid = 1234,
    interface = "eth0",
    clock_ticks = 100,
    prev_cpu = list(total = 1000, idle = 200),
    prev_proc_jiffies = 1000,
    prev_net = list(sent = 100, recv = 200),
    prev_wall_time = 10.0,
    cycle = 0,
    closed = FALSE,
    script_name = "test_script",
    last_context = NULL
  )

  snapshot <- list(
    cpu = 75.0,
    mem = 40.0,
    disk = 50.0,
    gpu_util = 10,
    gpu_mem = 256,
    dl = 8.0,
    ul = 4.0,
    cpu_proc = 50.0,
    mem_proc = 1.25,
    curr_cpu = list(total = 1200, idle = 250),
    curr_proc_jiffies = 1200,
    curr_net = list(sent = 1000100, recv = 2000200),
    curr_wall_time = 14.0
  )

  original_collect <- env$collect_monitor_snapshot
  env$collect_monitor_snapshot <- function(state) snapshot

  on.exit(
    {
      env$collect_monitor_snapshot <- original_collect
    },
    add = TRUE
  )

  updated_state <- env$update_monitor_state(
    state = state,
    context = "Collected through update_monitor_state",
    print_console = FALSE
  )

  expect_equal(updated_state$cycle, 1)

  flush(con)
  report_text <- paste(readLines(report_path, warn = FALSE), collapse = "\n")
  expect_match(report_text, "Context: Collected through update_monitor_state")
})

test_that("stop_monitor_state writes footer and closes report connection", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_state_stop_r_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)

  env$OUTPUT_DIR <- tmp_out
  env$RESUME_LOG <- tempfile(fileext = ".log")
  env$get_entry_script_name <- function() "launcher_script"
  env$read_resume_log <- function() invisible(NULL)
  env$get_default_interface <- function() "eth0"
  env$get_clock_ticks <- function() 100
  env$read_proc_stat <- function() list(total = 1000, idle = 200)
  env$read_process_cpu_jiffies <- function(pid) 1000
  env$read_net_bytes <- function(interface) list(sent = 100, recv = 200)

  state <- env$start_monitor_state(
    interval_seconds = 5.0,
    sampling_mode = "checkpoint-based updates during test execution",
    print_start_message = FALSE
  )

  stopped_state <- env$stop_monitor_state(
    state = state,
    print_stop_message = FALSE
  )

  expect_true(stopped_state$closed)
  expect_false(tryCatch(isOpen(stopped_state$report_con), error = function(e) FALSE))

  report_text <- paste(readLines(stopped_state$report_path, warn = FALSE), collapse = "\n")
  expect_match(report_text, "End Time:")
  expect_match(report_text, "Total Duration:")
  expect_match(report_text, "Total Cycles: 0")
})

# ---------------------------------------------------------------------------
# New tests: parse_resume_log, write_resume_log, read_resume_log
# ---------------------------------------------------------------------------

test_that("parse_resume_log returns NULL when file does not exist", {
  env <- load_monitor_env()
  env$RESUME_LOG <- tempfile(fileext = ".log")  # non-existent path

  result <- env$parse_resume_log()
  expect_null(result)
})

test_that("parse_resume_log returns named list from valid file", {
  env <- load_monitor_env()
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  writeLines(
    c(
      "script=query_editions",
      "report=some/path.txt",
      "started=2026-07-13 14:00:00",
      "status=RUNNING",
      "last_context=Completed acquisition for year 1500"
    ),
    log_file
  )

  result <- env$parse_resume_log()

  expect_true(is.list(result))
  expect_equal(result$script, "query_editions")
  expect_equal(result$report, "some/path.txt")
  expect_equal(result$started, "2026-07-13 14:00:00")
  expect_equal(result$status, "RUNNING")
  expect_equal(result$last_context, "Completed acquisition for year 1500")
})

test_that("write_resume_log writes correct fields", {
  env <- load_monitor_env()
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  env$write_resume_log(
    script = "query_editions",
    report_path = "some/path.txt",
    started = as.POSIXct("2026-07-13 14:00:00", tz = "UTC"),
    status = "RUNNING",
    last_context = "year 1500"
  )

  lines <- readLines(log_file, warn = FALSE)

  expect_true(any(grepl("^script=query_editions$", lines)))
  expect_true(any(grepl("^status=RUNNING$", lines)))
  expect_true(any(grepl("^last_context=year 1500$", lines)))
})

test_that("write_resume_log writes COMPLETED with ended", {
  env <- load_monitor_env()
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  env$write_resume_log(
    script = "query_editions",
    report_path = "some/path.txt",
    started = as.POSIXct("2026-07-13 14:00:00", tz = "UTC"),
    status = "COMPLETED",
    ended = as.POSIXct("2026-07-13 16:00:00", tz = "UTC")
  )

  lines <- readLines(log_file, warn = FALSE)

  expect_true(any(grepl("^status=COMPLETED$", lines)))
  expect_true(any(grepl("^ended=", lines)))
})

test_that("read_resume_log returns NULL when no file exists", {
  env <- load_monitor_env()
  env$RESUME_LOG <- tempfile(fileext = ".log")  # non-existent path

  result <- env$read_resume_log()
  expect_null(result)
})

test_that("read_resume_log detects brutal interruption when status is RUNNING", {
  env <- load_monitor_env()
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  writeLines(
    c(
      "script=query_editions",
      "report=some/path.txt",
      "started=2026-07-13 14:00:00",
      "status=RUNNING"
    ),
    log_file
  )

  output <- capture.output(env$read_resume_log())

  expect_true(any(grepl("BRUTALLY INTERRUPTED", output)))
})

test_that("read_resume_log reports INTERRUPTED status", {
  env <- load_monitor_env()
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  writeLines(
    c(
      "script=query_editions",
      "report=some/path.txt",
      "started=2026-07-13 14:00:00",
      "status=INTERRUPTED",
      "ended=2026-07-13 16:00:00"
    ),
    log_file
  )

  output <- capture.output(env$read_resume_log())

  expect_true(any(grepl("INTERRUPTED", output)))
  expect_true(any(grepl("2026-07-13 16:00:00", output)))
})

# ---------------------------------------------------------------------------
# New tests: write_report_header with resume_info
# ---------------------------------------------------------------------------

test_that("write_report_header includes previous run block when resume_info is provided", {
  env <- load_monitor_env()

  tmp_file <- tempfile(fileext = ".txt")
  con <- file(tmp_file, open = "wt", encoding = "UTF-8")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  env$get_entry_script_name <- function() "launcher_script"

  env$write_report_header(
    con = con,
    start_time = as.POSIXct("2026-07-13 14:00:00", tz = "UTC"),
    interval_seconds = 5.0,
    interface_name = "eth0",
    sampling_mode = "checkpoint-based updates during test execution",
    resume_info = list(
      script = "query_editions",
      report = "some/path.txt",
      started = "2026-07-13 14:00:00",
      status = "INTERRUPTED",
      last_context = "Completed acquisition for year 1500",
      ended = "2026-07-13 16:00:00"
    )
  )

  flush(con)
  report_text <- paste(readLines(tmp_file, warn = FALSE), collapse = "\n")

  expect_match(report_text, "Previous run detected")
  expect_match(report_text, "query_editions")
  expect_match(report_text, "INTERRUPTED")
  expect_match(report_text, "year 1500")
})

test_that("write_report_header marks BRUTALLY INTERRUPTED when status is RUNNING", {
  env <- load_monitor_env()

  tmp_file <- tempfile(fileext = ".txt")
  con <- file(tmp_file, open = "wt", encoding = "UTF-8")

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  env$get_entry_script_name <- function() "launcher_script"

  env$write_report_header(
    con = con,
    start_time = as.POSIXct("2026-07-13 14:00:00", tz = "UTC"),
    interval_seconds = 5.0,
    interface_name = "eth0",
    sampling_mode = "checkpoint-based updates during test execution",
    resume_info = list(
      script = "query_editions",
      report = "some/path.txt",
      started = "2026-07-13 14:00:00",
      status = "RUNNING"
    )
  )

  flush(con)
  report_text <- paste(readLines(tmp_file, warn = FALSE), collapse = "\n")

  expect_match(report_text, "BRUTALLY INTERRUPTED")
})

# ---------------------------------------------------------------------------
# New tests: start/advance/stop integration with resume log
# ---------------------------------------------------------------------------

test_that("start_monitor_state writes RUNNING status to resume log", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_state_resume_start_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)
  log_file <- tempfile(fileext = ".log")

  env$OUTPUT_DIR <- tmp_out
  env$RESUME_LOG <- log_file
  env$get_entry_script_name <- function() "launcher_script"
  env$read_resume_log <- function() invisible(NULL)
  env$get_default_interface <- function() "eth0"
  env$get_clock_ticks <- function() 100
  env$read_proc_stat <- function() list(total = 1000, idle = 200)
  env$read_process_cpu_jiffies <- function(pid) 1000
  env$read_net_bytes <- function(interface) list(sent = 100, recv = 200)

  state <- env$start_monitor_state(
    interval_seconds = 5.0,
    sampling_mode = "checkpoint-based updates during test execution",
    print_start_message = FALSE
  )

  on.exit(
    {
      env$stop_monitor_state(state, print_stop_message = FALSE)
    },
    add = TRUE
  )

  expect_true(file.exists(log_file))
  lines <- readLines(log_file, warn = FALSE)
  expect_true(any(grepl("^status=RUNNING$", lines)))
  expect_true(any(grepl("^script=launcher_script$", lines)))
})

test_that("advance_monitor_state updates last_context in state and in resume log", {
  env <- load_monitor_env()

  report_path <- tempfile(fileext = ".txt")
  con <- file(report_path, open = "wt", encoding = "UTF-8")
  log_file <- tempfile(fileext = ".log")
  env$RESUME_LOG <- log_file

  on.exit(
    {
      env$safe_close_connection(con)
    },
    add = TRUE
  )

  state <- list(
    report_path = report_path,
    report_con = con,
    start_time = Sys.time(),
    pid = 1234,
    interface = "eth0",
    clock_ticks = 100,
    prev_cpu = list(total = 1000, idle = 200),
    prev_proc_jiffies = 1000,
    prev_net = list(sent = 100, recv = 200),
    prev_wall_time = 10.0,
    cycle = 0,
    closed = FALSE,
    script_name = "test_script",
    last_context = NULL
  )

  snapshot <- list(
    cpu = 75.0,
    mem = 40.0,
    disk = 50.0,
    gpu_util = 10,
    gpu_mem = 256,
    dl = 8.0,
    ul = 4.0,
    cpu_proc = 50.0,
    mem_proc = 1.25,
    curr_cpu = list(total = 1200, idle = 250),
    curr_proc_jiffies = 1200,
    curr_net = list(sent = 1000100, recv = 2000200),
    curr_wall_time = 14.0
  )

  updated_state <- env$advance_monitor_state(
    state = state,
    snapshot = snapshot,
    context = "Year 1500 done",
    print_console = FALSE
  )

  expect_equal(updated_state$last_context, "Year 1500 done")

  expect_true(file.exists(log_file))
  lines <- readLines(log_file, warn = FALSE)
  expect_true(any(grepl("^last_context=Year 1500 done$", lines)))
})

test_that("stop_monitor_state writes INTERRUPTED status when requested", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_state_interrupted_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)
  log_file <- tempfile(fileext = ".log")

  env$OUTPUT_DIR <- tmp_out
  env$RESUME_LOG <- log_file
  env$get_entry_script_name <- function() "launcher_script"
  env$read_resume_log <- function() invisible(NULL)
  env$get_default_interface <- function() "eth0"
  env$get_clock_ticks <- function() 100
  env$read_proc_stat <- function() list(total = 1000, idle = 200)
  env$read_process_cpu_jiffies <- function(pid) 1000
  env$read_net_bytes <- function(interface) list(sent = 100, recv = 200)

  state <- env$start_monitor_state(
    interval_seconds = 5.0,
    sampling_mode = "checkpoint-based updates during test execution",
    print_start_message = FALSE
  )

  env$stop_monitor_state(state, print_stop_message = FALSE, status = "INTERRUPTED")

  lines <- readLines(log_file, warn = FALSE)
  expect_true(any(grepl("^status=INTERRUPTED$", lines)))
})

test_that("stop_monitor_state writes COMPLETED status by default", {
  env <- load_monitor_env()

  tmp_out <- tempfile("monitor_state_completed_")
  dir.create(tmp_out, recursive = TRUE, showWarnings = FALSE)
  log_file <- tempfile(fileext = ".log")

  env$OUTPUT_DIR <- tmp_out
  env$RESUME_LOG <- log_file
  env$get_entry_script_name <- function() "launcher_script"
  env$read_resume_log <- function() invisible(NULL)
  env$get_default_interface <- function() "eth0"
  env$get_clock_ticks <- function() 100
  env$read_proc_stat <- function() list(total = 1000, idle = 200)
  env$read_process_cpu_jiffies <- function(pid) 1000
  env$read_net_bytes <- function(interface) list(sent = 100, recv = 200)

  state <- env$start_monitor_state(
    interval_seconds = 5.0,
    sampling_mode = "checkpoint-based updates during test execution",
    print_start_message = FALSE
  )

  env$stop_monitor_state(state, print_stop_message = FALSE)

  lines <- readLines(log_file, warn = FALSE)
  expect_true(any(grepl("^status=COMPLETED$", lines)))
})