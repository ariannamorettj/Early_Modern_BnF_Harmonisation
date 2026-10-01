"""The synthetic ESTC samples in 00_test/data/estc_samples/ keep the column
structure of the COMHIS tables and load through the module 06 scripts."""

import csv
import importlib.util
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "00_test" / "data" / "estc_samples"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load("make_synthetic_samples", SAMPLES / "make_synthetic_samples.py")


def _rows(name):
    with open(SAMPLES / f"{name}.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def test_samples_have_the_comhis_columns_and_only_synthetic_ids():
    for name, columns in (("estc_actors_sample", generator.ACTOR_COLUMNS),
                          ("estc_actor_links_sample", generator.LINK_COLUMNS),
                          ("estc_core_sample", generator.CORE_COLUMNS)):
        header, rows = _rows(name)
        assert header == columns, name
        assert rows, name
    _, actors = _rows("estc_actors_sample")
    _, records = _rows("estc_core_sample")
    assert all(a["actor_id"].startswith("viaf_99999") for a in actors)
    assert all(r["estc_id"].startswith("Z") for r in records)


def test_samples_load_through_map_estc_actors():
    script = _load("map_estc_actors_samples", PROJECT_ROOT / "06_mapping" / "05_map_estc_actors.py")
    actors = script.load_estc_actors(str(SAMPLES / "estc_actors_sample.csv"))
    viaf_index, name_index = script.build_estc_indexes(actors)
    assert len(actors) == 27  # 30 actors, every tenth an organisation, which the script drops
    assert "99999000001" in viaf_index and name_index


def test_samples_load_through_map_estc_ecco(tmp_path):
    script = _load("map_estc_ecco_samples", PROJECT_ROOT / "06_mapping" / "03_map_estc_ecco.py")
    for name in ("estc_core", "estc_actor_links", "estc_actors"):
        shutil.copy(SAMPLES / f"{name}_sample.csv", tmp_path / f"{name}.csv")
    records = script.load_estc_directory(str(tmp_path))
    assert len(records) == 30
    assert all(len(r["authors"]) == 1 for r in records)  # one author link per record
