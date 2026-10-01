import csv
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ESTC_SCRIPT_PATH = PROJECT_ROOT / "06_mapping" / "03_map_estc_ecco.py"


def load_estc_module():
    spec = importlib.util.spec_from_file_location("map_estc_ecco", ESTC_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_bnf_csv(path, rows):
    fieldnames = ["bnf_id", "title", "year_first", "language", "author_name"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _write_estc_csv(path, rows):
    fieldnames = ["estc_id", "title", "author", "year", "language"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


# ── author_block_key / author_index ─────────────────────────────────────────

def test_author_block_key_uses_first_normalised_token():
    estc = load_estc_module()
    assert estc.author_block_key("Cicero, Marcus Tullius") == "cicero"
    assert estc.author_block_key("  ") == ""


def test_build_author_index_and_get_estc_author_candidates():
    estc = load_estc_module()
    records = [
        {"author": "Cicero, Marcus Tullius"},
        {"author": "Ovid"},
        {"author": ""},
    ]
    index = estc.build_author_index(records, "author")

    assert index["cicero"] == [0]
    assert index["ovid"] == [1]

    candidates = estc.get_estc_author_candidates("Cicero", index, max_candidates=10)
    assert candidates == [0]

    assert estc.get_estc_author_candidates("Cicero", index, max_candidates=0) == []
    assert estc.get_estc_author_candidates("", index, max_candidates=10) == []


# ── Pass 3: translations outside the year window (the colleague's point 1) ──

def test_run_mapping_finds_translation_far_outside_year_window(monkeypatch, tmp_path):
    """A translation published 150 years after the original must still be
    found via the author index, even though it falls way outside the
    Pass-2 ±year_window used for 'same edition in both catalogues'."""
    estc = load_estc_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(estc, "llm_translation_check",
                        lambda *a, **kw: (True, 0.9))

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Les Amours", "year_first": "1550",
         "language": "fr", "author_name": "Ovide"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "The Loves", "author": "Ovide",
         "year": "1700", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
    )

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["match_type"] == "llm"
    assert rows[0]["estc_id"] == "E1"


def test_run_mapping_no_translation_match_without_author_overlap(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(estc, "llm_translation_check",
                        lambda *a, **kw: (True, 0.9))

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Les Amours", "year_first": "1550",
         "language": "fr", "author_name": "Ovide"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "Some Other Work", "author": "Completely Different Author",
         "year": "1700", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
    )

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["match_type"] == "unmatched"


# ── Ambiguity detection (the colleague's point 2) ────────────────────────────

def test_run_mapping_flags_ambiguous_translation_for_multiple_sibling_candidates(monkeypatch, tmp_path):
    """Two independent translations of the same (e.g. classical) author,
    both outside the year window, both passing the LLM check: neither should
    be silently accepted as THE translation."""
    estc = load_estc_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(estc, "llm_translation_check",
                        lambda *a, **kw: (True, 0.85))

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Des Devoirs", "year_first": "1650",
         "language": "fr", "author_name": "Cicero"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "On Duties", "author": "Cicero",
         "year": "1680", "language": "en"},
        {"estc_id": "E2", "title": "Of Offices", "author": "Cicero",
         "year": "1720", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
    )

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(tmp_path / "report.json", encoding="utf-8") as f:
        import json
        stats = json.load(f)

    assert rows[0]["match_type"] == "ambiguous_translation"
    assert rows[0]["estc_id"] in {"E1", "E2"}  # highest-confidence kept
    assert rows[0]["notes"]  # alternates recorded
    assert stats["pass3_llm_ambiguous"] == 1
    assert stats["pass3_llm"] == 0


def test_run_mapping_single_translation_candidate_is_not_ambiguous(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(estc, "llm_translation_check",
                        lambda *a, **kw: (True, 0.9))

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Des Devoirs", "year_first": "1650",
         "language": "fr", "author_name": "Cicero"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "On Duties", "author": "Cicero",
         "year": "1680", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
    )

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["match_type"] == "llm"
    assert rows[0]["estc_id"] == "E1"


# ── Pass 2 (heuristic) always takes priority over Pass 3 (LLM) ─────────────

def test_run_mapping_heuristic_match_takes_priority_over_llm_candidate(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(estc, "llm_translation_check",
                        lambda *a, **kw: (True, 0.9))

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Les Fables", "year_first": "1600",
         "language": "fr", "author_name": "La Fontaine"},
    ])
    _write_estc_csv(estc_path, [
        # In-window, same title -> Pass-2 heuristic match
        {"estc_id": "E-SAME", "title": "Les Fables", "author": "La Fontaine",
         "year": "1600", "language": "fr"},
        # Author-indexed, far outside window -> would pass the LLM check
        {"estc_id": "E-TRANSLATION", "title": "The Fables", "author": "La Fontaine",
         "year": "1750", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
    )

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["match_type"] == "heuristic"
    assert rows[0]["estc_id"] == "E-SAME"


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


def test_run_mapping_writes_monitor_checkpoint_periodically_and_stops_cleanly(monkeypatch, tmp_path):
    """Checkpoints fire every MONITOR_CHECKPOINT_EVERY records and at the last
    one, not per record: with the cadence lowered to 2, a 2-record run skips
    record 1 and checkpoints record 2, then the completion checkpoint."""
    estc = load_estc_module()
    monkeypatch.setattr(estc, "MONITOR_CHECKPOINT_EVERY", 2)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_monitor = FakeMonitorModule()
    monkeypatch.setattr(estc, "load_monitor_module", lambda monitor_script: fake_monitor)

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Les Fables", "year_first": "1600",
         "language": "fr", "author_name": "La Fontaine"},
        {"bnf_id": "B2", "title": "Les Amours", "year_first": "1550",
         "language": "fr", "author_name": "Ovide"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "Unrelated", "author": "Nobody",
         "year": "1900", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
        use_monitor=True,
    )

    assert len(fake_monitor.start_calls) == 1
    assert len(fake_monitor.update_calls) == 1 + 1  # record 2 (last), completion
    assert "B2" in fake_monitor.update_calls[0]
    assert not any("B1" in call for call in fake_monitor.update_calls)
    assert fake_monitor.update_calls[-1] == "Completed ESTC/ECCO mapping run"
    assert fake_monitor.stop_calls == [True]


def test_run_mapping_skips_monitor_when_disabled(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fail_if_called(monitor_script):
        raise AssertionError("load_monitor_module should not be called when use_monitor=False")

    monkeypatch.setattr(estc, "load_monitor_module", fail_if_called)

    bnf_path = tmp_path / "bnf.csv"
    estc_path = tmp_path / "estc.csv"
    _write_bnf_csv(bnf_path, [
        {"bnf_id": "B1", "title": "Les Fables", "year_first": "1600",
         "language": "fr", "author_name": "La Fontaine"},
    ])
    _write_estc_csv(estc_path, [
        {"estc_id": "E1", "title": "Unrelated", "author": "Nobody",
         "year": "1900", "language": "en"},
    ])

    estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_path),
        output_path=str(tmp_path / "out.csv"),
        report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80,
        year_window=2, sleep=0,
        use_monitor=False,
    )


def test_load_monitor_module_resolves_real_monitor_script():
    estc = load_estc_module()
    monitor = estc.load_monitor_module()

    assert hasattr(monitor, "start_monitor_state")
    assert hasattr(monitor, "update_monitor_state")
    assert hasattr(monitor, "stop_monitor_state")


# ── COMHIS directory, actor bridge, scope, ambiguity, resume ─────────────────

def _write(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: "" for k in fieldnames}, **row})


def _comhis_dir(tmp_path, core_rows, link_rows, actor_rows):
    d = tmp_path / "estc"
    d.mkdir()
    _write(d / "estc_core.csv", ["estc_id", "primary_language", "publication_year",
                                 "short_title", "publication_place", "publication_country"], core_rows)
    _write(d / "estc_actor_links.csv", ["estc_id", "actor_id", "actor_role_author"], link_rows)
    _write(d / "estc_actors.csv", ["actor_id", "name_unified"], actor_rows)
    return d


EDITION_FIELDS = ["edition", "bnf_id", "title", "year_first", "author",
                  "language_harmonised", "publication_country"]
SWIFT = "http://data.bnf.fr/ark:/12148/cb11925870x#about"


def _setup_swift(tmp_path, core_rows):
    estc_dir = _comhis_dir(
        tmp_path, core_rows,
        [{"estc_id": r["estc_id"], "actor_id": "viaf_1", "actor_role_author": "TRUE"} for r in core_rows]
        + [{"estc_id": core_rows[0]["estc_id"], "actor_id": "printer_x", "actor_role_author": "FALSE"}],
        [{"actor_id": "viaf_1", "name_unified": "Swift, Jonathan"},
         {"actor_id": "printer_x", "name_unified": "Motte, Benjamin"}],
    )
    bnf_path = tmp_path / "bnf.csv"
    _write(bnf_path, EDITION_FIELDS, [
        {"edition": "<http://data.bnf.fr/ark:/12148/cb1#about>", "bnf_id": "1",
         "title": "Travels into several remote nations of the world. In four parts. By Lemuel Gulliver",
         "year_first": "1726", "author": f"<{SWIFT}>",
         "language_harmonised": "eng", "publication_country": "Great Britain"},
        {"edition": "<http://data.bnf.fr/ark:/12148/cb2#about>", "bnf_id": "2",
         "title": "Voyages de Gulliver", "year_first": "1727", "author": f"<{SWIFT}>",
         "language_harmonised": "fre", "publication_country": "France"},
    ])
    actors_path = tmp_path / "actors.csv"
    _write(actors_path, ["actor", "actor_name"], [{"actor": f"<{SWIFT}>", "actor_name": "Jonathan Swift"}])
    return estc_dir, bnf_path, actors_path


def _run(estc, tmp_path, estc_dir, bnf_path, actors_path, mapping_path=None, **kw):
    return estc.run_mapping(
        bnf_path=str(bnf_path), estc_path=str(estc_dir),
        output_path=str(tmp_path / "out.csv"), report_path=str(tmp_path / "report.json"),
        author_thr=0.80, title_thr=0.75, llm_thr=0.80, year_window=2, sleep=0,
        bnf_actors_path=str(actors_path),
        estc_actor_mapping_path=str(mapping_path) if mapping_path else None, **kw)


def _rows(tmp_path):
    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_heuristic_matches_names_in_either_order_and_skips_out_of_scope(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    estc_dir, bnf_path, actors_path = _setup_swift(tmp_path, [
        {"estc_id": "T1", "primary_language": "English", "publication_year": "1726",
         "short_title": "Travels into several remote nations of the world"},
    ])
    stats = _run(estc, tmp_path, estc_dir, bnf_path, actors_path)
    rows = _rows(tmp_path)

    # The French edition is outside the ESTC scope: not written.
    assert [r["BnF_edition_id"] for r in rows] == ["1"]
    assert rows[0]["match_type"] == "heuristic"
    assert rows[0]["estc_id"] == "T1"
    assert rows[0]["estc_author"] == "Swift, Jonathan"  # the printer is not an author
    assert stats["out_of_scope_this_run"] == 1


def test_actor_bridge_takes_priority_and_uses_the_estc_actor(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    estc_dir, bnf_path, actors_path = _setup_swift(tmp_path, [
        {"estc_id": "T1", "primary_language": "English", "publication_year": "1726",
         "short_title": "Travels into several remote nations of the world"},
    ])
    mapping = tmp_path / "estc_actor_mapping_confident.csv"
    _write(mapping, ["BnF_ID", "estc_actor_id"], [{"BnF_ID": f"<{SWIFT}>", "estc_actor_id": "viaf_1"}])
    _run(estc, tmp_path, estc_dir, bnf_path, actors_path, mapping)
    assert _rows(tmp_path)[0]["match_type"] == "actor_bridge"


def test_two_close_estc_records_of_the_same_year_are_ambiguous(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    title = "Travels into several remote nations of the world"
    estc_dir, bnf_path, actors_path = _setup_swift(tmp_path, [
        {"estc_id": "T1", "primary_language": "English", "publication_year": "1726", "short_title": title},
        {"estc_id": "T2", "primary_language": "English", "publication_year": "1726", "short_title": title},
    ])
    _run(estc, tmp_path, estc_dir, bnf_path, actors_path)
    row = _rows(tmp_path)[0]
    assert row["match_type"] == "ambiguous_heuristic"
    assert row["estc_id"] in {"T1", "T2"}
    assert "alternates" in row["notes"]


def test_near_tie_is_settled_by_the_bnf_year(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    title = "Travels into several remote nations of the world"
    estc_dir, bnf_path, actors_path = _setup_swift(tmp_path, [
        {"estc_id": "T0", "primary_language": "English", "publication_year": "1727", "short_title": title},
        {"estc_id": "T1", "primary_language": "English", "publication_year": "1726", "short_title": title},
    ])
    _run(estc, tmp_path, estc_dir, bnf_path, actors_path)
    row = _rows(tmp_path)[0]
    assert (row["match_type"], row["estc_id"], row["notes"]) == ("heuristic", "T1", "")


def test_title_similarity_compares_common_length_but_not_one_word_titles():
    estc = load_estc_module()
    long_bnf = "The Dunciad, an heroic poem. In three books. Dublin printed, London reprinted"
    assert estc.title_similarity(long_bnf, "The Dunciad, an heroic poem. In three books") > 0.8
    assert estc.title_similarity("Poems", "Poems on several occasions") < 0.75


def test_rerun_resumes_without_duplicating_rows(monkeypatch, tmp_path):
    estc = load_estc_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    estc_dir, bnf_path, actors_path = _setup_swift(tmp_path, [
        {"estc_id": "T1", "primary_language": "English", "publication_year": "1726",
         "short_title": "Travels into several remote nations of the world"},
    ])
    _run(estc, tmp_path, estc_dir, bnf_path, actors_path)
    stats = _run(estc, tmp_path, estc_dir, bnf_path, actors_path)
    assert len(_rows(tmp_path)) == 1
    assert stats["pass2_heuristic"] == 1


def test_title_similarity_rejects_shared_boilerplate_and_expands_ligatures():
    estc = load_estc_module()
    assert estc.title_similarity(
        "Ulysses, a tragedy, as written by N. Rowe,... and performed at the Theatre-Royal",
        "Jane Shore. A tragedy, by N. Rowe, Esq. As performed at") == 0.0
    assert estc.title_similarity("Historia naturae, variis experimentis",
                                 "Antonii le Grand Historia naturae, variis experimentis") > 0.5
    assert estc.title_similarity("Phaedra and Hippolitus, a tragedy", "Phædra and Hippolitus") > 0.75
