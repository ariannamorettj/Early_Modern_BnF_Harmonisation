import csv
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_dates" / "02_llm_based" / "llm_dates_normaliser.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("llm_dates_normaliser", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_heuristic_csv(path, rows):
    fieldnames = ["actor_uri", "field", "date_original", "date_harmonised",
                 "date_format_detected", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── collect_unique_non_parseable_values() ────────────────────────────────────

def test_collect_unique_non_parseable_values_dedupes_and_orders_first_seen():
    mod = load_module()
    rows = [
        {"date_original": "175.-07-27", "date_format_detected": "non_parseable"},
        {"date_original": "1799-03-2.", "date_format_detected": "non_parseable"},
        {"date_original": "175.-07-27", "date_format_detected": "non_parseable"},  # dup
    ]
    assert mod.collect_unique_non_parseable_values(rows) == ["175.-07-27", "1799-03-2."]


def test_collect_unique_non_parseable_values_ignores_resolved_and_missing_rows():
    mod = load_module()
    rows = [
        {"date_original": "1750", "date_format_detected": "exact_year"},
        {"date_original": "", "date_format_detected": "missing"},
        {"date_original": "14??", "date_format_detected": "non_parseable"},
    ]
    assert mod.collect_unique_non_parseable_values(rows) == ["14??"]


# ── cache round-trip ──────────────────────────────────────────────────────────

def test_cache_round_trip(tmp_path):
    mod = load_module()
    cache_path = tmp_path / "cache.json"
    assert mod.load_cache(str(cache_path)) == {}

    payload = {"14??": {"harmonised": "17XX", "confidence": "medium", "explanation": "..."}}
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


def test_run_resolves_and_merges_non_parseable_rows(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_birth", "date_original": "1750",
         "date_harmonised": "1750", "date_format_detected": "exact_year", "confidence": "high"},
        {"actor_uri": "A2", "field": "actor_birth", "date_original": "175.-07-27",
         "date_harmonised": "", "date_format_detected": "non_parseable", "confidence": "low"},
        {"actor_uri": "A3", "field": "actor_death", "date_original": "14??",
         "date_harmonised": "", "date_format_detected": "non_parseable", "confidence": "low"},
    ])
    client = FakeClient({
        "175.-07-27": ("175X-07-27", "medium", "Year century+decade known, day/month exact."),
        "14??": ("", "low", "Cannot confidently resolve the mask character '?'."),
    })

    output_path = tmp_path / "out.csv"
    cache_path = tmp_path / "cache.json"
    mod.run(str(heuristic_csv), str(output_path), str(cache_path), use_monitor=False, client=client)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["actor_uri"]: r for r in csv.DictReader(f)}

    # untouched: heuristic already resolved it
    assert rows["A1"]["date_harmonised"] == "1750"
    assert rows["A1"]["date_format_detected"] == "exact_year"
    assert rows["A1"]["llm_explanation"] == ""

    # resolved by the LLM
    assert rows["A2"]["date_harmonised"] == "175X-07-27"
    assert rows["A2"]["date_format_detected"] == "llm_resolved"
    assert rows["A2"]["confidence"] == "medium"
    assert rows["A2"]["llm_explanation"] == "Year century+decade known, day/month exact."

    # LLM also couldn't resolve it: stays non_parseable, but explanation recorded
    assert rows["A3"]["date_harmonised"] == ""
    assert rows["A3"]["date_format_detected"] == "non_parseable"
    assert rows["A3"]["llm_explanation"] == "Cannot confidently resolve the mask character '?'."

    assert set(client.messages.calls) == {"175.-07-27", "14??"}


def test_run_deduplicates_llm_calls_by_raw_value(tmp_path):
    """Same raw value on multiple rows must only trigger one API call."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_birth", "date_original": "175.-07-27",
         "date_format_detected": "non_parseable"},
        {"actor_uri": "A2", "field": "actor_death", "date_original": "175.-07-27",
         "date_format_detected": "non_parseable"},
    ])
    client = FakeClient({"175.-07-27": ("175X-07-27", "medium", "explained")})

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert client.messages.calls == ["175.-07-27"]  # called exactly once, not twice


def test_run_reuses_cache_across_runs_without_calling_client_again(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_birth", "date_original": "14??",
         "date_format_detected": "non_parseable"},
    ])
    cache_path = tmp_path / "cache.json"

    first_client = FakeClient({"14??": ("17XX", "medium", "first run")})
    mod.run(str(heuristic_csv), str(tmp_path / "out1.csv"), str(cache_path),
           use_monitor=False, client=first_client)
    assert first_client.messages.calls == ["14??"]

    # second run: value already cached -> client must not be used, and since
    # client=None here, this also proves get_client() is never invoked when
    # nothing new needs resolving (it would fail: anthropic isn't installed).
    mod.run(str(heuristic_csv), str(tmp_path / "out2.csv"), str(cache_path),
           use_monitor=False, client=None)

    with open(tmp_path / "out2.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["date_harmonised"] == "17XX"
    assert rows[0]["llm_explanation"] == "first run"


def test_run_leaves_missing_rows_untouched(tmp_path):
    """'missing' rows (no source value at all) are never sent to the LLM."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_start", "date_original": "",
         "date_harmonised": "", "date_format_detected": "missing", "confidence": "low"},
    ])
    client = FakeClient({})

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert client.messages.calls == []
    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["date_format_detected"] == "missing"
    assert rows[0]["llm_explanation"] == ""


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


def test_run_writes_monitor_checkpoint_periodically_and_stops_cleanly(monkeypatch, tmp_path):
    """Checkpoints fire every MONITOR_CHECKPOINT_EVERY records and at the last
    one, not per record: with the cadence lowered to 2, a 2-record run skips
    record 1 and checkpoints record 2, then the completion checkpoint."""
    mod = load_module()
    monkeypatch.setattr(mod, "MONITOR_CHECKPOINT_EVERY", 2)
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(mod, "load_monitor_module", lambda monitor_script: fake_monitor)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_birth", "date_original": "175.-07-27",
         "date_format_detected": "non_parseable"},
        {"actor_uri": "A2", "field": "actor_death", "date_original": "14??",
         "date_format_detected": "non_parseable"},
    ])
    client = FakeClient({
        "175.-07-27": ("175X-07-27", "medium", "x"),
        "14??": ("", "low", "y"),
    })

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=True, client=client)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 1 + 1  # record 2 (last), completion
    assert fake_monitor.update_calls[-1] == "Completed actor_dates LLM residual run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    mod = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(mod, "load_monitor_module", fail_if_called)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "field": "actor_birth", "date_original": "1750",
         "date_format_detected": "exact_year"},
    ])
    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=FakeClient({}))


def test_load_monitor_module_resolves_real_monitor_script():
    mod = load_module()
    monitor = mod.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
