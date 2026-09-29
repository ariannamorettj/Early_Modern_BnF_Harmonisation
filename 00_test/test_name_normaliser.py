import csv
import importlib.util
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAME_NORMALISER_PATH = (
    PROJECT_ROOT / "04_harmonisation_and_evaluation" / "01_harmonisation"
    / "actor_name" / "01_heuristic_rules" / "name_normaliser.py"
)


def load_name_normaliser_module():
    spec = importlib.util.spec_from_file_location("name_normaliser", NAME_NORMALISER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_actor_csv(path, rows):
    fieldnames = ["actor", "actor_name", "actor_first_name", "actor_last_name"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── strip_rdf_literal_tag() ──────────────────────────────────────────────────

def test_strip_rdf_literal_tag_unwraps_quoted_literal_with_language_tag():
    nn = load_name_normaliser_module()
    inner, found = nn.strip_rdf_literal_tag('"William Blake trust"@fr')
    assert found is True
    assert inner == "William Blake trust"


def test_strip_rdf_literal_tag_noop_on_clean_name():
    nn = load_name_normaliser_module()
    inner, found = nn.strip_rdf_literal_tag("Voltaire")
    assert found is False
    assert inner == "Voltaire"


def test_derive_actor_name_prefers_rdf_literal_rule_over_generic_brackets():
    """Regression test for the real-data finding: a plain bracket-strip
    left the closing quote and '@fr' tag both in place (99.5% of cases in
    this bucket on the full raw dataset were this exact pattern)."""
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name('"William Blake trust"@fr', "", "")
    assert result["harmonised"] == "William Blake trust"
    assert result["correction_type"] == "stripped_rdf_literal_tag"
    assert '"' not in result["harmonised"]
    assert "@fr" not in result["harmonised"]


# ── strip_wrapping_punctuation() ─────────────────────────────────────────────

def test_strip_wrapping_punctuation_removes_matched_brackets():
    nn = load_name_normaliser_module()
    assert nn.strip_wrapping_punctuation("[Voltaire]") == "Voltaire"
    assert nn.strip_wrapping_punctuation("(Voltaire)") == "Voltaire"
    assert nn.strip_wrapping_punctuation('"Voltaire"') == "Voltaire"


def test_strip_wrapping_punctuation_strips_stray_leading_trailing_punctuation():
    nn = load_name_normaliser_module()
    assert nn.strip_wrapping_punctuation("- Voltaire -") == "Voltaire"


def test_strip_wrapping_punctuation_noop_on_clean_name():
    nn = load_name_normaliser_module()
    assert nn.strip_wrapping_punctuation("Voltaire") == "Voltaire"


def test_contains_brackets_or_separators_gates_the_cascade_rule():
    """Regression test: strip_wrapping_punctuation()'s trailing-non-alnum
    trim would otherwise eat the period off a plain abbreviation like 'Th.'
    before the initials/abbreviation rule ever runs — it must only fire
    when a real bracket/quote/separator is present."""
    nn = load_name_normaliser_module()
    assert nn.contains_brackets_or_separators("Th.") is False
    assert nn.contains_brackets_or_separators("[Voltaire]") is True


# ── split_on_alias_marker() ──────────────────────────────────────────────────

def test_split_on_alias_marker_drops_alias_text():
    nn = load_name_normaliser_module()
    primary, found = nn.split_on_alias_marker("Jean Petit, dit le Grand")
    assert found is True
    assert primary == "Jean Petit"


def test_split_on_alias_marker_handles_alias_keyword():
    nn = load_name_normaliser_module()
    primary, found = nn.split_on_alias_marker("Giovanni Rossi alias Il Moro")
    assert found is True
    assert primary == "Giovanni Rossi"


def test_split_on_alias_marker_noop_when_no_marker():
    nn = load_name_normaliser_module()
    primary, found = nn.split_on_alias_marker("Voltaire")
    assert found is False
    assert primary == "Voltaire"


# ── strip_title_or_role() ─────────────────────────────────────────────────────

def test_strip_title_or_role_removes_multi_word_title():
    nn = load_name_normaliser_module()
    remainder, found = nn.strip_title_or_role("Sieur de Malherbe")
    assert found is True
    assert remainder == "Malherbe"


def test_strip_title_or_role_removes_single_word_title():
    nn = load_name_normaliser_module()
    remainder, found = nn.strip_title_or_role("Veuve Duval")
    assert found is True
    assert remainder == "Duval"


def test_strip_title_or_role_noop_when_no_title():
    nn = load_name_normaliser_module()
    remainder, found = nn.strip_title_or_role("Voltaire")
    assert found is False
    assert remainder == "Voltaire"


# ── looks_like_multiple_values() ─────────────────────────────────────────────

def test_looks_like_multiple_values_detects_internal_conjunction():
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Jean et Pierre Dupont") is True


def test_looks_like_multiple_values_false_for_compound_surname():
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Fernando Alvarez de Toledo y Pimentel") is False


def test_looks_like_multiple_values_false_for_clean_name():
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Voltaire") is False


def test_looks_like_multiple_values_false_for_iberian_double_surname():
    """Regression test for a real-data finding: the Iberian/German
    double-surname convention ('Given Surname1 y|und Surname2') was the
    dominant false-positive pattern once the middle-initial case was
    fixed — hundreds of genuine single-person names like this one were
    being flagged as concatenated multiple values."""
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Juan Melo y Girón") is False
    assert nn.looks_like_multiple_values(
        "Friedrich August, Graf von Zinzendorf und Pottendorf") is False


def test_looks_like_multiple_values_still_true_for_genuine_concatenation_near_start():
    """The distinguishing signal is POSITION: a real concatenation of two
    people has the conjunction near the start (two given names sharing a
    surname), not second-to-last (a compound surname)."""
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Peter et John Dollond") is True
    assert nn.looks_like_multiple_values("Jean et Pierre Dupont") is True


def test_looks_like_multiple_values_false_for_middle_initial_pattern():
    """Regression test for a real-data finding: dozens of names like
    'A E Crous' were false-positived as 'X and Crous' because a bare
    uppercase 'E' middle initial case-folds to the Italian conjunction
    'e'. A real conjunction joins two full names, not an initial and a
    name."""
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("A E Crous") is False
    assert nn.looks_like_multiple_values("F E Louys") is False


def test_looks_like_multiple_values_false_when_conjunction_slot_itself_is_an_initial():
    """Regression test for a second real-data finding: 'Eric E Edner' was
    still flagged after the previous fix, because that fix only checked
    the NEIGHBOURS of the conjunction slot for bare-initial shape, not the
    slot itself. Case is the signal here: a capitalised single letter in
    that slot is an initial ('E'), a real conjunction reads lowercase in
    running prose ('e')."""
    nn = load_name_normaliser_module()
    assert nn.looks_like_multiple_values("Eric E Edner") is False
    assert nn.looks_like_multiple_values("Sherman E. Lee") is False
    assert nn.looks_like_multiple_values("Flavio e Flaminio Bartoli") is True


# ── looks_like_initials_or_abbreviation() ────────────────────────────────────

def test_looks_like_initials_or_abbreviation_detects_dotted_abbreviation():
    nn = load_name_normaliser_module()
    assert nn.looks_like_initials_or_abbreviation("Th.") is True


def test_looks_like_initials_or_abbreviation_detects_bare_initials():
    nn = load_name_normaliser_module()
    assert nn.looks_like_initials_or_abbreviation("M D") is True


def test_looks_like_initials_or_abbreviation_false_for_clean_name():
    nn = load_name_normaliser_module()
    assert nn.looks_like_initials_or_abbreviation("Voltaire") is False


# ── apply_name_cleanup_rules() / derive_actor_name() cascade ────────────────

def test_derive_actor_name_strips_brackets():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("[Voltaire]", "", "")
    assert result == {"harmonised": "Voltaire",
                      "correction_type": "stripped_brackets_or_separators",
                      "confidence": "high"}


def test_derive_actor_name_flags_unresolvable_brackets_instead_of_corrupting():
    """Regression test for a real-data finding: a quote/bracket that only
    wraps part of the string (a book title quoted mid-sentence) must not be
    naively stripped — that leaves a stray, unbalanced character behind,
    which is worse than the original value."""
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name('Le Redacteur de la Morale de "Moise"', "", "")
    assert result["harmonised"] == 'Le Redacteur de la Morale de "Moise"'
    assert result["correction_type"] == "unresolved_brackets_or_separators"
    assert result["confidence"] == "low"


def test_derive_actor_name_splits_alias():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Jean Petit, dit le Grand", "", "")
    assert result["harmonised"] == "Jean Petit"
    assert result["correction_type"] == "alias_split"
    assert result["confidence"] == "medium"


def test_derive_actor_name_strips_title_role():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Sieur de Malherbe", "", "")
    assert result["harmonised"] == "Malherbe"
    assert result["correction_type"] == "stripped_title_role"
    assert result["confidence"] == "medium"


def test_derive_actor_name_flags_multiple_values_without_guessing():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Jean et Pierre Dupont", "", "")
    assert result["harmonised"] == "Jean et Pierre Dupont"
    assert result["correction_type"] == "unresolved_multiple_values"
    assert result["confidence"] == "low"


def test_derive_actor_name_prefers_first_last_over_initials():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Th.", "Thomas", "Hobbes")
    assert result == {"harmonised": "Thomas Hobbes",
                      "correction_type": "preferred_first_last_over_initials",
                      "confidence": "high"}


def test_derive_actor_name_leaves_initials_unresolved_without_alternative():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Th.", "", "")
    assert result == {"harmonised": "Th.",
                      "correction_type": "initials_or_abbreviation_unresolved",
                      "confidence": "low"}


def test_derive_actor_name_treats_triple_star_as_missing():
    """'***' is the BnF null marker used by PersonNameEvaluation's
    missing-value error case, not just blank/NA/NULL."""
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "", "")  # normalise() already turns "***" into ""
    assert result["correction_type"] == "unresolved_missing"
    assert nn.normalise("***") == ""


# ── derive_actor_name() ──────────────────────────────────────────────────────

def test_derive_actor_name_passes_through_when_actor_name_present():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("Voltaire", "", "")
    assert result == {"harmonised": "Voltaire", "correction_type": "none", "confidence": "high"}


def test_derive_actor_name_from_first_and_last():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "Jean", "Racine")
    assert result["harmonised"] == "Jean Racine"
    assert result["correction_type"] == "derived_from_first_last"
    assert result["confidence"] == "high"


def test_derive_actor_name_from_last_name_only_the_lucretius_case():
    """The colleague's exact case: actor_name and actor_first_name are empty,
    only actor_last_name carries the value."""
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "", "Lucretius")
    assert result["harmonised"] == "Lucretius"
    assert result["correction_type"] == "derived_from_first_last"
    assert result["confidence"] == "high"


def test_derive_actor_name_from_first_name_only():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "Voltaire", "")
    assert result["harmonised"] == "Voltaire"
    assert result["correction_type"] == "derived_from_first_last"


def test_derive_actor_name_unresolved_when_all_empty():
    nn = load_name_normaliser_module()
    result = nn.derive_actor_name("", "", "")
    assert result == {"harmonised": "", "correction_type": "unresolved_missing", "confidence": "low"}


# ── collect_unique_actors() ──────────────────────────────────────────────────

def test_collect_unique_actors_deduplicates_by_actor_uri(tmp_path):
    """Mirrors the real raw dataset: the same actor appears on multiple rows
    (one per external-link binding) with identical name fields repeated."""
    nn = load_name_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...cb124434672#about>", "actor_last_name": "Nicolas"},
        {"actor": "<...other>", "actor_name": "Voltaire"},
    ])

    actors = nn.collect_unique_actors(str(csv_path))

    assert len(actors) == 2
    assert actors["<...cb124434672#about>"] == {
        "actor_name": "", "actor_first_name": "", "actor_last_name": "Nicolas",
    }
    assert actors["<...other>"]["actor_name"] == "Voltaire"


def test_collect_unique_actors_ignores_rows_without_actor_uri(tmp_path):
    nn = load_name_normaliser_module()
    csv_path = tmp_path / "actors.csv"
    _write_actor_csv(csv_path, [{"actor": "", "actor_name": "Nobody"}])

    actors = nn.collect_unique_actors(str(csv_path))
    assert actors == {}


# ── run() end-to-end ──────────────────────────────────────────────────────────

def test_run_writes_harmonised_csv_with_expected_schema(tmp_path):
    nn = load_name_normaliser_module()
    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},
        {"actor": "A2", "actor_name": "Voltaire"},
        {"actor": "A3"},
    ])

    output_dir = tmp_path / "out"
    output_path = nn.run(str(input_path), str(output_dir))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = {row["actor_uri"]: row for row in csv.DictReader(f)}

    assert set(rows["A1"].keys()) == {
        "actor_uri", "actor_name_original", "actor_name_harmonised",
        "correction_type", "confidence",
    }
    assert rows["A1"]["actor_name_harmonised"] == "Lucretius"
    assert rows["A1"]["correction_type"] == "derived_from_first_last"

    assert rows["A2"]["actor_name_harmonised"] == "Voltaire"
    assert rows["A2"]["correction_type"] == "none"

    assert rows["A3"]["actor_name_harmonised"] == ""
    assert rows["A3"]["correction_type"] == "unresolved_missing"


def test_run_accepts_zip_input(tmp_path):
    nn = load_name_normaliser_module()
    csv_inner = tmp_path / "actor_data.csv"
    _write_actor_csv(csv_inner, [{"actor": "A1", "actor_last_name": "Lucretius"}])

    zip_path = tmp_path / "actor_data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_inner, arcname="actor_data.csv")

    output_path = nn.run(str(zip_path), str(tmp_path / "out"))

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["actor_name_harmonised"] == "Lucretius"


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


def test_run_writes_monitor_checkpoint_per_actor_and_stops_cleanly(monkeypatch, tmp_path):
    nn = load_name_normaliser_module()
    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(nn, "load_monitor_module", lambda monitor_script: fake_monitor)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [
        {"actor": "A1", "actor_last_name": "Lucretius"},
        {"actor": "A2", "actor_name": "Voltaire"},
    ])

    nn.run(str(input_path), str(tmp_path / "out"), use_monitor=True)

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 2 + 1  # one per actor + final
    assert "A1" in fake_monitor.update_calls[0]
    assert "A2" in fake_monitor.update_calls[1]
    assert fake_monitor.update_calls[-1] == "Completed actor_name harmonisation run"
    assert fake_monitor.stop_calls == [True]


def test_run_skips_monitor_when_disabled(monkeypatch, tmp_path):
    nn = load_name_normaliser_module()

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(nn, "load_monitor_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_last_name": "Lucretius"}])

    nn.run(str(input_path), str(tmp_path / "out"), use_monitor=False)


def test_load_monitor_module_resolves_real_monitor_script():
    nn = load_name_normaliser_module()
    monitor = nn.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")


def test_load_llm_module_resolves_real_llm_script():
    nn = load_name_normaliser_module()
    llm_module = nn.load_llm_module()

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
    nn = load_name_normaliser_module()
    fake_llm = FakeLLMModule()
    monkeypatch.setattr(nn, "load_llm_module", lambda: fake_llm)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_last_name": "Lucretius"}])
    output_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "name_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_dir),
        "--no-monitor",
    ])
    nn.main()

    assert len(fake_llm.run_calls) == 1
    call = fake_llm.run_calls[0]
    expected_output = str(output_dir / nn.OUTPUT_FILENAME_DEFAULT)
    assert call["heuristic_output_csv"] == expected_output
    assert call["output_path"] == expected_output
    assert call["cache_path"] == fake_llm.CACHE_PATH_DEFAULT
    assert call["model"] == "claude-opus-5"
    assert call["effort"] == "low"
    assert call["use_monitor"] is False


def test_main_no_llm_flag_skips_llm_step(monkeypatch, tmp_path):
    nn = load_name_normaliser_module()

    def fail_if_called():
        raise AssertionError("load_llm_module should not be called when --no-llm is passed")

    monkeypatch.setattr(nn, "load_llm_module", fail_if_called)

    input_path = tmp_path / "actors.csv"
    _write_actor_csv(input_path, [{"actor": "A1", "actor_last_name": "Lucretius"}])
    output_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "name_normaliser.py",
        "--input", str(input_path),
        "--output", str(output_dir),
        "--no-monitor",
        "--no-llm",
    ])
    nn.main()  # must not raise -> load_llm_module was never called

    assert (output_dir / nn.OUTPUT_FILENAME_DEFAULT).exists()
