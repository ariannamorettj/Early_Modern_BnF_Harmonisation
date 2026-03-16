#!/usr/bin/env python3

import os
import sys
import time
import subprocess
from datetime import datetime
import __main__

RESUME_LOG = "resume_info.log"
OUTPUT_DIR = "00_monitor/report"


def get_entry_script_name():
    """
    Returns the basename (without extension) of the top-level script
    that started the current process.
    """
    main_file = getattr(__main__, "__file__", None)

    if main_file:
        return os.path.splitext(os.path.basename(main_file))[0]

    if sys.argv and sys.argv[0]:
        return os.path.splitext(os.path.basename(sys.argv[0]))[0]

    return "interactive_session"


def create_report_file():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caller_name = get_entry_script_name()
    filename = f"{caller_name}_{timestamp}_py.txt"
    return os.path.join(OUTPUT_DIR, filename)


def read_resume_log():
    if os.path.exists(RESUME_LOG):
        with open(RESUME_LOG, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                print(f"\n[RESUME] {content}\n")


def read_proc_stat():
    with open("/proc/stat", "r", encoding="utf-8") as f:
        first_line = f.readline().strip()

    parts = first_line.split()
    values = [int(x) for x in parts[1:]]

    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values[:8]) if len(values) >= 8 else sum(values)

    return total, idle


def compute_system_cpu_percent(prev_total, prev_idle, curr_total, curr_idle):
    delta_total = curr_total - prev_total
    delta_idle = curr_idle - prev_idle

    if delta_total <= 0:
        return 0.0

    return max(0.0, min(100.0, (1.0 - (delta_idle / delta_total)) * 100.0))


def read_mem_percent():
    mem_total_kb = None
    mem_available_kb = None

    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_available_kb = int(line.split()[1])

            if mem_total_kb is not None and mem_available_kb is not None:
                break

    if not mem_total_kb or mem_available_kb is None:
        return 0.0

    used_kb = mem_total_kb - mem_available_kb
    return (used_kb / mem_total_kb) * 100.0


def read_disk_percent():
    try:
        result = subprocess.run(
            ["df", "-P", "/"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return 0.0

        parts = lines[1].split()
        return float(parts[4].rstrip("%"))
    except Exception:
        return 0.0


def get_default_interface():
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as f:
            next(f)
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    return parts[0]
    except Exception:
        pass

    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            lines = f.readlines()[2:]
            for line in lines:
                iface = line.split(":")[0].strip()
                if iface != "lo":
                    return iface
    except Exception:
        pass

    return None


def read_net_bytes(interface):
    if not interface:
        return 0, 0

    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            lines = f.readlines()[2:]

        for line in lines:
            if line.strip().startswith(interface + ":"):
                _, data = line.split(":", 1)
                parts = data.split()
                bytes_recv = int(parts[0])
                bytes_sent = int(parts[8])
                return bytes_sent, bytes_recv
    except Exception:
        pass

    return 0, 0


def compute_network_mbps(prev_sent, prev_recv, curr_sent, curr_recv, elapsed_seconds):
    if elapsed_seconds <= 0:
        return 0.0, 0.0

    delta_sent = max(0, curr_sent - prev_sent)
    delta_recv = max(0, curr_recv - prev_recv)

    ul_mbps = (delta_sent * 8.0) / elapsed_seconds / 1e6
    dl_mbps = (delta_recv * 8.0) / elapsed_seconds / 1e6

    return dl_mbps, ul_mbps


def read_gpu_metrics():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        first_line = result.stdout.strip().splitlines()[0]
        parts = [x.strip() for x in first_line.split(",")]
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def read_process_cpu_jiffies(pid):
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            content = f.read().strip()

        rparen = content.rfind(")")
        tail = content[rparen + 2:].split()

        utime = int(tail[11])
        stime = int(tail[12])

        return utime + stime
    except Exception:
        return 0


def read_process_mem_percent(pid):
    try:
        mem_total_kb = None
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break

        if not mem_total_kb:
            return 0.0

        rss_kb = None
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break

        if rss_kb is None:
            return 0.0

        return (rss_kb / mem_total_kb) * 100.0
    except Exception:
        return 0.0


def compute_process_cpu_percent(prev_jiffies, curr_jiffies, clock_ticks, elapsed_seconds):
    if elapsed_seconds <= 0 or clock_ticks <= 0:
        return 0.0

    delta_jiffies = max(0, curr_jiffies - prev_jiffies)
    cpu_seconds = delta_jiffies / clock_ticks

    return (cpu_seconds / elapsed_seconds) * 100.0


def safe_close_file(file_obj):
    if file_obj is None:
        return False

    if not getattr(file_obj, "closed", True):
        file_obj.close()

    return True


def write_report_header(
    file_obj,
    start_time,
    interface_name,
    interval_seconds=None,
    sampling_mode=None,
):
    file_obj.write("=" * 70 + "\n")
    file_obj.write("SYSTEM MONITORING REPORT - PYTHON\n")
    file_obj.write("=" * 70 + "\n\n")
    file_obj.write(f"Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    file_obj.write(f"Entry Script: {get_entry_script_name()}\n")
    file_obj.write(f"PID: {os.getpid()}\n")

    if interval_seconds is not None:
        file_obj.write(f"Sampling Interval: {interval_seconds:.2f} seconds\n")

    if sampling_mode:
        file_obj.write(f"Sampling Mode: {sampling_mode}\n")

    file_obj.write(f"Network Interface: {interface_name if interface_name else 'unavailable'}\n")
    file_obj.write("Network Speed Source: passive delta from /proc/net/dev\n")
    file_obj.write("\n" + "-" * 70 + "\n\n")
    file_obj.flush()


def write_metrics_to_report(
    file_obj,
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
    context=None,
):
    file_obj.write(f"Cycle {cycle}:\n")

    if context:
        file_obj.write(f"  Context: {context}\n")

    file_obj.write(f"  System — CPU: {cpu:.1f}% | Mem: {mem:.1f}% | Disk: {disk:.1f}%\n")
    file_obj.write(f"  GPU    — Util: {int(round(gpu_util))}% | Mem: {int(round(gpu_mem))} MB\n")
    file_obj.write(f"  Network— DL: {dl:.2f} Mbps | UL: {ul:.2f} Mbps\n")
    file_obj.write(f"  Process— CPU: {cpu_proc:.1f}% | Mem: {mem_proc:.2f}%\n")
    file_obj.write("\n")
    file_obj.flush()


def write_report_footer(file_obj, start_time, end_time, cycle):
    duration = (end_time - start_time).total_seconds()

    file_obj.write("-" * 70 + "\n\n")
    file_obj.write(f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    file_obj.write(f"Total Duration: {duration:.2f} seconds\n")
    file_obj.write(f"Total Cycles: {cycle}\n")
    file_obj.write("\n" + "=" * 70 + "\n")
    file_obj.flush()


def start_monitor_state(interval_seconds=None, sampling_mode=None, print_start_message=True):
    read_resume_log()

    report_path = create_report_file()
    start_time = datetime.now()
    pid = os.getpid()
    interface = get_default_interface()
    clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    prev_total, prev_idle = read_proc_stat()
    prev_proc_jiffies = read_process_cpu_jiffies(pid)
    prev_sent, prev_recv = read_net_bytes(interface)
    prev_wall_time = time.monotonic()

    report_file = open(report_path, "w", encoding="utf-8")

    write_report_header(
        file_obj=report_file,
        start_time=start_time,
        interface_name=interface,
        interval_seconds=interval_seconds,
        sampling_mode=sampling_mode,
    )

    if print_start_message:
        print("Starting system monitor...")
        print(f"Report will be saved to: {report_path}")

    return {
        "report_path": report_path,
        "report_file": report_file,
        "start_time": start_time,
        "pid": pid,
        "interface": interface,
        "clock_ticks": clock_ticks,
        "prev_total": prev_total,
        "prev_idle": prev_idle,
        "prev_proc_jiffies": prev_proc_jiffies,
        "prev_sent": prev_sent,
        "prev_recv": prev_recv,
        "prev_wall_time": prev_wall_time,
        "cycle": 0,
        "closed": False,
    }


def collect_monitor_snapshot(state):
    curr_wall_time = time.monotonic()
    elapsed = max(curr_wall_time - state["prev_wall_time"], 1e-9)

    curr_total, curr_idle = read_proc_stat()
    curr_proc_jiffies = read_process_cpu_jiffies(state["pid"])
    curr_sent, curr_recv = read_net_bytes(state["interface"])

    cpu = compute_system_cpu_percent(
        state["prev_total"],
        state["prev_idle"],
        curr_total,
        curr_idle,
    )
    mem = read_mem_percent()
    disk = read_disk_percent()
    gpu_util, gpu_mem = read_gpu_metrics()
    dl, ul = compute_network_mbps(
        state["prev_sent"],
        state["prev_recv"],
        curr_sent,
        curr_recv,
        elapsed,
    )
    cpu_proc = compute_process_cpu_percent(
        state["prev_proc_jiffies"],
        curr_proc_jiffies,
        state["clock_ticks"],
        elapsed,
    )
    mem_proc = read_process_mem_percent(state["pid"])

    return {
        "cpu": cpu,
        "mem": mem,
        "disk": disk,
        "gpu_util": gpu_util,
        "gpu_mem": gpu_mem,
        "dl": dl,
        "ul": ul,
        "cpu_proc": cpu_proc,
        "mem_proc": mem_proc,
        "curr_total": curr_total,
        "curr_idle": curr_idle,
        "curr_proc_jiffies": curr_proc_jiffies,
        "curr_sent": curr_sent,
        "curr_recv": curr_recv,
        "curr_wall_time": curr_wall_time,
    }


def advance_monitor_state(state, snapshot, context=None, print_console=True):
    if state["closed"]:
        raise RuntimeError("Cannot update a closed monitor state.")

    cycle = state["cycle"] + 1

    if print_console:
        if context:
            print(f"[MONITOR] {context}")

        print(f"System — CPU: {snapshot['cpu']:.1f}% | Mem: {snapshot['mem']:.1f}% | Disk: {snapshot['disk']:.1f}%")
        print(f"GPU    — Util: {int(round(snapshot['gpu_util']))}% | Mem: {int(round(snapshot['gpu_mem']))} MB")
        print(f"Network— DL: {snapshot['dl']:.2f} Mbps | UL: {snapshot['ul']:.2f} Mbps")
        print(f"Process— CPU: {snapshot['cpu_proc']:.1f}% | Mem: {snapshot['mem_proc']:.2f}%")
        print("-" * 60)

    write_metrics_to_report(
        file_obj=state["report_file"],
        cycle=cycle,
        cpu=snapshot["cpu"],
        mem=snapshot["mem"],
        disk=snapshot["disk"],
        gpu_util=snapshot["gpu_util"],
        gpu_mem=snapshot["gpu_mem"],
        dl=snapshot["dl"],
        ul=snapshot["ul"],
        cpu_proc=snapshot["cpu_proc"],
        mem_proc=snapshot["mem_proc"],
        context=context,
    )

    state["prev_total"] = snapshot["curr_total"]
    state["prev_idle"] = snapshot["curr_idle"]
    state["prev_proc_jiffies"] = snapshot["curr_proc_jiffies"]
    state["prev_sent"] = snapshot["curr_sent"]
    state["prev_recv"] = snapshot["curr_recv"]
    state["prev_wall_time"] = snapshot["curr_wall_time"]
    state["cycle"] = cycle

    return state


def update_monitor_state(state, context=None, print_console=True):
    snapshot = collect_monitor_snapshot(state)
    return advance_monitor_state(
        state=state,
        snapshot=snapshot,
        context=context,
        print_console=print_console,
    )


def stop_monitor_state(state, print_stop_message=True):
    if state is None or state["closed"]:
        return state

    end_time = datetime.now()

    write_report_footer(
        file_obj=state["report_file"],
        start_time=state["start_time"],
        end_time=end_time,
        cycle=state["cycle"],
    )

    safe_close_file(state["report_file"])
    state["closed"] = True

    if print_stop_message:
        print(f"\nMonitoring stopped. Report saved to: {state['report_path']}")

    return state


def monitor_system(interval=5.0):
    state = start_monitor_state(
        interval_seconds=interval,
        sampling_mode=None,
        print_start_message=True,
    )

    try:
        while True:
            time.sleep(interval)
            state = update_monitor_state(
                state=state,
                context=None,
                print_console=True,
            )
    except KeyboardInterrupt:
        state = stop_monitor_state(
            state=state,
            print_stop_message=True,
        )
    finally:
        if state is not None and not state["closed"]:
            safe_close_file(state["report_file"])


if __name__ == "__main__":
    monitor_system()