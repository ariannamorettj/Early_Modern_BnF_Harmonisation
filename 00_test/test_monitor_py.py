import importlib.util
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONITOR_PATH = PROJECT_ROOT / "00_monitor" / "monitor.py"


def load_monitor_module():
    spec = importlib.util.spec_from_file_location("monitor_py", MONITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_monitor_script_exists():
    assert MONITOR_PATH.exists(), f"Monitor script not found at: {MONITOR_PATH}"


def test_create_report_file_uses_caller_name_timestamp_and_py_suffix(tmp_path, monkeypatch):
    monitor = load_monitor_module()

    monkeypatch.setattr(monitor, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "get_entry_script_name", lambda: "launcher_script")

    report_path = monitor.create_report_file()
    report_name = os.path.basename(report_path)

    assert os.path.dirname(report_path) == str(tmp_path)
    assert re.fullmatch(r"launcher_script_\d{8}_\d{6}_py\.txt", report_name)


def test_compute_system_cpu_percent_matches_expected_formula():
    monitor = load_monitor_module()

    cpu_pct = monitor.compute_system_cpu_percent(
        prev_total=1000,
        prev_idle=200,
        curr_total=1200,
        curr_idle=250,
    )

    assert cpu_pct == 75.0


def test_compute_network_mbps_matches_expected_formula():
    monitor = load_monitor_module()

    dl, ul = monitor.compute_network_mbps(
        prev_sent=100,
        prev_recv=200,
        curr_sent=1_000_100,
        curr_recv=2_000_200,
        elapsed_seconds=2.0,
    )

    assert abs(dl - 8.0) < 1e-9
    assert abs(ul - 4.0) < 1e-9


def test_compute_process_cpu_percent_matches_expected_formula():
    monitor = load_monitor_module()

    cpu_pct = monitor.compute_process_cpu_percent(
        prev_jiffies=1000,
        curr_jiffies=1200,
        clock_ticks=100,
        elapsed_seconds=4.0,
    )

    assert cpu_pct == 50.0


def test_safe_close_file_closes_an_open_file(tmp_path):
    monitor = load_monitor_module()

    test_file = tmp_path / "safe_close_test.txt"
    file_obj = open(test_file, "w", encoding="utf-8")
    file_obj.write("test")

    assert file_obj.closed is False
    result = monitor.safe_close_file(file_obj)

    assert result is True
    assert file_obj.closed is True


def test_write_report_header_writes_interval_sampling_mode_and_interface(tmp_path, monkeypatch):
    monitor = load_monitor_module()

    report_path = tmp_path / "header_report.txt"
    report_file = open(report_path, "w", encoding="utf-8")

    monkeypatch.setattr(monitor, "get_entry_script_name", lambda: "launcher_script")
    monkeypatch.setattr(monitor.os, "getpid", lambda: 4321)

    try:
        monitor.write_report_header(
            file_obj=report_file,
            start_time=monitor.datetime(2026, 3, 16, 10, 0, 0),
            interface_name="eth0",
            interval_seconds=5.0,
            sampling_mode="checkpoint-based updates during test execution",
        )

        report_file.flush()
        report_text = report_path.read_text(encoding="utf-8")

        assert "SYSTEM MONITORING REPORT - PYTHON" in report_text
        assert "Start Time: 2026-03-16 10:00:00" in report_text
        assert "Entry Script: launcher_script" in report_text
        assert "PID: 4321" in report_text
        assert "Sampling Interval: 5.00 seconds" in report_text
        assert "Sampling Mode: checkpoint-based updates during test execution" in report_text
        assert "Network Interface: eth0" in report_text
        assert "Network Speed Source: passive delta from /proc/net/dev" in report_text
    finally:
        monitor.safe_close_file(report_file)


def test_write_metrics_to_report_writes_context_and_metrics_block(tmp_path):
    monitor = load_monitor_module()

    report_path = tmp_path / "metrics_report.txt"
    report_file = open(report_path, "w", encoding="utf-8")

    try:
        monitor.write_metrics_to_report(
            file_obj=report_file,
            cycle=1,
            cpu=75.0,
            mem=40.0,
            disk=50.0,
            gpu_util=10,
            gpu_mem=256,
            dl=8.0,
            ul=4.0,
            cpu_proc=50.0,
            mem_proc=1.25,
            context="Completed checkpoint test",
        )

        report_file.flush()
        report_text = report_path.read_text(encoding="utf-8")

        assert "Cycle 1:" in report_text
        assert "Context: Completed checkpoint test" in report_text
        assert "System — CPU: 75.0% | Mem: 40.0% | Disk: 50.0%" in report_text
        assert "GPU    — Util: 10% | Mem: 256 MB" in report_text
        assert "Network— DL: 8.00 Mbps | UL: 4.00 Mbps" in report_text
        assert "Process— CPU: 50.0% | Mem: 1.25%" in report_text
    finally:
        monitor.safe_close_file(report_file)


def test_start_monitor_state_creates_report_and_writes_header(tmp_path, monkeypatch):
    monitor = load_monitor_module()

    monkeypatch.setattr(monitor, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "get_entry_script_name", lambda: "launcher_script")
    monkeypatch.setattr(monitor, "read_resume_log", lambda: None)
    monkeypatch.setattr(monitor, "get_default_interface", lambda: "eth0")
    monkeypatch.setattr(monitor, "read_proc_stat", lambda: (1000, 200))
    monkeypatch.setattr(monitor, "read_process_cpu_jiffies", lambda pid: 1000)
    monkeypatch.setattr(monitor, "read_net_bytes", lambda interface: (100, 200))
    monkeypatch.setattr(monitor, "get_clock_ticks", lambda: 100)

    state = monitor.start_monitor_state(
        interval_seconds=5.0,
        sampling_mode="checkpoint-based updates during test execution",
        print_start_message=False,
    )

    try:
        assert state["cycle"] == 0
        assert state["closed"] is False
        assert state["interface"] == "eth0"
        assert state["clock_ticks"] == 100
        assert Path(state["report_path"]).exists()

        report_text = Path(state["report_path"]).read_text(encoding="utf-8")
        assert "SYSTEM MONITORING REPORT - PYTHON" in report_text
        assert "Entry Script: launcher_script" in report_text
        assert "Sampling Interval: 5.00 seconds" in report_text
        assert "Sampling Mode: checkpoint-based updates during test execution" in report_text
        assert "Network Interface: eth0" in report_text
    finally:
        monitor.stop_monitor_state(state, print_stop_message=False)


def test_collect_monitor_snapshot_returns_expected_snapshot_structure(monkeypatch):
    monitor = load_monitor_module()

    monkeypatch.setattr(monitor.time, "monotonic", lambda: 14.0)
    monkeypatch.setattr(monitor, "read_proc_stat", lambda: (1200, 250))
    monkeypatch.setattr(monitor, "read_process_cpu_jiffies", lambda pid: 1200)
    monkeypatch.setattr(monitor, "read_net_bytes", lambda interface: (1_000_100, 2_000_200))
    monkeypatch.setattr(monitor, "read_mem_percent", lambda: 40.0)
    monkeypatch.setattr(monitor, "read_disk_percent", lambda: 50.0)
    monkeypatch.setattr(monitor, "read_gpu_metrics", lambda: (10, 256))
    monkeypatch.setattr(
        monitor,
        "compute_network_mbps",
        lambda prev_sent, prev_recv, curr_sent, curr_recv, elapsed_seconds: (8.0, 4.0),
    )
    monkeypatch.setattr(
        monitor,
        "compute_process_cpu_percent",
        lambda prev_jiffies, curr_jiffies, clock_ticks, elapsed_seconds: 50.0,
    )
    monkeypatch.setattr(monitor, "read_process_mem_percent", lambda pid: 1.25)

    state = {
        "pid": 1234,
        "interface": "eth0",
        "clock_ticks": 100,
        "prev_total": 1000,
        "prev_idle": 200,
        "prev_proc_jiffies": 1000,
        "prev_sent": 100,
        "prev_recv": 200,
        "prev_wall_time": 10.0,
    }

    snapshot = monitor.collect_monitor_snapshot(state)

    assert snapshot["cpu"] == 75.0
    assert snapshot["mem"] == 40.0
    assert snapshot["disk"] == 50.0
    assert snapshot["gpu_util"] == 10
    assert snapshot["gpu_mem"] == 256
    assert snapshot["dl"] == 8.0
    assert snapshot["ul"] == 4.0
    assert snapshot["cpu_proc"] == 50.0
    assert snapshot["mem_proc"] == 1.25
    assert snapshot["curr_total"] == 1200
    assert snapshot["curr_idle"] == 250
    assert snapshot["curr_proc_jiffies"] == 1200
    assert snapshot["curr_sent"] == 1_000_100
    assert snapshot["curr_recv"] == 2_000_200
    assert snapshot["curr_wall_time"] == 14.0


def test_advance_monitor_state_writes_context_and_updates_cycle(tmp_path):
    monitor = load_monitor_module()

    report_path = tmp_path / "advance_monitor_state_report.txt"
    report_file = open(report_path, "w", encoding="utf-8")

    state = {
        "report_path": str(report_path),
        "report_file": report_file,
        "start_time": monitor.datetime.now(),
        "pid": 1234,
        "interface": "eth0",
        "clock_ticks": 100,
        "prev_total": 1000,
        "prev_idle": 200,
        "prev_proc_jiffies": 1000,
        "prev_sent": 100,
        "prev_recv": 200,
        "prev_wall_time": 10.0,
        "cycle": 0,
        "closed": False,
    }

    snapshot = {
        "cpu": 75.0,
        "mem": 40.0,
        "disk": 50.0,
        "gpu_util": 10,
        "gpu_mem": 256,
        "dl": 8.0,
        "ul": 4.0,
        "cpu_proc": 50.0,
        "mem_proc": 1.25,
        "curr_total": 1200,
        "curr_idle": 250,
        "curr_proc_jiffies": 1200,
        "curr_sent": 1_000_100,
        "curr_recv": 2_000_200,
        "curr_wall_time": 14.0,
    }

    try:
        updated_state = monitor.advance_monitor_state(
            state=state,
            snapshot=snapshot,
            context="Completed checkpoint test",
            print_console=False,
        )

        assert updated_state["cycle"] == 1
        assert updated_state["prev_total"] == 1200
        assert updated_state["prev_idle"] == 250
        assert updated_state["prev_proc_jiffies"] == 1200
        assert updated_state["prev_sent"] == 1_000_100
        assert updated_state["prev_recv"] == 2_000_200
        assert updated_state["prev_wall_time"] == 14.0

        report_file.flush()
        report_text = report_path.read_text(encoding="utf-8")
        assert "Cycle 1:" in report_text
        assert "Context: Completed checkpoint test" in report_text
        assert "System — CPU: 75.0% | Mem: 40.0% | Disk: 50.0%" in report_text
        assert "Network— DL: 8.00 Mbps | UL: 4.00 Mbps" in report_text
        assert "Process— CPU: 50.0% | Mem: 1.25%" in report_text
    finally:
        monitor.safe_close_file(report_file)


def test_update_monitor_state_uses_collect_monitor_snapshot(tmp_path, monkeypatch):
    monitor = load_monitor_module()

    report_path = tmp_path / "update_monitor_state_report.txt"
    report_file = open(report_path, "w", encoding="utf-8")

    state = {
        "report_path": str(report_path),
        "report_file": report_file,
        "start_time": monitor.datetime.now(),
        "pid": 1234,
        "interface": "eth0",
        "clock_ticks": 100,
        "prev_total": 1000,
        "prev_idle": 200,
        "prev_proc_jiffies": 1000,
        "prev_sent": 100,
        "prev_recv": 200,
        "prev_wall_time": 10.0,
        "cycle": 0,
        "closed": False,
    }

    snapshot = {
        "cpu": 75.0,
        "mem": 40.0,
        "disk": 50.0,
        "gpu_util": 10,
        "gpu_mem": 256,
        "dl": 8.0,
        "ul": 4.0,
        "cpu_proc": 50.0,
        "mem_proc": 1.25,
        "curr_total": 1200,
        "curr_idle": 250,
        "curr_proc_jiffies": 1200,
        "curr_sent": 1_000_100,
        "curr_recv": 2_000_200,
        "curr_wall_time": 14.0,
    }

    monkeypatch.setattr(monitor, "collect_monitor_snapshot", lambda s: snapshot)

    try:
        updated_state = monitor.update_monitor_state(
            state=state,
            context="Collected through update_monitor_state",
            print_console=False,
        )

        assert updated_state["cycle"] == 1
        report_file.flush()
        report_text = report_path.read_text(encoding="utf-8")
        assert "Context: Collected through update_monitor_state" in report_text
    finally:
        monitor.safe_close_file(report_file)


def test_stop_monitor_state_writes_footer_and_closes_report(tmp_path, monkeypatch):
    monitor = load_monitor_module()

    monkeypatch.setattr(monitor, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "get_entry_script_name", lambda: "launcher_script")
    monkeypatch.setattr(monitor, "read_resume_log", lambda: None)
    monkeypatch.setattr(monitor, "get_default_interface", lambda: "eth0")
    monkeypatch.setattr(monitor, "read_proc_stat", lambda: (1000, 200))
    monkeypatch.setattr(monitor, "read_process_cpu_jiffies", lambda pid: 1000)
    monkeypatch.setattr(monitor, "read_net_bytes", lambda interface: (100, 200))
    monkeypatch.setattr(monitor, "get_clock_ticks", lambda: 100)

    state = monitor.start_monitor_state(
        interval_seconds=5.0,
        sampling_mode="checkpoint-based updates during test execution",
        print_start_message=False,
    )

    stopped_state = monitor.stop_monitor_state(
        state=state,
        print_stop_message=False,
    )

    assert stopped_state["closed"] is True
    assert stopped_state["report_file"].closed is True

    report_text = Path(stopped_state["report_path"]).read_text(encoding="utf-8")
    assert "End Time:" in report_text
    assert "Total Duration:" in report_text
    assert "Total Cycles: 0" in report_text