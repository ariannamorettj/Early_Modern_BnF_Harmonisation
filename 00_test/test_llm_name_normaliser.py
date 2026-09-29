import csv
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_name" / "02_llm_based" / "llm_name_normaliser.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("llm_name_normaliser", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_heuristic_csv(path, rows):
    fieldnames = ["actor_uri", "actor_name_original", "actor_name_harmonised",
                 "correction_type", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── collect_unique_residual_values() ─────────────────────────────────────────

def test_collect_unique_residual_values_dedupes_and_orders_first_seen():
    mod = load_module()
    rows = [
        {"actor_name_original": "Jean et Pierre Dupont", "correction_type": "unresolved_multiple_values"},
        {"actor_name_original": "M. B. L.", "correction_type": "initials_or_abbreviation_unresolved"},
        {"actor_name_original": "Jean et Pierre Dupont", "correction_type": "unresolved_multiple_values"},  # dup
    ]
    assert mod.collect_unique_residual_values(rows) == [
        ("Jean et Pierre Dupont", "unresolved_multiple_values"),
        ("M. B. L.", "initials_or_abbreviation_unresolved"),
    ]


def test_collect_unique_residual_values_ignores_resolved_and_missing_rows():
    mod = load_module()
    rows = [
        {"actor_name_original": "Voltaire", "correction_type": "none"},
        {"actor_name_original": "", "correction_type": "unresolved_missing"},
        {"actor_name_original": "Jean Petit", "correction_type": "alias_split"},
        {"actor_name_original": "Sieur de Malherbe", "correction_type": "stripped_title_role"},
        {"actor_name_original": "[unclosed", "correction_type": "unresolved_brackets_or_separators"},
    ]
    assert mod.collect_unique_residual_values(rows) == [
        ("[unclosed", "unresolved_brackets_or_separators"),
    ]


def test_collect_unique_residual_values_same_text_different_issue_kept_distinct():
    """The (value, correction_type) pair is the dedup key, not the value alone."""
    mod = load_module()
    rows = [
        {"actor_name_original": "X Y Z", "correction_type": "unresolved_multiple_values"},
        {"actor_name_original": "X Y Z", "correction_type": "initials_or_abbreviation_unresolved"},
    ]
    assert mod.collect_unique_residual_values(rows) == [
        ("X Y Z", "unresolved_multiple_values"),
        ("X Y Z", "initials_or_abbreviation_unresolved"),
    ]


# ── cache round-trip ──────────────────────────────────────────────────────────

def test_cache_round_trip(tmp_path):
    mod = load_module()
    cache_path = tmp_path / "cache.json"
    assert mod.load_cache(str(cache_path)) == {}

    payload = {
        mod._cache_key("M. B. L.", "initials_or_abbreviation_unresolved"):
            {"harmonised": "", "confidence": "low", "explanation": "..."},
    }
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
    def __init__(self, responses_by_content):
        self.responses_by_content = responses_by_content
        self.calls = []

    def parse(self, model, max_tokens, output_config, system, messages, output_format):
        content = messages[0]["content"]
        self.calls.append(content)
        harmonised, confidence, explanation = self.responses_by_content[content]
        return FakeResponse(FakeParsedOutput(harmonised, confidence, explanation))


class FakeClient:
    def __init__(self, responses_by_content):
        self.messages = FakeMessages(responses_by_content)


def test_run_resolves_and_merges_residual_rows(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "Voltaire", "actor_name_harmonised": "Voltaire",
         "correction_type": "none", "confidence": "high"},
        {"actor_uri": "A2", "actor_name_original": "Jean et Pierre Dupont",
         "actor_name_harmonised": "Jean et Pierre Dupont",
         "correction_type": "unresolved_multiple_values", "confidence": "low"},
        {"actor_uri": "A3", "actor_name_original": "M. B. L.", "actor_name_harmonised": "M. B. L.",
         "correction_type": "initials_or_abbreviation_unresolved", "confidence": "low"},
    ])

    multi_msg = mod._ISSUE_DESCRIPTIONS["unresolved_multiple_values"]
    initials_msg = mod._ISSUE_DESCRIPTIONS["initials_or_abbreviation_unresolved"]
    client = FakeClient({
        f'Value: "Jean et Pierre Dupont"\nIssue detected: unresolved_multiple_values — {multi_msg}': (
            "Jean Dupont; Pierre Dupont", "high", "Two distinct given names sharing one surname."),
        f'Value: "M. B. L."\nIssue detected: initials_or_abbreviation_unresolved — {initials_msg}': (
            "", "low", "No fuller form available; not guessing a historical identity."),
    })

    output_path = tmp_path / "out.csv"
    cache_path = tmp_path / "cache.json"
    mod.run(str(heuristic_csv), str(output_path), str(cache_path), use_monitor=False, client=client)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["actor_uri"]: r for r in csv.DictReader(f)}

    # untouched: heuristic already resolved it
    assert rows["A1"]["actor_name_harmonised"] == "Voltaire"
    assert rows["A1"]["correction_type"] == "none"
    assert rows["A1"]["llm_explanation"] == ""

    # resolved by the LLM
    assert rows["A2"]["actor_name_harmonised"] == "Jean Dupont; Pierre Dupont"
    assert rows["A2"]["correction_type"] == "llm_resolved"
    assert rows["A2"]["confidence"] == "high"
    assert rows["A2"]["llm_explanation"] == "Two distinct given names sharing one surname."

    # LLM also couldn't resolve it: stays initials_or_abbreviation_unresolved
    assert rows["A3"]["actor_name_harmonised"] == "M. B. L."
    assert rows["A3"]["correction_type"] == "initials_or_abbreviation_unresolved"
    assert rows["A3"]["llm_explanation"] == "No fuller form available; not guessing a historical identity."

    assert len(client.messages.calls) == 2


def test_run_deduplicates_llm_calls_by_value_and_issue(tmp_path):
    """Same (raw value, correction_type) pair on multiple rows must only
    trigger one API call."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "M. B. L.",
         "correction_type": "initials_or_abbreviation_unresolved"},
        {"actor_uri": "A2", "actor_name_original": "M. B. L.",
         "correction_type": "initials_or_abbreviation_unresolved"},
    ])
    issue = mod._ISSUE_DESCRIPTIONS["initials_or_abbreviation_unresolved"]
    client = FakeClient({
        f'Value: "M. B. L."\nIssue detected: initials_or_abbreviation_unresolved — {issue}':
            ("", "low", "cannot resolve"),
    })

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert len(client.messages.calls) == 1  # called exactly once, not twice


def test_run_reuses_cache_across_runs_without_calling_client_again(tmp_path):
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "M. B. L.",
         "correction_type": "initials_or_abbreviation_unresolved"},
    ])
    cache_path = tmp_path / "cache.json"
    issue = mod._ISSUE_DESCRIPTIONS["initials_or_abbreviation_unresolved"]
    key = f'Value: "M. B. L."\nIssue detected: initials_or_abbreviation_unresolved — {issue}'

    first_client = FakeClient({key: ("", "low", "first run")})
    mod.run(str(heuristic_csv), str(tmp_path / "out1.csv"), str(cache_path),
           use_monitor=False, client=first_client)
    assert first_client.messages.calls == [key]

    # second run: value already cached -> client must not be used
    mod.run(str(heuristic_csv), str(tmp_path / "out2.csv"), str(cache_path),
           use_monitor=False, client=None)

    with open(tmp_path / "out2.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["llm_explanation"] == "first run"


def test_run_leaves_excluded_categories_untouched(tmp_path):
    """'unresolved_missing'/'alias_split'/'stripped_title_role' rows are
    never sent to the LLM -- see module docstring."""
    mod = load_module()
    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "", "actor_name_harmonised": "",
         "correction_type": "unresolved_missing", "confidence": "low"},
        {"actor_uri": "A2", "actor_name_original": "Jean Petit", "actor_name_harmonised": "Jean Petit",
         "correction_type": "alias_split", "confidence": "medium"},
        {"actor_uri": "A3", "actor_name_original": "Malherbe", "actor_name_harmonised": "Malherbe",
         "correction_type": "stripped_title_role", "confidence": "medium"},
    ])
    client = FakeClient({})

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=client)

    assert client.messages.calls == []
    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = {r["actor_uri"]: r for r in csv.DictReader(f)}
    assert rows["A1"]["correction_type"] == "unresolved_missing"
    assert rows["A2"]["correction_type"] == "alias_split"
    assert rows["A3"]["correction_type"] == "stripped_title_role"
    for r in rows.values():
        assert r["llm_explanation"] == ""


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


def test_run_writes_monitor_checkpoint_per_unique_pair_and_stops_cleanly(monkeypatch, tmp_path):
    mod = load_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(mod, "load_monitor_module", lambda monitor_script: fake_monitor)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "M. B. L.",
         "correction_type": "initials_or_abbreviation_unresolved"},
        {"actor_uri": "A2", "actor_name_original": "X Y Z",
         "correction_type": "unresolved_multiple_values"},
    ])
    issue1 = mod._ISSUE_DESCRIPTIONS["initials_or_abbreviation_unresolved"]
    issue2 = mod._ISSUE_DESCRIPTIONS["unresolved_multiple_values"]
    client = FakeClient({
        f'Value: "M. B. L."\nIssue detected: initials_or_abbreviation_unresolved — {issue1}':
            ("", "low", "x"),
        f'Value: "X Y Z"\nIssue detected: unresolved_multiple_values — {issue2}':
            ("X Y; Z", "medium", "y"),
    })

    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=True, client=client)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per unique pair + final
    assert fake_monitor.update_calls[-1] == "Completed actor_name LLM residual run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    mod = load_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(mod, "load_monitor_module", fail_if_called)

    heuristic_csv = tmp_path / "heuristic.csv"
    _write_heuristic_csv(heuristic_csv, [
        {"actor_uri": "A1", "actor_name_original": "Voltaire", "correction_type": "none"},
    ])
    mod.run(str(heuristic_csv), str(tmp_path / "out.csv"), str(tmp_path / "cache.json"),
           use_monitor=False, client=FakeClient({}))


def test_load_monitor_module_resolves_real_monitor_script():
    mod = load_module()
    monitor = mod.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")
