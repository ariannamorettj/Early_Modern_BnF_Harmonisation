import csv
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "02_sampling"))

import text_integrity as ti  # noqa: E402


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_issues_by_type():
    assert ti.detect_issues("Église catholique") == []
    assert ti.detect_issues("São Paulo") == []
    assert ti.detect_issues("Ã‰glise") == ["double_encoded"]
    assert ti.detect_issues("lâ€™auteur") == ["double_encoded"]
    assert ti.detect_issues("�glise") == ["replacement_char"]
    assert ti.detect_issues("a\x07b") == ["control_char"]
    assert ti.detect_issues('"France"@fr') == ["serialised_rdf_literal"]
    assert ti.detect_issues('"1750"^^<http://www.w3.org/2001/XMLSchema#gYear>') == ["serialised_rdf_literal"]
    # A title that merely contains quotes is not a serialised literal.
    assert ti.detect_issues('Le "Misanthrope" de Molière') == []


def test_unwrap_rdf_literal():
    assert ti.unwrap_rdf_literal('"France"@fr') == "France"
    assert ti.unwrap_rdf_literal('"Assemblée"@fr-FR') == "Assemblée"
    assert ti.unwrap_rdf_literal("Voltaire") == "Voltaire"


def test_iter_csv_rows_flags_invalid_utf8_without_stopping(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes("actor,actor_name\nA1,Église\n".encode("utf-8")
                     + b"A2,\xc9glise\n"  # Latin-1 byte: invalid UTF-8
                     + '"A3","""France""@fr"\n'.encode("utf-8"))
    rows = list(ti.iter_csv_rows(str(path)))
    assert [r["actor"] for _, r, _ in rows] == ["A1", "A2", "A3"]
    issues = {r["actor"]: ti.row_issues(r, valid) for _, r, valid in rows}
    assert issues["A1"] == {}
    assert issues["A2"]["actor_name"] == ["invalid_utf8"]
    assert issues["A3"] == {"actor_name": ["serialised_rdf_literal"]}


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["actor", "actor_name"])
        w.writeheader()
        w.writerows(rows)


def test_sample_script_groups_by_entity_and_is_reproducible(tmp_path):
    mod = load(PROJECT_ROOT / "02_sampling" / "05_text_issue_sample.py", "text_issue_sample")
    path = tmp_path / "actors.csv"
    rows = [{"actor": f"O{i}", "actor_name": f'"Org {i}"@fr'} for i in range(10)]
    rows += [{"actor": "O1", "actor_name": '"Org 1"@fr'}, {"actor": "P1", "actor_name": "Voltaire"}]
    _write(path, rows)

    sampled, counts, total = mod.sample_issues(str(path), n=3, seed=7)
    again, _, _ = mod.sample_issues(str(path), n=3, seed=7)
    assert total == 10                      # O1 counted once, P1 has no issue
    assert counts["serialised_rdf_literal"] == 10
    assert len({s["entity"] for s in sampled}) == 3
    assert sampled == again


def test_integrity_check_counts_per_column(tmp_path):
    mod = load(PROJECT_ROOT / "03_analysis" / "06_text_integrity_check.py", "text_integrity_check")
    path = tmp_path / "actors.csv"
    _write(path, [{"actor": "O1", "actor_name": '"Org"@fr'},
                  {"actor": "A1", "actor_name": "Ã©"},
                  {"actor": "A2", "actor_name": "Voltaire"}])
    result = mod.check_file(str(path))
    assert result["rows"] == 3
    assert result["rows_with_any_issue"] == 2
    assert result["by_column"]["actor_name"] == {"serialised_rdf_literal": 1, "double_encoded": 1}
    assert result["totals"]["replacement_char"] == 0
