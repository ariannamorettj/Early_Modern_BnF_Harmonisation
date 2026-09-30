import configparser
import csv
import importlib.util
import logging
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "07_graph_materialisation" / "scripts" / "bnf_graph_pipeline.py"
LOGGER = logging.getLogger("test_graph_pipeline")

PERSON = "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/Person"
ORG = "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/Organization"


def load_module():
    spec = importlib.util.spec_from_file_location("bnf_graph_pipeline", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_actor_iri_accepts_angle_bracketed_bnf_id():
    m = load_module()
    iri = "http://data.bnf.fr/ark:/12148/cb10001433g#about"
    assert m.resolve_actor_iri(f"<{iri}>") == iri


def test_roles_resolve_edition_ids_through_the_edition_table(tmp_path):
    """role_edition_map holds the bare FRBNF number; the real ARK has a check
    character, so ids must go through the edition table, and ids missing
    from it are skipped rather than turned into a guessed IRI."""
    m = load_module()
    actors = pd.DataFrame({
        "actor": ["http://data.bnf.fr/ark:/12148/cbA#about",
                  "http://data.bnf.fr/ark:/12148/cbB#about"],
        "role_edition_map": ["author:31015462;editor:999", "author:31015462"],
    })
    edition_map = {"31015462": "http://data.bnf.fr/ark:/12148/cb31015462k#about"}

    m._build_and_save_roles(actors, tmp_path, LOGGER, edition_map)

    with open(tmp_path / m.READY_FILES["roles"], newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["edition_iri"] for r in rows} == {edition_map["31015462"]}
    # Two authors of one edition share the edition's single authoring activity,
    # the same node mapping_bibliographic.yaml builds from the edition side.
    assert {r["role_activity_iri"] for r in rows} == {
        "http://data.bnf.fr/ark:/12148/cb31015462k#expr_creation_author"}
    assert len(rows) == 2


def test_dedicated_condition_columns_pair_fragments_with_their_guard():
    m = load_module()
    dedicated = m.dedicated_condition_columns("mapping_actors.yaml")
    assert dedicated["actor_birth_event"] == "actor_birth_obj"
    assert dedicated["actor_birth_ts"] == "actor_birth_obj"
    # The actor IRI is shared by many differently-guarded mappings.
    assert "actor" not in dedicated


def test_finalise_types_actors_once_and_drops_empty_fragment_nodes():
    m = load_module()
    df = pd.DataFrame({
        "actor": ["http://x.org/p#about", "http://x.org/o#about"],
        "entity_type": [PERSON, ORG],
        "actor_birth_obj": ["1700-01-01T00:00:00", ""],
        "actor_birth_event": ["http://x.org/p#birth_event", "http://x.org/o#birth_event"],
        "actor_birth_ts": ["http://x.org/p#birth_ts", "http://x.org/o#birth_ts"],
    })

    out = m.finalise_for_mapping(df, "mapping_actors.yaml", LOGGER)

    assert list(out["actor_if_person"]) == ["http://x.org/p#about", ""]
    assert list(out["actor_if_organization"]) == ["", "http://x.org/o#about"]
    assert list(out["actor_birth_event"]) == ["http://x.org/p#birth_event", ""]
    assert list(out["actor_birth_ts"]) == ["http://x.org/p#birth_ts", ""]
    # Columns the mapping references but the input lacks are added empty.
    assert (out["actor_profession"] == "").all()


def test_finalise_builds_wkt_point_from_harmonised_coordinates():
    m = load_module()
    df = pd.DataFrame({
        "edition_base": ["http://x.org/e1", "http://x.org/e2"],
        "publication_place": ["Mainz", ""],
        "longitude": ["8.2711", ""],
        "latitude": ["49.9929", ""],
    })
    out = m.finalise_for_mapping(df, "mapping_bibliographic.yaml", LOGGER)
    assert list(out["place_wkt"]) == ["POINT(8.2711 49.9929)", ""]
    assert list(out["edition_pub_place_norm_app"]) == ["http://x.org/e1#pub_place_norm_app", ""]


def test_runtime_mapping_points_every_source_at_the_profile_ready_dir(tmp_path):
    m = load_module()
    config = configparser.ConfigParser()
    config["__PATHS__"] = {"project_dir": str(SCRIPT_PATH.parents[1])}
    ready = tmp_path / "ready"

    out = m.runtime_mapping(config, "mapping_actors.yaml", ready, tmp_path, "sample")

    sources = [line.strip() for line in out.read_text(encoding="utf-8").splitlines()
               if line.strip().endswith("~csv")]
    assert sources
    assert all(s.startswith(f"- {ready.resolve().as_posix()}/") for s in sources)
