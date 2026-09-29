import csv
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "publisher" / "02_llm_based" / "llm_publisher_normaliser.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("llm_publisher_normaliser", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_heuristic_csv(path, rows):
    fieldnames = ["edition", "publisher_original", "publisher_harmonised",
                 "correction_type", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── collect_unique_multi_value_values() ──────────────────────────────────────

def test_collect_unique_multi_value_values_dedupes_and_orders_first_seen():
    mod = load_module()
    rows = [
        {"publisher_original": "Vve F. Muguet et H. Muguet", "correction_type": "multi_value"},
        {"publisher_original": "Vve Saugrain et. - P. Prault", "correction_type": "multi_value"},
        {"publisher_original": "Vve F. Muguet et H. Muguet", "correction_type": "multi_value"},  # dup
    ]
    assert mod.collect_unique_multi_value_values(rows) == [
        "Vve F. Muguet et H. Muguet", "Vve Saugrain et. - P. Prault",
    ]


def test_collect_unique_multi_value_values_ignores_resolved_and_missing_rows():
    mod = load_module()
    rows = [
        {"publisher_original": "P. Prault", "correction_type": "passthrough"},
        {"publisher_original": "", "correction_type": "missing"},
        {"publisher_original": "X et fils", "correction_type": "multi_value"},
    ]
    assert mod.collect_unique_multi_value_values(rows) == ["X et fils"]


# ── cache round-trip ──────────────────────────────────────────────────────────

def test_cache_round_trip(tmp_path):
    mod = load_module()
    cache_path = tmp_path / "cache.json"
    assert mod.load_cache(str(cache_path)) == {}

    payload = {"X et fils": {"harmonised": "X et fils", "confidence": "medium", "explanation": "..."}}
    mod.save_cache(str(cache_path), payload)
    assert mod.load_cache(str(cache_path)) == payload


# ── run() end-to-end (fake client, no real API/network call) ────────────────

class FakeParsedOutput:
    def __init__(self, harmonised, confidence, explanation):
        self.harmonised = harmonised
        self.confidence = confidence
        self.explanation = explanation


class FakeResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class FakeMessages:
    def __init__(self, responses_by_value):
        self.responses_by_value = responses_by_value
        self.calls = []

    def parse(self, model, max_tokens, output_config, system, messages, output_format):
        raw_value = messages[0]["content"]
        self.calls.append(raw_value)
        harmonised, confidence, explanation = self.responses_by_value[raw_value]
        return FakeResponse(FakeParsedOutput(harmonised, confidence, explanation))


class FakeClient:
    def __init__(self, responses_by_value):
        self.messages = FakeMessages(responses_by_value)


def test_run_resolves_and_merges_multi_value_rows(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "P. Prault", "publisher_harmonised": "P. Prault",
         "correction_type": "passthrough", "confidence": "high"},
        {"edition": "E2", "publisher_original": "Vve F. Muguet et H. Muguet",
         "publisher_harmonised": "Vve F. Muguet et H. Muguet",
         "correction_type": "multi_value", "confidence": "low"},
        {"edition": "E3", "publisher_original": "X et fils", "publisher_harmonised": "X et fils",
         "correction_type": "multi_value", "confidence": "low"},
    ])
    client = FakeClient({
        "Vve F. Muguet et H. Muguet": (
            "Vve F. Muguet; H. Muguet", "high", "Two distinct publishers concatenated."),
        "X et fils": ("", "low", "Cannot confidently tell if this is one firm or two."),
    })

    output_path = tmp_path / "out.csv"
    cache_path = tmp_path / "cache.json"
    mod.run(str(heuristic_csv), str(output_path), str(cache_path), use_monitor=False, client=client)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["edition"]: r for r in csv.DictReader(f)}

    # untouched: heuristic already resolved it
    assert rows["E1"]["publisher_harmonised"] == "P. Prault"
    assert rows["E1"]["correction_type"] == "passthrough"
    assert rows["E1"]["llm_explanation"] == ""

    # resolved by the LLM
    assert rows["E2"]["publisher_harmonised"] == "Vve F. Muguet; H. Muguet"
    assert rows["E2"]["correction_type"] == "llm_resolved"
    assert rows["E2"]["confidence"] == "high"
    assert rows["E2"]["llm_explanation"] == "Two distinct publishers concatenated."

    # LLM also couldn't resolve it: stays multi_value, explanation recorded
    assert rows["E3"]["publisher_harmonised"] == "X et fils"
    assert rows["E3"]["correction_type"] == "multi_value"
    assert rows["E3"]["llm_explanation"] == "Cannot confidently tell if this is one firm or two."

    assert set(client.messages.calls) == {"Vve F. Muguet et H. Muguet", "X et fils"}


def test_run_deduplicates_llm_calls_by_raw_value(tmp_path):
    """Same raw value on multiple rows must only trigger one API call."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "X et fils", "correction_type": "multi_value"},
        {"edition": "E2", "publisher_original": "X et fils", "correction_type": "multi_value"},
    ])
    client = FakeClient({"X et fils": ("X et fils", "medium", "single firm name")})

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert client.messages.calls == ["X et fils"]  # called exactly once, not twice


def test_run_reuses_cache_across_runs_without_calling_client_again(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "X et fils", "correction_type": "multi_value"},
    ])
    cache_path = tmp_path / "cache.json"

    first_client = FakeClient({"X et fils": ("X et fils", "medium", "first run")})
    mod.run(str(heuristic_csv), str(tmp_path / "out1.csv"), str(cache_path),
           use_monitor=False, client=first_client)
    assert first_client.messages.calls == ["X et fils"]

    # second run: value already cached -> client must not be used
    mod.run(str(heuristic_csv), str(tmp_path / "out2.csv"), str(cache_path),
           use_monitor=False, client=None)

    with open(tmp_path / "out2.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["publisher_harmonised"] == "X et fils"
    assert rows[0]["llm_explanation"] == "first run"


def test_run_leaves_definitive_rows_untouched(tmp_path):
    """'missing'/'sine_nomine'/'self_published' rows are never sent to the LLM."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "", "publisher_harmonised": "",
         "correction_type": "missing", "confidence": "low"},
        {"edition": "E2", "publisher_original": "[s.n.]", "publisher_harmonised": "",
         "correction_type": "sine_nomine", "confidence": "high"},
    ])
    client = FakeClient({})

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert client.messages.calls == []
    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = {r["edition"]: r for r in csv.DictReader(f)}
    assert rows["E1"]["correction_type"] == "missing"
    assert rows["E2"]["correction_type"] == "sine_nomine"
    assert rows["E1"]["llm_explanation"] == ""
    assert rows["E2"]["llm_explanation"] == ""


# ── Monitor integration ──────────────────────────────────────────────────────

class FakeMonitorModule:
    def __init__(self):
        self.start_calls = []
        self.update_calls = []
        self.stop_calls = []

    def start_monitor_state(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"report_path": "fake_report.txt", "closed": False}

    def update_monitor_state(self, state, context=None, print_console=True):
        self.update_calls.append(context)
        return state

    def stop_monitor_state(self, state, print_stop_message=True):
        self.stop_calls.append(print_stop_message)
        state["closed"] = True
        return state


def test_run_writes_monitor_checkpoint_per_unique_value_and_stops_cleanly(monkeypatch, tmp_path):
    mod = load_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(mod, "load_monitor_module", lambda monitor_script: fake_monitor)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "X et fils", "correction_type": "multi_value"},
        {"edition": "E2", "publisher_original": "Y et Z", "correction_type": "multi_value"},
    ])
    client = FakeClient({
        "X et fils": ("X et fils", "medium", "x"),
        "Y et Z": ("Y; Z", "high", "y"),
    })

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=True, client=client)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per unique value + final
    assert fake_monitor.update_calls[-1] == "Completed publisher LLM residual run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    mod = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(mod, "load_monitor_module", fail_if_called)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"edition": "E1", "publisher_original": "P. Prault", "correction_type": "passthrough"},
    ])
    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=FakeClient({}))


def test_load_monitor_module_resolves_real_monitor_script():
    mod = load_module()
    monitor = mod.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
