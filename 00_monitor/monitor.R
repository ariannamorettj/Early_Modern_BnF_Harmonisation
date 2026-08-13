#!/usr/bin/env Rscript

RESUME_LOG <- "resume_info.log"
OUTPUT_DIR <- "00_monitor/report"

IS_WINDOWS <- .Platform$OS.type == "windows"

run_powershell <- function(script) {
  tryCatch(
    system2(
      "powershell",
      c("-NoProfile", "-NonInteractive", "-Command", script),
      stdout = TRUE,
      stderr = FALSE
    ),
    error = function(e) character(0)
  )
}

# On Windows, each of read_proc_stat/read_mem_percent/read_disk_percent/
# read_net_bytes/read_process_cpu_jiffies/read_process_mem_percent spawns its
# own powershell.exe process. Called once per monitoring cycle each, that is
# 6 subprocess spawns + WMI/CIM queries per cycle - with runs sampling once
# per year/actor (hundreds to hundreds of thousands of cycles), this adds up
# to a large, avoidable share of total wall-clock time. All 6 metrics are
# fetched together in a single PowerShell invocation and cached for a short
# TTL, so the 5 calls that follow the first one in the same cycle reuse it
# instead of spawning their own process. The cache is intentionally
# time-based (not tied to collect_monitor_snapshot's call sequence) so it
# needs no changes to collect_monitor_snapshot and cannot go stale across
# real monitoring cycles, which are always well over a second apart.
.monitor_runtime_state <- new.env(parent = emptyenv())
WINDOWS_METRICS_CACHE_TTL <- 3.0

set_current_interface <- function(interface) {
  assign("interface", interface, envir = .monitor_runtime_state)
}

get_current_interface <- function() {
  if (exists("interface", envir = .monitor_runtime_state, inherits = FALSE)) {
    get("interface", envir = .monitor_runtime_state, inherits = FALSE)
  } else {
    NULL
  }
}

read_windows_metrics_once <- function(pid, drive, interface) {
  net_line <- if (!is.null(interface) && nzchar(interface)) {
    sprintf(
      "$net = Get-NetAdapterStatistics -Name '%s' -ErrorAction SilentlyContinue",
      interface
    )
  } else {
    "$net = $null"
  }

  script <- paste(
    "$cpu = Get-CimInstance Win32_PerfRawData_PerfOS_Processor | Where-Object { $_.Name -eq '_Total' }",
    "$os = Get-CimInstance Win32_OperatingSystem",
    sprintf(
      "$disk = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -eq '%s' }",
      drive
    ),
    net_line,
    sprintf(
      "$proc = Get-CimInstance Win32_PerfRawData_PerfProc_Process | Where-Object { $_.IDProcess -eq %d }",
      pid
    ),
    sprintf(
      "$procMem = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq %d }",
      pid
    ),
    paste0(
      "'{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}|{9}' -f ",
      "$cpu.Timestamp_Sys100NS,$cpu.PercentIdleTime,",
      "$os.TotalVisibleMemorySize,$os.FreePhysicalMemory,",
      "$disk.Size,$disk.FreeSpace,",
      "$net.SentBytes,$net.ReceivedBytes,",
      "$proc.PercentProcessorTime,$procMem.WorkingSetSize"
    ),
    sep = "; "
  )

  out <- run_powershell(script)

  as_num <- function(x) {
    v <- suppressWarnings(as.numeric(x))
    if (length(v) == 0 || is.na(v)) 0 else v
  }

  empty_bundle <- list(
    cpu_total = 0, cpu_idle = 0, mem_total_kb = 0, mem_free_kb = 0,
    disk_size = 0, disk_free = 0, net_sent = 0, net_recv = 0,
    proc_cpu_raw = 0, proc_working_set = 0
  )

  if (length(out) == 0) {
    return(empty_bundle)
  }

  parts <- strsplit(trimws(out[1]), "\\|")[[1]]

  if (length(parts) < 10) {
    return(empty_bundle)
  }

  list(
    cpu_total = as_num(parts[1]),
    cpu_idle = as_num(parts[2]),
    mem_total_kb = as_num(parts[3]),
    mem_free_kb = as_num(parts[4]),
    disk_size = as_num(parts[5]),
    disk_free = as_num(parts[6]),
    net_sent = as_num(parts[7]),
    net_recv = as_num(parts[8]),
    proc_cpu_raw = as_num(parts[9]),
    proc_working_set = as_num(parts[10])
  )
}

get_windows_metrics_bundle <- function() {
  cached_at <- if (exists("cached_at", envir = .monitor_runtime_state, inherits = FALSE)) {
    get("cached_at", envir = .monitor_runtime_state, inherits = FALSE)
  } else {
    -Inf
  }

  # cached_at must be stamped *after* the fetch completes, not before: the
  # fetch itself (a single PowerShell process running ~6 CIM/adapter
  # queries) takes over a second even warm, so timestamping at the start
  # made the cache look stale to the very next call in the same cycle -
  # each of the 6 read_* calls ended up doing its own full fetch, which is
  # exactly the 6-spawns-per-cycle cost this cache exists to avoid.
  if ((unclass(Sys.time()) - cached_at) > WINDOWS_METRICS_CACHE_TTL) {
    data <- read_windows_metrics_once(
      pid = Sys.getpid(),
      drive = substr(normalizePath(getwd()), 1, 2),
      interface = get_current_interface()
    )

    assign("windows_metrics", data, envir = .monitor_runtime_state)
    assign("cached_at", unclass(Sys.time()), envir = .monitor_runtime_state)
  }

  get("windows_metrics", envir = .monitor_runtime_state, inherits = FALSE)
}

get_entry_script_name <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)

  if (length(file_arg) > 0) {
    script_path <- sub("^--file=", "", file_arg[1])
    return(tools::file_path_sans_ext(basename(script_path)))
  }

  return("interactive_session")
}

create_report_file <- function() {
  dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
  timestamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
  caller_name <- get_entry_script_name()
  file.path(OUTPUT_DIR, sprintf("%s_%s_R.txt", caller_name, timestamp))
}

parse_resume_log <- function() {
  if (!file.exists(RESUME_LOG)) return(NULL)
  lines <- readLines(RESUME_LOG, warn = FALSE)
  if (length(lines) == 0) return(NULL)
  result <- list()
  for (line in lines) {
    sep <- regexpr("=", line)
    if (sep == -1) next
    key <- trimws(substr(line, 1, sep - 1))
    val <- trimws(substr(line, sep + 1, nchar(line)))
    if (nzchar(key)) result[[key]] <- val
  }
  if (length(result) == 0) return(NULL)
  result
}

write_resume_log <- function(script, report_path, started, status, last_context = NULL, ended = NULL) {
  lines <- c(
    paste0("script=", script),
    paste0("report=", report_path),
    paste0("started=", format(started, "%Y-%m-%d %H:%M:%S")),
    paste0("status=", status)
  )
  if (!is.null(last_context) && nzchar(last_context)) {
    lines <- c(lines, paste0("last_context=", last_context))
  }
  if (!is.null(ended)) {
    lines <- c(lines, paste0("ended=", format(ended, "%Y-%m-%d %H:%M:%S")))
  }
  writeLines(lines, RESUME_LOG)
}

read_resume_log <- function() {
  info <- parse_resume_log()
  if (is.null(info)) return(invisible(NULL))

  prev_status <- if (!is.null(info$status)) info$status else "UNKNOWN"
  brutally_interrupted <- identical(prev_status, "RUNNING")

  cat("\n[RESUME] Previous run detected:\n")
  if (!is.null(info$script))       cat(sprintf("  Script:          %s\n", info$script))
  if (!is.null(info$report))       cat(sprintf("  Report:          %s\n", info$report))
  if (!is.null(info$started))      cat(sprintf("  Started:         %s\n", info$started))
  if (!is.null(info$last_context)) cat(sprintf("  Last checkpoint: %s\n", info$last_context))
  if (brutally_interrupted) {
    cat("  Status:          BRUTALLY INTERRUPTED (no clean exit detected)\n")
  } else {
    cat(sprintf("  Status:          %s\n", prev_status))
    if (!is.null(info$ended)) cat(sprintf("  Ended:           %s\n", info$ended))
  }
  cat("\n")

  invisible(info)
}

read_proc_stat <- function() {
  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()
    return(list(total = m$cpu_total, idle = m$cpu_idle))
  }

  line <- readLines("/proc/stat", n = 1, warn = FALSE)
  parts <- strsplit(trimws(line), "\\s+")[[1]]
  values <- as.numeric(parts[-1])

  idle <- values[4] + ifelse(length(values) >= 5, values[5], 0)
  total <- if (length(values) >= 8) sum(values[1:8]) else sum(values)

  list(total = total, idle = idle)
}

compute_system_cpu_percent <- function(prev_total, prev_idle, curr_total, curr_idle) {
  delta_total <- curr_total - prev_total
  delta_idle <- curr_idle - prev_idle

  if (delta_total <= 0) {
    return(0.0)
  }

  pct <- (1 - (delta_idle / delta_total)) * 100
  max(0.0, min(100.0, pct))
}

read_mem_percent <- function() {
  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()

    if (m$mem_total_kb <= 0) {
      return(0.0)
    }

    return(((m$mem_total_kb - m$mem_free_kb) / m$mem_total_kb) * 100)
  }

  lines <- readLines("/proc/meminfo", warn = FALSE)

  mem_total_line <- grep("^MemTotal:", lines, value = TRUE)
  mem_available_line <- grep("^MemAvailable:", lines, value = TRUE)

  if (length(mem_total_line) == 0 || length(mem_available_line) == 0) {
    return(0.0)
  }

  mem_total_kb <- as.numeric(strsplit(trimws(mem_total_line), "\\s+")[[1]][2])
  mem_available_kb <- as.numeric(strsplit(trimws(mem_available_line), "\\s+")[[1]][2])

  used_kb <- mem_total_kb - mem_available_kb
  (used_kb / mem_total_kb) * 100
}

read_disk_percent <- function() {
  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()

    if (m$disk_size <= 0) {
      return(0.0)
    }

    return(((m$disk_size - m$disk_free) / m$disk_size) * 100)
  }

  out <- tryCatch(
    system("df -P / | tail -1", intern = TRUE),
    error = function(e) character(0)
  )

  if (length(out) == 0) {
    return(0.0)
  }

  parts <- strsplit(trimws(out), "\\s+")[[1]]
  as.numeric(sub("%", "", parts[5]))
}

get_default_interface <- function() {
  if (IS_WINDOWS) {
    out <- run_powershell(
      "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty InterfaceAlias"
    )

    if (length(out) == 0 || !nzchar(trimws(out[1]))) {
      return(NULL)
    }

    return(trimws(out[1]))
  }

  route_lines <- tryCatch(
    readLines("/proc/net/route", warn = FALSE),
    error = function(e) character(0)
  )

  if (length(route_lines) > 1) {
    for (line in route_lines[-1]) {
      parts <- strsplit(trimws(line), "\\s+")[[1]]
      if (length(parts) >= 2 && parts[2] == "00000000") {
        return(parts[1])
      }
    }
  }

  dev_lines <- tryCatch(
    readLines("/proc/net/dev", warn = FALSE),
    error = function(e) character(0)
  )

  if (length(dev_lines) > 2) {
    for (line in dev_lines[-c(1, 2)]) {
      iface <- trimws(strsplit(line, ":")[[1]][1])
      if (!identical(iface, "lo")) {
        return(iface)
      }
    }
  }

  NULL
}

read_net_bytes <- function(interface) {
  if (is.null(interface) || !nzchar(interface)) {
    return(list(sent = 0, recv = 0))
  }

  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()
    return(list(sent = m$net_sent, recv = m$net_recv))
  }

  lines <- tryCatch(
    readLines("/proc/net/dev", warn = FALSE),
    error = function(e) character(0)
  )

  target <- grep(sprintf("^\\s*%s:", interface), lines, value = TRUE)

  if (length(target) == 0) {
    return(list(sent = 0, recv = 0))
  }

  payload <- trimws(strsplit(target[1], ":")[[1]][2])
  parts <- strsplit(payload, "\\s+")[[1]]

  bytes_recv <- as.numeric(parts[1])
  bytes_sent <- as.numeric(parts[9])

  list(sent = bytes_sent, recv = bytes_recv)
}

compute_network_mbps <- function(prev_sent, prev_recv, curr_sent, curr_recv, elapsed_seconds) {
  if (elapsed_seconds <= 0) {
    return(list(dl = 0.0, ul = 0.0))
  }

  delta_sent <- max(0, curr_sent - prev_sent)
  delta_recv <- max(0, curr_recv - prev_recv)

  ul_mbps <- (delta_sent * 8) / elapsed_seconds / 1e6
  dl_mbps <- (delta_recv * 8) / elapsed_seconds / 1e6

  list(dl = dl_mbps, ul = ul_mbps)
}

read_gpu_metrics <- function() {
  out <- tryCatch(
    system2(
      "nvidia-smi",
      args = c(
        "--query-gpu=utilization.gpu,memory.used",
        "--format=csv,noheader,nounits"
      ),
      stdout = TRUE,
      stderr = FALSE
    ),
    error = function(e) character(0)
  )

  if (length(out) == 0) {
    return(list(util = 0, mem = 0))
  }

  parts <- trimws(strsplit(out[1], ",")[[1]])

  util <- suppressWarnings(as.numeric(parts[1]))
  mem <- suppressWarnings(as.numeric(parts[2]))

  if (is.na(util)) util <- 0
  if (is.na(mem)) mem <- 0

  list(util = util, mem = mem)
}

read_process_cpu_jiffies <- function(pid) {
  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()
    return(m$proc_cpu_raw)
  }

  path <- sprintf("/proc/%d/stat", pid)
  line <- tryCatch(
    readLines(path, n = 1, warn = FALSE),
    error = function(e) character(0)
  )

  if (length(line) == 0) {
    return(0)
  }

  close_paren_pos <- max(gregexpr("\\)", line[1])[[1]])
  tail_part <- trimws(substr(line[1], close_paren_pos + 1, nchar(line[1])))
  parts <- strsplit(tail_part, "\\s+")[[1]]

  utime <- suppressWarnings(as.numeric(parts[12]))
  stime <- suppressWarnings(as.numeric(parts[13]))

  if (is.na(utime)) utime <- 0
  if (is.na(stime)) stime <- 0

  utime + stime
}

read_process_mem_percent <- function(pid) {
  if (IS_WINDOWS) {
    m <- get_windows_metrics_bundle()

    if (m$mem_total_kb <= 0) {
      return(0.0)
    }

    return((m$proc_working_set / (m$mem_total_kb * 1024)) * 100)
  }

  status_path <- sprintf("/proc/%d/status", pid)
  status_lines <- tryCatch(
    readLines(status_path, warn = FALSE),
    error = function(e) character(0)
  )
  meminfo_lines <- tryCatch(
    readLines("/proc/meminfo", warn = FALSE),
    error = function(e) character(0)
  )

  if (length(status_lines) == 0 || length(meminfo_lines) == 0) {
    return(0.0)
  }

  rss_line <- grep("^VmRSS:", status_lines, value = TRUE)
  mem_total_line <- grep("^MemTotal:", meminfo_lines, value = TRUE)

  if (length(rss_line) == 0 || length(mem_total_line) == 0) {
    return(0.0)
  }

  rss_kb <- as.numeric(strsplit(trimws(rss_line[1]), "\\s+")[[1]][2])
  mem_total_kb <- as.numeric(strsplit(trimws(mem_total_line[1]), "\\s+")[[1]][2])

  if (is.na(rss_kb) || is.na(mem_total_kb) || mem_total_kb <= 0) {
    return(0.0)
  }

  (rss_kb / mem_total_kb) * 100
}

get_clock_ticks <- function() {
  if (IS_WINDOWS) {
    return(10000000)  # FILETIME / perf-counter raw units are 100ns intervals
  }

  out <- tryCatch(
    system("getconf CLK_TCK", intern = TRUE),
    error = function(e) character(0)
  )

  if (length(out) == 0) {
    return(100)
  }

  ticks <- suppressWarnings(as.numeric(out[1]))
  if (is.na(ticks) || ticks <= 0) {
    return(100)
  }

  ticks
}

compute_process_cpu_percent <- function(prev_jiffies, curr_jiffies, clock_ticks, elapsed_seconds) {
  if (elapsed_seconds <= 0 || clock_ticks <= 0) {
    return(0.0)
  }

  delta_jiffies <- max(0, curr_jiffies - prev_jiffies)
  cpu_seconds <- delta_jiffies / clock_ticks

  (cpu_seconds / elapsed_seconds) * 100
}

safe_close_connection <- function(con) {
  if (is.null(con)) {
    return(invisible(FALSE))
  }

  is_open <- tryCatch(isOpen(con), error = function(e) FALSE)

  if (isTRUE(is_open)) {
    close(con)
  }

  invisible(TRUE)
}

write_report_header <- function(
  con,
  start_time,
  interval_seconds = NULL,
  interface_name,
  sampling_mode = NULL,
  resume_info = NULL
) {
  writeLines(strrep("=", 70), con)
  writeLines("SYSTEM MONITORING REPORT - R", con)
  writeLines(strrep("=", 70), con)
  writeLines("", con)
  writeLines(sprintf("Start Time: %s", format(start_time, "%Y-%m-%d %H:%M:%S")), con)
  writeLines(sprintf("Entry Script: %s", get_entry_script_name()), con)
  writeLines(sprintf("PID: %d", Sys.getpid()), con)

  if (!is.null(interval_seconds) && is.finite(interval_seconds)) {
    writeLines(sprintf("Sampling Interval: %.2f seconds", interval_seconds), con)
  }

  if (!is.null(sampling_mode) && nzchar(sampling_mode)) {
    writeLines(sprintf("Sampling Mode: %s", sampling_mode), con)
  }

  writeLines(
    sprintf(
      "Network Interface: %s",
      ifelse(is.null(interface_name), "unavailable", interface_name)
    ),
    con
  )
  writeLines("Network Speed Source: passive delta from /proc/net/dev", con)

  if (!is.null(resume_info)) {
    writeLines("", con)
    writeLines(strrep("-", 70), con)
    writeLines("", con)
    writeLines("Previous run detected:", con)
    prev_status <- if (!is.null(resume_info$status)) resume_info$status else "UNKNOWN"
    brutally_interrupted <- identical(prev_status, "RUNNING")
    if (!is.null(resume_info$script))       writeLines(sprintf("  Script:          %s", resume_info$script), con)
    if (!is.null(resume_info$report))       writeLines(sprintf("  Report:          %s", resume_info$report), con)
    if (!is.null(resume_info$started))      writeLines(sprintf("  Started:         %s", resume_info$started), con)
    if (!is.null(resume_info$last_context)) writeLines(sprintf("  Last checkpoint: %s", resume_info$last_context), con)
    if (brutally_interrupted) {
      writeLines("  Status:          BRUTALLY INTERRUPTED (no clean exit detected)", con)
    } else {
      writeLines(sprintf("  Status:          %s", prev_status), con)
      if (!is.null(resume_info$ended)) writeLines(sprintf("  Ended:           %s", resume_info$ended), con)
    }
  }

  writeLines("", con)
  writeLines(strrep("-", 70), con)
  writeLines("", con)
  flush(con)
}

write_metrics_to_report <- function(
  con,
  cycle,
  cpu,
  mem,
  disk,
  gpu_util,
  gpu_mem,
  dl,
  ul,
  cpu_proc,
  mem_proc,
  context = NULL
) {
  writeLines(sprintf("Cycle %d:", cycle), con)

  if (!is.null(context) && nzchar(context)) {
    writeLines(sprintf("  Context: %s", context), con)
  }

  writeLines(sprintf("  System — CPU: %.1f%% | Mem: %.1f%% | Disk: %.1f%%", cpu, mem, disk), con)
  writeLines(sprintf("  GPU    — Util: %d%% | Mem: %d MB", as.integer(round(gpu_util)), as.integer(round(gpu_mem))), con)
  writeLines(sprintf("  Network— DL: %.2f Mbps | UL: %.2f Mbps", dl, ul), con)
  writeLines(sprintf("  Process— CPU: %.1f%% | Mem: %.2f%%", cpu_proc, mem_proc), con)
  writeLines("", con)
  flush(con)
}

write_report_footer <- function(con, start_time, end_time, cycle) {
  duration <- as.numeric(difftime(end_time, start_time, units = "secs"))

  writeLines(strrep("-", 70), con)
  writeLines("", con)
  writeLines(sprintf("End Time: %s", format(end_time, "%Y-%m-%d %H:%M:%S")), con)
  writeLines(sprintf("Total Duration: %.2f seconds", duration), con)
  writeLines(sprintf("Total Cycles: %d", cycle), con)
  writeLines("", con)
  writeLines(strrep("=", 70), con)
  flush(con)
}

start_monitor_state <- function(
  interval_seconds = NULL,
  sampling_mode = NULL,
  print_start_message = TRUE
) {
  resume_info <- read_resume_log()

  report_path <- create_report_file()
  start_time <- Sys.time()
  pid <- Sys.getpid()
  script_name <- get_entry_script_name()
  interface <- get_default_interface()
  set_current_interface(interface)
  clock_ticks <- get_clock_ticks()

  prev_cpu <- read_proc_stat()
  prev_proc_jiffies <- read_process_cpu_jiffies(pid)
  prev_net <- read_net_bytes(interface)
  prev_wall_time <- unclass(Sys.time())

  report_con <- file(report_path, open = "wt", encoding = "UTF-8")

  write_report_header(
    con = report_con,
    start_time = start_time,
    interval_seconds = interval_seconds,
    interface_name = interface,
    sampling_mode = sampling_mode,
    resume_info = resume_info
  )

  write_resume_log(
    script = script_name,
    report_path = report_path,
    started = start_time,
    status = "RUNNING"
  )

  if (isTRUE(print_start_message)) {
    cat("Starting system monitor...\n")
    cat(sprintf("Report will be saved to: %s\n", report_path))
  }

  list(
    report_path = report_path,
    report_con = report_con,
    start_time = start_time,
    pid = pid,
    script_name = script_name,
    interface = interface,
    clock_ticks = clock_ticks,
    prev_cpu = prev_cpu,
    prev_proc_jiffies = prev_proc_jiffies,
    prev_net = prev_net,
    prev_wall_time = prev_wall_time,
    cycle = 0,
    last_context = NULL,
    closed = FALSE
  )
}

collect_monitor_snapshot <- function(state) {
  curr_wall_time <- unclass(Sys.time())
  elapsed <- max(curr_wall_time - state$prev_wall_time, 1e-9)

  curr_cpu <- read_proc_stat()
  curr_proc_jiffies <- read_process_cpu_jiffies(state$pid)
  curr_net <- read_net_bytes(state$interface)

  cpu <- compute_system_cpu_percent(
    state$prev_cpu$total,
    state$prev_cpu$idle,
    curr_cpu$total,
    curr_cpu$idle
  )

  mem <- read_mem_percent()
  disk <- read_disk_percent()
  gpu <- read_gpu_metrics()

  net <- compute_network_mbps(
    state$prev_net$sent,
    state$prev_net$recv,
    curr_net$sent,
    curr_net$recv,
    elapsed
  )

  cpu_proc <- compute_process_cpu_percent(
    state$prev_proc_jiffies,
    curr_proc_jiffies,
    state$clock_ticks,
    elapsed
  )

  mem_proc <- read_process_mem_percent(state$pid)

  list(
    cpu = cpu,
    mem = mem,
    disk = disk,
    gpu_util = gpu$util,
    gpu_mem = gpu$mem,
    dl = net$dl,
    ul = net$ul,
    cpu_proc = cpu_proc,
    mem_proc = mem_proc,
    curr_cpu = curr_cpu,
    curr_proc_jiffies = curr_proc_jiffies,
    curr_net = curr_net,
    curr_wall_time = curr_wall_time
  )
}

advance_monitor_state <- function(
  state,
  snapshot,
  context = NULL,
  print_console = TRUE
) {
  if (isTRUE(state$closed)) {
    stop("Cannot update a closed monitor state.")
  }

  cycle <- state$cycle + 1

  if (isTRUE(print_console)) {
    if (!is.null(context) && nzchar(context)) {
      cat(sprintf("[MONITOR] %s\n", context))
    }

    cat(sprintf("System — CPU: %.1f%% | Mem: %.1f%% | Disk: %.1f%%\n", snapshot$cpu, snapshot$mem, snapshot$disk))
    cat(sprintf("GPU    — Util: %d%% | Mem: %d MB\n", as.integer(round(snapshot$gpu_util)), as.integer(round(snapshot$gpu_mem))))
    cat(sprintf("Network— DL: %.2f Mbps | UL: %.2f Mbps\n", snapshot$dl, snapshot$ul))
    cat(sprintf("Process— CPU: %.1f%% | Mem: %.2f%%\n", snapshot$cpu_proc, snapshot$mem_proc))
    cat(sprintf("%s\n", strrep("-", 60)))
  }

  write_metrics_to_report(
    con = state$report_con,
    cycle = cycle,
    cpu = snapshot$cpu,
    mem = snapshot$mem,
    disk = snapshot$disk,
    gpu_util = snapshot$gpu_util,
    gpu_mem = snapshot$gpu_mem,
    dl = snapshot$dl,
    ul = snapshot$ul,
    cpu_proc = snapshot$cpu_proc,
    mem_proc = snapshot$mem_proc,
    context = context
  )

  state$prev_cpu <- snapshot$curr_cpu
  state$prev_proc_jiffies <- snapshot$curr_proc_jiffies
  state$prev_net <- snapshot$curr_net
  state$prev_wall_time <- snapshot$curr_wall_time
  state$cycle <- cycle

  if (!is.null(context) && nzchar(context)) {
    state$last_context <- context
    write_resume_log(
      script = state$script_name,
      report_path = state$report_path,
      started = state$start_time,
      status = "RUNNING",
      last_context = context
    )
  }

  state
}

update_monitor_state <- function(
  state,
  context = NULL,
  print_console = TRUE
) {
  snapshot <- collect_monitor_snapshot(state)
  advance_monitor_state(
    state = state,
    snapshot = snapshot,
    context = context,
    print_console = print_console
  )
}

stop_monitor_state <- function(
  state,
  print_stop_message = TRUE,
  status = "COMPLETED"
) {
  if (is.null(state) || isTRUE(state$closed)) {
    return(invisible(state))
  }

  end_time <- Sys.time()

  write_report_footer(
    con = state$report_con,
    start_time = state$start_time,
    end_time = end_time,
    cycle = state$cycle
  )

  write_resume_log(
    script = state$script_name,
    report_path = state$report_path,
    started = state$start_time,
    status = status,
    last_context = state$last_context,
    ended = end_time
  )

  safe_close_connection(state$report_con)
  state$closed <- TRUE

  if (isTRUE(print_stop_message)) {
    cat(sprintf("\nMonitoring stopped. Report saved to: %s\n", state$report_path))
  }

  invisible(state)
}

monitor_system <- function(interval = 5) {
  state <- start_monitor_state(
    interval_seconds = interval,
    sampling_mode = NULL,
    print_start_message = TRUE
  )

  on.exit(
    {
      if (!is.null(state) && !isTRUE(state$closed)) {
        safe_close_connection(state$report_con)
      }
    },
    add = TRUE
  )

  tryCatch(
    {
      repeat {
        Sys.sleep(interval)
        state <- update_monitor_state(
          state = state,
          context = NULL,
          print_console = TRUE
        )
      }
    },
    interrupt = function(e) {
      state <<- stop_monitor_state(
        state = state,
        print_stop_message = TRUE
      )
      invisible(NULL)
    }
  )
}

if (sys.nframe() == 0) {
  monitor_system()
}