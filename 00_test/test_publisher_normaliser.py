import csv
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "publisher" / "01_heuristic_rules" / "publisher_normaliser.py"
)


def load_publisher_normaliser_module():
    spec = importlib.util.spec_from_file_location("publisher_normaliser", PUBLISHER_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_edition_csv(path, rows):
    fieldnames = ["edition", "publisher"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── classify_and_normalise() ─────────────────────────────────────────────────

def test_classify_missing():
    pn = load_publisher_normaliser_module()
    result = pn.classify_and_normalise("")
    assert result == {"harmonised": "", "correction_type": "missing", "confidence": "low"}


def test_classify_sine_nomine_bracketed():
    pn = load_publisher_normaliser_module()
    for value in ("[s.n.]", "[sans nom]", "s.n.", "sine nomine"):
        result = pn.classify_and_normalise(value)
        assert result["correction_type"] == "sine_nomine"
        assert result["harmonised"] == ""
        assert result["confidence"] == "high"


def test_classify_self_published():
    pn = load_publisher_normaliser_module()
    for value in ("Auteur", "l'auteur", "chez l'auteur"):
        result = pn.classify_and_normalise(value)
        assert result["correction_type"] == "self_published"
        assert result["harmonised"] == "L'auteur"


def test_classify_multi_value_flagged_not_split():
    pn = load_publisher_normaliser_module()
    raw = "Vve F. Muguet et H. Muguet"
    result = pn.classify_and_normalise(raw)
    assert result["correction_type"] == "multi_value"
    assert result["confidence"] == "low"
    # Flagged, not split or altered.
    assert result["harmonised"] == raw


def test_classify_abbreviation_expanded_collapses_real_variants():
    # Real top-frequency data: "Impr. royale" (19,364x), "Imp. royale"
    # (5,305x), "imp. royale" (4,827x) all collapse to the same expanded
    # string because the second word is already consistently lowercase.
    pn = load_publisher_normaliser_module()
    for raw in ("Impr. royale", "Imp. royale", "imp. royale"):
        result = pn.classify_and_normalise(raw)
        assert result["correction_type"] == "abbreviation_expanded"
        assert result["harmonised"] == "Imprimerie royale"


def test_classify_location_stripped():
    pn = load_publisher_normaliser_module()
    result = pn.classify_and_normalise("Chaignieau aine (Paris)")
    assert result["correction_type"] == "location_stripped"
    assert result["harmonised"] == "Chaignieau aine"


def test_classify_does_not_strip_a_year_range_parenthesis():
    pn = load_publisher_normaliser_module()
    result = pn.classify_and_normalise("J. Smith (1750-1780)")
    assert result["correction_type"] == "passthrough"
    assert result["harmonised"] == "J. Smith (1750-1780)"


def test_classify_bracketed_uncertain_when_nothing_else_applies():
    pn = load_publisher_normaliser_module()
    result = pn.classify_and_normalise("[G. L. Le Rouge]")
    assert result["correction_type"] == "bracketed_uncertain"
    assert result["harmonised"] == "G. L. Le Rouge"
    assert result["confidence"] == "medium"


def test_classify_passthrough():
    pn = load_publisher_normaliser_module()
    result = pn.classify_and_normalise("P. Prault")
    assert result == {"harmonised": "P. Prault", "correction_type": "passthrough", "confidence": "high"}


# ── canonical_key() ───────────────────────────────────────────────────────────

def test_canonical_key_is_case_accent_and_punctuation_insensitive():
    pn = load_publisher_normaliser_module()
    assert pn.canonical_key("Imprimerie Royale") == pn.canonical_key("imprimerie   royale,")
    assert pn.canonical_key("Chereau") == pn.canonical_key("Chéreau")


# ── cluster_by_canonical_key() ───────────────────────────────────────────────

def test_cluster_by_canonical_key_merges_onto_most_frequent_literal():
    pn = load_publisher_normaliser_module()
    results = {
        "P. Prault": {"harmonised": "P. Prault", "correction_type": "passthrough", "confidence": "high"},
        "P Prault": {"harmonised": "P Prault", "correction_type": "passthrough", "confidence": "high"},
    }
    counts = Counter({"P. Prault": 100, "P Prault": 5})

    clustered, changed = pn.cluster_by_canonical_key(results, counts)

    assert changed == 1
    assert clustered["P. Prault"]["harmonised"] == "P. Prault"
    assert clustered["P. Prault"]["correction_type"] == "passthrough"
    assert clustered["P Prault"]["harmonised"] == "P. Prault"
    assert clustered["P Prault"]["correction_type"] == "canonical_clustered"


def test_cluster_by_canonical_key_never_touches_non_clusterable_types():
    pn = load_publisher_normaliser_module()
    results = {
        "Auteur": {"harmonised": "L'auteur", "correction_type": "self_published", "confidence": "high"},
        "auteur": {"harmonised": "L'auteur", "correction_type": "self_published", "confidence": "high"},
    }
    counts = Counter({"Auteur": 10, "auteur": 1})

    clustered, changed = pn.cluster_by_canonical_key(results, counts)

    assert changed == 0
    assert clustered["Auteur"]["correction_type"] == "self_published"
    assert clustered["auteur"]["correction_type"] == "self_published"


# ── cluster_by_fuzzy_similarity() ────────────────────────────────────────────

def test_cluster_by_fuzzy_similarity_merges_near_miss_not_caught_by_exact_key():
    pn = load_publisher_normaliser_module()
    # "Imprimerie royale" vs "Imprimerie roiale" (a 'y'->'i' typo) share no
    # canonical_key(), so pass 1 (exact key) would never merge them.
    results = {
        "Impr. royale": {"harmonised": "Imprimerie royale",
                         "correction_type": "abbreviation_expanded", "confidence": "high"},
        "Imprimerie roiale": {"harmonised": "Imprimerie roiale",
                              "correction_type": "passthrough", "confidence": "high"},
    }
    counts = Counter({"Impr. royale": 100, "Imprimerie roiale": 3})

    clustered, changed, skipped = pn.cluster_by_fuzzy_similarity(results, counts)

    assert changed == 1
    assert skipped == 0
    assert clustered["Imprimerie roiale"]["harmonised"] == "Imprimerie royale"
    assert clustered["Imprimerie roiale"]["correction_type"] == "fuzzy_clustered"
    assert clustered["Imprimerie roiale"]["confidence"] == "medium"
    # The more frequent literal never gets relabelled by its own merge.
    assert clustered["Impr. royale"]["correction_type"] == "abbreviation_expanded"


def test_cluster_by_fuzzy_similarity_below_threshold_does_not_merge():
    pn = load_publisher_normaliser_module()
    results = {
        "A": {"harmonised": "Prault", "correction_type": "passthrough", "confidence": "high"},
        "B": {"harmonised": "Panckoucke", "correction_type": "passthrough", "confidence": "high"},
    }
    counts = Counter({"A": 10, "B": 10})

    clustered, changed, skipped = pn.cluster_by_fuzzy_similarity(results, counts)

    assert changed == 0
    assert clustered["A"]["harmonised"] == "Prault"
    assert clustered["B"]["harmonised"] == "Panckoucke"


def test_cluster_by_fuzzy_similarity_transitive_merge_via_union_find():
    """A~B and B~C match directly, A~C does not -- all three must still end
    up in the same cluster via the union-find, not just A+B or B+C."""
    pn = load_publisher_normaliser_module()
    results = {
        "raw_a": {"harmonised": "Baudoin", "correction_type": "passthrough", "confidence": "high"},
        "raw_b": {"harmonised": "Baudouin", "correction_type": "passthrough", "confidence": "high"},
        "raw_c": {"harmonised": "Baudowin", "correction_type": "passthrough", "confidence": "high"},
    }
    counts = Counter({"raw_a": 1, "raw_b": 100, "raw_c": 1})

    clustered, changed, skipped = pn.cluster_by_fuzzy_similarity(results, counts, threshold=0.8)

    literals = {clustered[k]["harmonised"] for k in results}
    assert len(literals) == 1  # everything merged onto one literal
    assert clustered["raw_b"]["correction_type"] == "passthrough"  # most frequent, unrelabelled


def test_cluster_by_fuzzy_similarity_skips_oversized_block():
    pn = load_publisher_normaliser_module()
    # 3 distinct literals all blocking under the same 4-char canonical-key
    # prefix ("test") -- with max_block_size=2 this block (size 3) must be
    # skipped rather than compared.
    results = {
        "r1": {"harmonised": "testalpha", "correction_type": "passthrough", "confidence": "high"},
        "r2": {"harmonised": "testalphb", "correction_type": "passthrough", "confidence": "high"},
        "r3": {"harmonised": "testalphc", "correction_type": "passthrough", "confidence": "high"},
    }
    counts = Counter({"r1": 5, "r2": 5, "r3": 5})

    clustered, changed, skipped = pn.cluster_by_fuzzy_similarity(
        results, counts, threshold=0.5, max_block_size=2)

    assert skipped == 1
    assert changed == 0


def test_uf_find_and_union_basic_behaviour():
    pn = load_publisher_normaliser_module()
    parent = {"a": "a", "b": "b", "c": "c"}
    pn._uf_union(parent, "a", "b")
    pn._uf_union(parent, "b", "c")
    assert pn._uf_find(parent, "a") == pn._uf_find(parent, "c")


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    pn = load_publisher_normaliser_module()
    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [
        {"edition": "E1", "publisher": "Impr. royale"},
        {"edition": "E1", "publisher": "Impr. royale"},  # duplicate row
        {"edition": "E2", "publisher": "[s.n.]"},
        {"edition": "E3", "publisher": ""},
    ])

    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"
    pn.run(str(input_path), str(output_path), str(report_path))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert set(rows[0].keys()) == {
        "edition", "publisher_original", "publisher_harmonised", "correction_type", "confidence",
    }
    assert len(rows) == 3  # one row per edition

    by_edition = {r["edition"]: r for r in rows}
    assert by_edition["E1"]["publisher_harmonised"] == "Imprimerie royale"
    assert by_edition["E2"]["correction_type"] == "sine_nomine"
    assert by_edition["E3"]["correction_type"] == "missing"

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["total_editions"] == 3
    assert report["distinct_raw_values"] == 2


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


def test_run_stops_monitor_cleanly_when_enabled(monkeypatch, tmp_path):
    pn = load_publisher_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(pn, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [{"edition": "E1", "publisher": "P. Prault"}])

    pn.run(str(input_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert fake_monitor.update_calls[-1] == "Completed publisher harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    pn = load_publisher_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(pn, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [{"edition": "E1", "publisher": "P. Prault"}])

    pn.run(str(input_path), str(tmp_path / "out.csv"), str(tmp_path / "report.json"), use_monitor=False)


def test_load_llm_module_resolves_real_llm_script():
    pn = load_publisher_normaliser_module()
    llm_module = pn.load_llm_module()

    assert hasattr(llm_module, "run")
    assert hasattr(llm_module, "CACHE_PATH_DEFAULT")


# ── main() orchestration: LLM step wiring ────────────────────────────────────

class FakeLLMModule:
    def __init__(self):
        self.run_calls = []
        self.CACHE_PATH_DEFAULT = "fake/cache/path.json"

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def test_main_runs_llm_step_by_default(monkeypatch, tmp_path):
    pn = load_publisher_normaliser_module()
    fake_llm = FakeLLMModule()
    monkeypatch.setattr(pn, "load_llm_module", lambda: fake_llm)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [{"edition": "E1", "publisher": "P. Prault"}])
    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(sys, "argv", [
        "publisher_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_path),
        "--report", str(report_path),
        "--no-monitor",
    ])
    pn.main()

    assert len(fake_llm.run_calls) == 1
    call = fake_llm.run_calls[0]
    assert call["heuristic_output_csv"] == str(output_path)
    assert call["output_path"] == str(output_path)
    assert call["cache_path"] == fake_llm.CACHE_PATH_DEFAULT
    assert call["model"] == "claude-opus-5"
    assert call["effort"] == "low"
    assert call["use_monitor"] is False


def test_main_no_llm_flag_skips_llm_step(monkeypatch, tmp_path):
    pn = load_publisher_normaliser_module()

    def fail_if_called():
        raise AssertionError("load_llm_module should not be called when --no-llm is passed")

    monkeypatch.setattr(pn, "load_llm_module", fail_if_called)

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [{"edition": "E1", "publisher": "P. Prault"}])
    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(sys, "argv", [
        "publisher_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_path),
        "--report", str(report_path),
        "--no-monitor",
        "--no-llm",
    ])
    pn.main()  # must not raise -> load_llm_module was never called

    assert output_path.exists()


def test_main_no_fuzzy_clustering_flag_disables_pass_2_6(monkeypatch, tmp_path):
    pn = load_publisher_normaliser_module()

    input_path = tmp_path / "editions.csv"
    _write_edition_csv(input_path, [
        {"edition": "E1", "publisher": "Impr. royale"},
        {"edition": "E2", "publisher": "Imprimerie roiale"},  # near-miss typo
    ])
    output_path = tmp_path / "out.csv"
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(sys, "argv", [
        "publisher_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_path),
        "--report", str(report_path),
        "--no-monitor", "--no-llm", "--no-fuzzy-clustering",
    ])
    pn.main()

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["fuzzy_clustered_count"] == 0

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {r["edition"]: r for r in csv.DictReader(f)}
    # Without pass 2.6, the typo'd variant is left as its own passthrough
    # literal rather than merged onto "Imprimerie royale".
    assert rows["E2"]["publisher_harmonised"] == "Imprimerie roiale"
