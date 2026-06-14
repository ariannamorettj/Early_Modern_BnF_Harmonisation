#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained BnF graph materialisation pipeline.

Commands:
  preprocess   raw ZIP CSVs -> ready CSVs
  materialize  ready CSVs -> N-Triples through morph-kgc CLI
  merge        concatenate actors + bibliographic N-Triples
  validate     validate sampled N-Triples lines with RDFLib
  all          preprocess + materialize + merge + validate

The pipeline is intentionally conservative:
- sample and full profiles never share ready/output directories;
- morph-kgc is called as a subprocess, not via materialize_set();
- malformed IRI values are removed before graph generation;
- all generated files are kept inside the 07_graph_materialisation folder.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import logging
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = lambda x, **kwargs: x

ENTITY_TYPE_MAP: dict[str, str] = {
    "http://xmlns.com/foaf/0.1/Person": "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/Person",
    "http://xmlns.com/foaf/0.1/Organization": "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/Organization",
}

GENDER_MAP: dict[str, str] = {
    "male": "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/male",
    "female": "https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/female",
}

ROLE_AAT_MAP: dict[str, str] = {
    "author":      "http://vocab.getty.edu/aat/300025492",
    "editor":      "http://vocab.getty.edu/aat/300312355",
    "translator":  "http://vocab.getty.edu/aat/300069831",
    "illustrator": "http://vocab.getty.edu/aat/300025164",
}

BNF_ARK_BASE      = "http://data.bnf.fr/ark:/12148/"
VIAF_URI_BASE     = "http://viaf.org/viaf/"
WIKIDATA_URI_BASE = "http://www.wikidata.org/entity/"
ISNI_URI_BASE     = "https://isni.org/isni/"
LC_URI_BASE       = "http://id.loc.gov/authorities/names/"
ESTC_URI_BASE     = "https://estc.bl.uk/"

READY_FILES = {
    "actors":      "bnf_actors_ready.csv",
    "editions":    "bnf_editions_ready.csv",
    "links_exact": "bnf_actors_ready_links_exact.csv",
    "links_close": "bnf_actors_ready_links_close.csv",
    "roles":       "bnf_actors_ready_roles.csv",
}

ACTOR_MAIN_IRI_COLS = ["actor"]
ACTOR_OPTIONAL_IRI_COLS = ["actor_country", "actor_language"]
ACTOR_LINK_COLS = ["actor_link_exact", "actor_link_close"]

BIB_MAIN_IRI_COLS = ["edition"]
BIB_OPTIONAL_IRI_COLS = [
    "expression",
    "work",
    "language",
    "record_type",
    "subject_topic",
    "digital_copy_link",
    "author",
    "editor",
    "translator",
    "illustrator",
    "publisher_2",
]

ALL_IRI_COLS = sorted(set(
    ACTOR_MAIN_IRI_COLS
    + ACTOR_OPTIONAL_IRI_COLS
    + ACTOR_LINK_COLS
    + BIB_MAIN_IRI_COLS
    + BIB_OPTIONAL_IRI_COLS
    + ["entity_type"]
))


def read_config(config_path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    loaded = config.read(config_path)
    if not loaded:
        raise FileNotFoundError(f"Config not found: {config_path}")
    config["__PATHS__"] = {"project_dir": str(config_path.resolve().parent)}
    return config


def project_dir(config: configparser.ConfigParser) -> Path:
    return Path(config["__PATHS__"]["project_dir"])


def resolve_in_project(config: configparser.ConfigParser, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_dir(config) / path


def setup_logger(config: configparser.ConfigParser) -> logging.Logger:
    logs_dir = resolve_in_project(config, config["DIRECTORIES"].get("logs_dir", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("bnf_graph_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(logs_dir / "bnf_graph_pipeline.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


def get_profile_dirs(config: configparser.ConfigParser, profile: str) -> tuple[Path, Path]:
    if profile == "full":
        ready = config["DIRECTORIES"]["ready_full_dir"]
        output = config["DIRECTORIES"]["output_full_dir"]
    elif profile == "sample":
        ready = config["DIRECTORIES"]["ready_sample_dir"]
        output = config["DIRECTORIES"]["output_sample_dir"]
    else:
        raise ValueError("profile must be 'full' or 'sample'")
    return resolve_in_project(config, ready), resolve_in_project(config, output)


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "<na>", "na", "n/a"}:
        return ""
    return text


def strip_angle_brackets(value: object) -> str:
    text = clean_cell(value)
    text = re.sub(r"^\s*<\s*", "", text)
    text = re.sub(r"\s*>\s*$", "", text)
    return text.strip()


def is_valid_http_iri(value: object) -> bool:
    """Accept only usable HTTP(S) IRIs for RDF URI positions."""
    text = strip_angle_brackets(value)
    if not text:
        return False
    if any(ch.isspace() for ch in text):
        return False
    if text.startswith("://"):
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def clean_required_iri(value: object) -> str:
    text = strip_angle_brackets(value)
    return text if is_valid_http_iri(text) else ""


def clean_optional_iri(value: object) -> str:
    text = strip_angle_brackets(value)
    return text if is_valid_http_iri(text) else ""


def clean_multivalue_iri_cell(value: object) -> str:
    """Clean a semicolon-separated IRI cell and keep only valid HTTP(S) IRIs."""
    text = strip_angle_brackets(value)
    if not text:
        return ""
    parts = [strip_angle_brackets(part) for part in re.split(r"\s*;\s*", text) if part.strip()]
    good = [part for part in parts if is_valid_http_iri(part)]
    return "; ".join(good)


def make_base_iri(value: object) -> str:
    text = clean_required_iri(value)
    return text.split("#")[0] if text else ""


def add_fragment(value: object, fragment: str) -> str:
    base = make_base_iri(value)
    return f"{base}#{fragment}" if base else ""


def normalize_date(value: object) -> str:
    text = clean_cell(value)
    if not text:
        return ""
    if len(text) == 4 and text.isdigit():
        return f"{text}-01-01T00:00:00"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T00:00:00"
    return ""


def read_csv_safe(path: Path, sample: int = 0) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".zip":
        frames: list[pd.DataFrame] = []
        total = 0
        with zipfile.ZipFile(path) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise FileNotFoundError(f"No CSV found inside ZIP: {path}")
            for name in csv_names:
                with zf.open(name) as fh:
                    try:
                        df = pd.read_csv(fh, encoding="utf-8", low_memory=False, keep_default_na=False)
                    except UnicodeDecodeError:
                        fh.seek(0)
                        df = pd.read_csv(fh, encoding="latin1", low_memory=False, keep_default_na=False)
                frames.append(df)
                total += len(df)
                if sample and total >= sample:
                    break
        out = pd.concat(frames, ignore_index=True)
        return out.head(sample) if sample else out

    try:
        df = pd.read_csv(path, encoding="utf-8", low_memory=False, keep_default_na=False)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin1", low_memory=False, keep_default_na=False)
    return df.head(sample) if sample else df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8", quoting=csv.QUOTE_ALL)


def explode_multivalue_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df[col] = df[col].fillna("").astype(str)
    df[f"{col}_list"] = df[col].apply(
        lambda x: [part.strip() for part in re.split(r"\s*;\s*", x) if part.strip()]
    )
    df = df.explode(f"{col}_list").reset_index(drop=True)
    df[col] = df[f"{col}_list"]
    df = df.drop(columns=[f"{col}_list"])
    df = df[df[col].apply(is_valid_http_iri)].copy()
    df["link_idx"] = df.groupby("actor", sort=False).cumcount() + 1
    return df


def clean_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str)
    return df


# ── Enriched-input helpers ─────────────────────────────────────────────────────

def resolve_actor_iri(bnf_id: str) -> str:
    """Convert a BnF_ID to a full actor IRI (http://data.bnf.fr/ark:/12148/...)."""
    s = bnf_id.strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s if "#" in s else s + "#about"
    if s.lower().startswith("cb"):
        return f"{BNF_ARK_BASE}{s}#about"
    if s.isdigit():
        return f"{BNF_ARK_BASE}cb{s}#about"
    return ""


def resolve_edition_iri(edition_id: str) -> str:
    """Convert an edition ID to a full edition IRI."""
    s = edition_id.strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s if "#" in s else s + "#about"
    if s.lower().startswith("cb"):
        return f"{BNF_ARK_BASE}{s}#about"
    if s.isdigit():
        return f"{BNF_ARK_BASE}cb{s}#about"
    return ""


def parse_role_edition_map(role_map: str) -> list[tuple[str, str]]:
    """Parse 'author:id1,id2;editor:id3' into [(role, edition_id), ...] pairs."""
    result: list[tuple[str, str]] = []
    if not role_map or clean_cell(role_map) == "":
        return result
    for segment in role_map.split(";"):
        segment = segment.strip()
        if ":" not in segment:
            continue
        role, ids_str = segment.split(":", 1)
        role = role.strip().lower()
        for eid in ids_str.split(","):
            eid = eid.strip()
            if eid:
                result.append((role, eid))
    return result


def _add_authority_uris(df: pd.DataFrame) -> pd.DataFrame:
    """Add viaf_uri, wikidata_uri, isni_uri, lc_uri columns from raw ID columns."""
    def _uri(val: object, base: str, strip_spaces: bool = False) -> str:
        s = clean_cell(val)
        if strip_spaces:
            s = s.replace(" ", "")
        return f"{base}{s}" if s else ""

    df["viaf_uri"]     = df.get("viaf_id",  pd.Series("", index=df.index)).apply(
        lambda v: _uri(v, VIAF_URI_BASE))
    df["wikidata_uri"] = df.get("qid", pd.Series("", index=df.index)).apply(
        lambda v: _uri(
            v if str(v).startswith("Q") else ("Q" + str(v)) if clean_cell(v) else v,
            WIKIDATA_URI_BASE,
        ))
    df["isni_uri"]     = df.get("isni", pd.Series("", index=df.index)).apply(
        lambda v: _uri(v, ISNI_URI_BASE, strip_spaces=True))
    df["lc_uri"]       = df.get("lc_id",  pd.Series("", index=df.index)).apply(
        lambda v: _uri(v, LC_URI_BASE))
    return df


def _build_and_save_roles(
    df: pd.DataFrame,
    ready_dir: Path,
    logger: logging.Logger,
) -> None:
    """Explode role_edition_map into a ready CSV for mapping_roles.yaml."""
    if "role_edition_map" not in df.columns:
        logger.info("[PREPROCESS][ROLES] no role_edition_map column — skipping roles CSV")
        return

    rows: list[dict] = []
    for _, row in df.iterrows():
        actor_iri = clean_cell(row.get("actor", ""))
        if not actor_iri:
            continue
        actor_base = make_base_iri(actor_iri)
        role_pairs = parse_role_edition_map(clean_cell(row.get("role_edition_map", "")))
        role_counts: dict[str, int] = {}
        for role, edition_id in role_pairs:
            aat = ROLE_AAT_MAP.get(role, "")
            if not aat:
                continue
            edition_iri = resolve_edition_iri(edition_id)
            edition_base = make_base_iri(edition_iri)
            if not edition_iri or not edition_base:
                continue
            idx = role_counts.get(role, 0) + 1
            role_counts[role] = idx
            rows.append({
                "actor_iri":            actor_iri,
                "edition_iri":          edition_iri,
                "edition_base":         edition_base,
                "edition_expr_creation": f"{edition_base}#expr_creation",
                "role":                 role,
                "role_activity_iri":    f"{edition_base}#expr_creation_{role}_{idx}",
                "role_aat":             aat,
            })

    roles_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["actor_iri", "edition_iri", "edition_base",
                 "edition_expr_creation", "role", "role_activity_iri", "role_aat"])
    roles_path = ready_dir / READY_FILES["roles"]
    save_csv(roles_df, roles_path)
    logger.info(f"[PREPROCESS][ROLES] {roles_path} ({len(roles_df)} rows)")


def _find_enriched_inputs(config: configparser.ConfigParser, proj: Path) -> dict[str, Path | None]:
    """Return resolved paths for enriched/optimised upstream CSVs, or None if absent."""
    def _resolve(section: str, key: str) -> Path | None:
        if section not in config or key not in config[section]:
            return None
        p = proj / config[section][key]
        return p if p.exists() else None

    return {
        "actors_enriched":  _resolve("ENRICHED_INPUTS", "actors_enriched_csv"),
        "editions_enriched": _resolve("ENRICHED_INPUTS", "editions_enriched_csv"),
        "actors_optimised": _resolve("ENRICHED_INPUTS", "actors_optimised_csv"),
        "actors_minimal":   _resolve("ENRICHED_INPUTS", "actors_minimal_csv"),
    }


def preprocess_actors(raw_path: Path, ready_dir: Path, sample: int, logger: logging.Logger) -> None:
    logger.info(f"[PREPROCESS][ACTORS] raw input: {raw_path}")
    df = read_csv_safe(raw_path, sample=sample)
    logger.info(f"[PREPROCESS][ACTORS] raw rows read: {len(df)}")

    for col in ["actor", "actor_country", "actor_language"]:
        if col in df.columns:
            df[col] = df[col].apply(strip_angle_brackets)

    for col in ACTOR_LINK_COLS:
        if col in df.columns:
            df[col] = df[col].apply(clean_multivalue_iri_cell)

    if "actor" in df.columns:
        before = len(df)
        df["actor"] = df["actor"].apply(clean_required_iri)
        df = df[df["actor"] != ""].copy()
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[PREPROCESS][ACTORS] dropped invalid actor IRI rows: {dropped}")

    for col in ACTOR_OPTIONAL_IRI_COLS:
        if col in df.columns:
            invalid = ((df[col].astype(str).str.strip() != "") & (~df[col].apply(is_valid_http_iri))).sum()
            if invalid:
                logger.warning(f"[PREPROCESS][ACTORS] cleared invalid optional IRI values in {col}: {invalid}")
            df[col] = df[col].apply(clean_optional_iri)

    if "entity_type" in df.columns:
        df["entity_type"] = df["entity_type"].apply(strip_angle_brackets)
        df["entity_type"] = df["entity_type"].map(lambda v: ENTITY_TYPE_MAP.get(str(v).strip(), str(v).strip()))

    if "actor_gender" in df.columns:
        df["actor_gender_obj"] = df["actor_gender"].map(lambda v: GENDER_MAP.get(str(v).strip().lower(), ""))

    if "actor" in df.columns:
        df["actor_base"] = df["actor"].apply(make_base_iri)
        fragments = {
            "actor_app_fullname": "app_fullname",
            "actor_app_firstname": "app_firstname",
            "actor_app_lastname": "app_lastname",
            "actor_gender_aa": "gender_aa",
            "actor_language_aa": "language_aa",
            "actor_birth_event": "birth_event",
            "actor_birth_ts": "birth_ts",
            "actor_death_event": "death_event",
            "actor_death_ts": "death_ts",
            "actor_start_event": "start_event",
            "actor_start_ts": "start_ts",
            "actor_end_event": "end_event",
            "actor_end_ts": "end_ts",
            "actor_profession_lo": "profession_lo",
        }
        for out_col, fragment in fragments.items():
            df[out_col] = df["actor_base"].apply(lambda value, frag=fragment: add_fragment(value, frag))

    for date_col in ["actor_birth", "actor_death", "actor_start", "actor_end"]:
        if date_col in df.columns:
            df[f"{date_col}_obj"] = df[date_col].apply(normalize_date)

    df = clean_object_columns(df)
    df = df.drop(columns=["__internal_csv_path", "link_idx"], errors="ignore")

    ready_dir.mkdir(parents=True, exist_ok=True)
    main_path = ready_dir / READY_FILES["actors"]
    save_csv(df, main_path)
    logger.info(f"[PREPROCESS][ACTORS] ready main: {main_path} ({len(df)} rows)")

    if "actor_link_exact" in df.columns:
        exact = explode_multivalue_column(df, "actor_link_exact")
        keep = ["actor", "actor_base", "actor_link_exact", "link_idx"]
        exact = exact[[c for c in keep if c in exact.columns]]
        exact_path = ready_dir / READY_FILES["links_exact"]
        save_csv(exact, exact_path)
        logger.info(f"[PREPROCESS][ACTORS] ready exact links: {exact_path} ({len(exact)} rows)")

    if "actor_link_close" in df.columns:
        close = explode_multivalue_column(df, "actor_link_close")
        keep = ["actor", "actor_base", "actor_link_close", "link_idx"]
        close = close[[c for c in keep if c in close.columns]]
        close_path = ready_dir / READY_FILES["links_close"]
        save_csv(close, close_path)
        logger.info(f"[PREPROCESS][ACTORS] ready close links: {close_path} ({len(close)} rows)")


def preprocess_bibliographic(raw_path: Path, ready_dir: Path, sample: int, logger: logging.Logger) -> None:
    logger.info(f"[PREPROCESS][BIB] raw input: {raw_path}")
    df = read_csv_safe(raw_path, sample=sample)
    logger.info(f"[PREPROCESS][BIB] raw rows read: {len(df)}")

    for col in ["edition"]:
        if col in df.columns:
            df[col] = df[col].apply(strip_angle_brackets)

    if "edition" in df.columns:
        before = len(df)
        df["edition"] = df["edition"].apply(clean_required_iri)
        df = df[df["edition"] != ""].copy()
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[PREPROCESS][BIB] dropped invalid edition IRI rows: {dropped}")

    for col in BIB_OPTIONAL_IRI_COLS:
        if col in df.columns:
            # If a field contains multiple semicolon-separated IRIs, keep only the first valid value.
            # The current YARRRML mappings expect a single IRI per cell.
            def clean_bib_optional(value: object) -> str:
                cleaned = clean_multivalue_iri_cell(value)
                if not cleaned:
                    return ""
                return cleaned.split("; ")[0]

            invalid = ((df[col].astype(str).str.strip() != "") & (df[col].apply(clean_bib_optional) == "")).sum()
            if invalid:
                logger.warning(f"[PREPROCESS][BIB] cleared invalid optional IRI values in {col}: {invalid}")
            df[col] = df[col].apply(clean_bib_optional)

    if "edition" in df.columns:
        df["edition_base"] = df["edition"].apply(make_base_iri)

    if "year_first" in df.columns and "year_range" in df.columns:
        df["year_range"] = df["year_range"].fillna("").astype(str)
        df["year_first"] = df["year_first"].fillna("").astype(str)
        mask = (df["year_range"] == "") & (df["year_first"] != "")
        df.loc[mask, "year_range"] = df.loc[mask, "year_first"]

    fragments = {
        "edition_bnf_id": "bnf_id",
        "edition_title": "title",
        "edition_ts_year_first": "ts_year_first",
        "edition_ts_year_range": "ts_year_range",
        "edition_pub_place": "pub_place",
        "edition_pub_place_app": "pub_place_app",
        "edition_pub_actor": "pub_actor",
        "edition_pub_actor_app": "pub_actor_app",
        "edition_digital_obj": "digital_obj",
        "edition_digital_id": "digital_id",
        "edition_expr_creation": "expr_creation",
        "edition_expr_creation_author": "expr_creation_author",
        "edition_expr_creation_editor": "expr_creation_editor",
        "edition_expr_creation_translator": "expr_creation_translator",
        "edition_expr_creation_illustrator": "expr_creation_illustrator",
    }
    for out_col, fragment in fragments.items():
        df[out_col] = df["edition_base"].apply(lambda value, frag=fragment: add_fragment(value, frag))

    df = clean_object_columns(df)
    df = df.drop(columns=["__internal_csv_path"], errors="ignore")
    df = df.dropna(axis=1, how="all")

    ready_dir.mkdir(parents=True, exist_ok=True)
    out_path = ready_dir / READY_FILES["editions"]
    save_csv(df, out_path)
    logger.info(f"[PREPROCESS][BIB] ready editions: {out_path} ({len(df)} rows)")


def preprocess_enriched_actors(
    actors_path: Path,
    minimal_path: Path | None,
    ready_dir: Path,
    sample: int,
    logger: logging.Logger,
) -> None:
    """Preprocess actors from enriched CSV (module 06 primary / module 05 fallback)."""
    logger.info(f"[PREPROCESS][ACTORS] enriched input: {actors_path}")
    df = read_csv_safe(actors_path, sample=sample)
    logger.info(f"[PREPROCESS][ACTORS] rows read: {len(df)}")

    # Merge link columns from minimal CSV if missing from the enriched CSV
    if minimal_path and minimal_path.exists():
        needs_links = "actor_link_exact" not in df.columns or "actor_link_close" not in df.columns
        if needs_links:
            logger.info(f"[PREPROCESS][ACTORS] merging link columns from: {minimal_path}")
            min_df = read_csv_safe(minimal_path)
            key = "BnF_ID" if "BnF_ID" in min_df.columns else None
            if key and key in df.columns:
                link_cols = [c for c in ["actor_link_exact", "actor_link_close"]
                             if c in min_df.columns]
                if link_cols:
                    df = df.merge(min_df[[key] + link_cols], on=key, how="left",
                                  suffixes=("", "_min"))

    # Resolve actor IRI from BnF_ID when no 'actor' column is present
    if "actor" not in df.columns:
        if "BnF_ID" in df.columns:
            df["actor"] = df["BnF_ID"].apply(lambda v: resolve_actor_iri(clean_cell(v)))
        else:
            raise ValueError(
                "Enriched actors CSV has neither 'actor' nor 'BnF_ID' column"
            )

    # Add authority URI columns (viaf_uri, wikidata_uri, isni_uri, lc_uri)
    df = _add_authority_uris(df)

    # Strip angle brackets from IRI columns
    for col in ["actor", "actor_country", "actor_language"]:
        if col in df.columns:
            df[col] = df[col].apply(strip_angle_brackets)

    for col in ACTOR_LINK_COLS:
        if col in df.columns:
            df[col] = df[col].apply(clean_multivalue_iri_cell)

    if "actor" in df.columns:
        before = len(df)
        df["actor"] = df["actor"].apply(clean_required_iri)
        df = df[df["actor"] != ""].copy()
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[PREPROCESS][ACTORS] dropped invalid actor IRI rows: {dropped}")

    for col in ACTOR_OPTIONAL_IRI_COLS:
        if col in df.columns:
            df[col] = df[col].apply(clean_optional_iri)

    if "entity_type" in df.columns:
        df["entity_type"] = df["entity_type"].apply(strip_angle_brackets)
        df["entity_type"] = df["entity_type"].map(
            lambda v: ENTITY_TYPE_MAP.get(str(v).strip(), str(v).strip()))

    if "actor_gender" in df.columns:
        df["actor_gender_obj"] = df["actor_gender"].map(
            lambda v: GENDER_MAP.get(str(v).strip().lower(), ""))

    if "actor" in df.columns:
        df["actor_base"] = df["actor"].apply(make_base_iri)
        fragments = {
            "actor_app_fullname":  "app_fullname",
            "actor_app_firstname": "app_firstname",
            "actor_app_lastname":  "app_lastname",
            "actor_gender_aa":     "gender_aa",
            "actor_language_aa":   "language_aa",
            "actor_birth_event":   "birth_event",
            "actor_birth_ts":      "birth_ts",
            "actor_death_event":   "death_event",
            "actor_death_ts":      "death_ts",
            "actor_start_event":   "start_event",
            "actor_start_ts":      "start_ts",
            "actor_end_event":     "end_event",
            "actor_end_ts":        "end_ts",
            "actor_profession_lo": "profession_lo",
        }
        for out_col, fragment in fragments.items():
            df[out_col] = df["actor_base"].apply(
                lambda v, frag=fragment: add_fragment(v, frag))

    for date_col in ["actor_birth", "actor_death", "actor_start", "actor_end"]:
        if date_col in df.columns:
            df[f"{date_col}_obj"] = df[date_col].apply(normalize_date)

    # Generate roles CSV from role_edition_map before column clean-up
    _build_and_save_roles(df, ready_dir, logger)

    df = clean_object_columns(df)
    df = df.drop(columns=["__internal_csv_path", "link_idx"], errors="ignore")

    ready_dir.mkdir(parents=True, exist_ok=True)
    main_path = ready_dir / READY_FILES["actors"]
    save_csv(df, main_path)
    logger.info(f"[PREPROCESS][ACTORS] ready main: {main_path} ({len(df)} rows)")

    if "actor_link_exact" in df.columns:
        exact = explode_multivalue_column(df, "actor_link_exact")
        keep = ["actor", "actor_base", "actor_link_exact", "link_idx"]
        exact = exact[[c for c in keep if c in exact.columns]]
        save_csv(exact, ready_dir / READY_FILES["links_exact"])
        logger.info(f"[PREPROCESS][ACTORS] ready exact links: {len(exact)} rows")

    if "actor_link_close" in df.columns:
        close = explode_multivalue_column(df, "actor_link_close")
        keep = ["actor", "actor_base", "actor_link_close", "link_idx"]
        close = close[[c for c in keep if c in close.columns]]
        save_csv(close, ready_dir / READY_FILES["links_close"])
        logger.info(f"[PREPROCESS][ACTORS] ready close links: {len(close)} rows")


def preprocess_enriched_bibliographic(
    editions_path: Path,
    ready_dir: Path,
    sample: int,
    logger: logging.Logger,
) -> None:
    """Preprocess editions from enriched CSV (module 06 primary / module 05 fallback)."""
    logger.info(f"[PREPROCESS][BIB] enriched input: {editions_path}")
    df = read_csv_safe(editions_path, sample=sample)
    logger.info(f"[PREPROCESS][BIB] rows read: {len(df)}")

    # Build estc_uri from estc_id
    if "estc_id" in df.columns:
        df["estc_uri"] = df["estc_id"].apply(
            lambda v: f"{ESTC_URI_BASE}{clean_cell(v)}" if clean_cell(v) else "")
    else:
        df["estc_uri"] = ""

    # Apply standard bibliographic derivation (same logic as preprocess_bibliographic)
    for col in ["edition"]:
        if col in df.columns:
            df[col] = df[col].apply(strip_angle_brackets)

    if "edition" in df.columns:
        before = len(df)
        df["edition"] = df["edition"].apply(clean_required_iri)
        df = df[df["edition"] != ""].copy()
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[PREPROCESS][BIB] dropped invalid edition IRI rows: {dropped}")

    for col in BIB_OPTIONAL_IRI_COLS:
        if col in df.columns:
            def clean_bib_optional(value: object) -> str:
                cleaned = clean_multivalue_iri_cell(value)
                return cleaned.split("; ")[0] if cleaned else ""
            df[col] = df[col].apply(clean_bib_optional)

    if "edition" in df.columns:
        df["edition_base"] = df["edition"].apply(make_base_iri)

    if "year_first" in df.columns and "year_range" in df.columns:
        df["year_range"] = df["year_range"].fillna("").astype(str)
        df["year_first"] = df["year_first"].fillna("").astype(str)
        mask = (df["year_range"] == "") & (df["year_first"] != "")
        df.loc[mask, "year_range"] = df.loc[mask, "year_first"]

    fragments = {
        "edition_bnf_id":                    "bnf_id",
        "edition_title":                     "title",
        "edition_ts_year_first":             "ts_year_first",
        "edition_ts_year_range":             "ts_year_range",
        "edition_pub_place":                 "pub_place",
        "edition_pub_place_app":             "pub_place_app",
        "edition_pub_actor":                 "pub_actor",
        "edition_pub_actor_app":             "pub_actor_app",
        "edition_digital_obj":               "digital_obj",
        "edition_digital_id":                "digital_id",
        "edition_expr_creation":             "expr_creation",
        "edition_expr_creation_author":      "expr_creation_author",
        "edition_expr_creation_editor":      "expr_creation_editor",
        "edition_expr_creation_translator":  "expr_creation_translator",
        "edition_expr_creation_illustrator": "expr_creation_illustrator",
    }
    for out_col, fragment in fragments.items():
        df[out_col] = df["edition_base"].apply(
            lambda v, frag=fragment: add_fragment(v, frag))

    df = clean_object_columns(df)
    df = df.drop(columns=["__internal_csv_path"], errors="ignore")
    df = df.dropna(axis=1, how="all")

    ready_dir.mkdir(parents=True, exist_ok=True)
    out_path = ready_dir / READY_FILES["editions"]
    save_csv(df, out_path)
    logger.info(f"[PREPROCESS][BIB] ready editions: {out_path} ({len(df)} rows)")


def require_ready_files(ready_dir: Path, target: str = "all") -> None:
    if target == "actors":
        required = [READY_FILES["actors"], READY_FILES["links_exact"], READY_FILES["links_close"]]
    elif target == "bibliographic":
        required = [READY_FILES["editions"]]
    elif target == "roles":
        required = [READY_FILES["roles"]]
    else:
        required = list(READY_FILES.values())
    missing = [name for name in required if not (ready_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing ready CSV files in {ready_dir}: {missing}. Run preprocess first.")


def write_morph_config(
    config: configparser.ConfigParser,
    profile: str,
    target: str,
    ready_dir: Path,
    target_tmp_dir: Path,
    runtime_dir: Path,
) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target_tmp_dir.mkdir(parents=True, exist_ok=True)

    cfg = configparser.ConfigParser()
    cfg["CONFIGURATION"] = {
        "na_values": ',,#N/A,N/A,#N/A N/A,n/a,NA,<NA>,#NA,NULL,null,nan,None,""',
        "output_dir": str(target_tmp_dir.resolve()),
        "output_format": config["MORPH_KGC"].get("output_format", "N-TRIPLES"),
        "output_serialization": config["MORPH_KGC"].get("output_serialization", "ntriples"),
        "only_printable_characters": config["MORPH_KGC"].get("only_printable_characters", "no"),
        "safe_percent_encoding": "",
        "mapping_partitioning": config["MORPH_KGC"].get("mapping_partitioning", "NO"),
        "infer_sql_datatypes": config["MORPH_KGC"].get("infer_sql_datatypes", "no"),
        "logging_level": config["MORPH_KGC"].get("logging_level", "INFO"),
        "logs_file": "",
        "project_iri_base": config["MORPH_KGC"].get("project_iri_base", "https://w3id.org/bnf/ontology/chad-ap/data/"),
        "udfs": str((project_dir(config) / config["MORPH_KGC"].get("udfs", "udfs.py")).resolve()),
    }

    if target == "actors":
        cfg["DataSource1"] = {
            "mappings": str((project_dir(config) / "mapping_actors.yaml").resolve()),
            "mapping_format": "YARRRML",
            "file_path": str((ready_dir / READY_FILES["actors"]).resolve()),
            "ready_input_dir": str(ready_dir.resolve()),
            "source_type": "csv",
            "output_file": str((target_tmp_dir / "knowledge-graph_actors.nt").resolve()),
            "delimiter": ",",
        }
    elif target == "bibliographic":
        cfg["DataSource1"] = {
            "mappings": str((project_dir(config) / "mapping_bibliographic.yaml").resolve()),
            "mapping_format": "YARRRML",
            "file_path": str((ready_dir / READY_FILES["editions"]).resolve()),
            "ready_input_dir": str(ready_dir.resolve()),
            "source_type": "csv",
            "output_file": str((target_tmp_dir / "knowledge-graph_bibliographic.nt").resolve()),
            "delimiter": ",",
        }
    elif target == "roles":
        cfg["DataSource1"] = {
            "mappings": str((project_dir(config) / "mapping_roles.yaml").resolve()),
            "mapping_format": "YARRRML",
            "file_path": str((ready_dir / READY_FILES["roles"]).resolve()),
            "ready_input_dir": str(ready_dir.resolve()),
            "source_type": "csv",
            "output_file": str((target_tmp_dir / "knowledge-graph_roles.nt").resolve()),
            "delimiter": ",",
        }
    else:
        raise ValueError("target must be actors, bibliographic, or roles")

    path = runtime_dir / f"morph_{profile}_{target}.ini"
    with path.open("w", encoding="utf-8") as fh:
        cfg.write(fh)
    return path


def run_command(cmd: list[str], log_path: Path, cwd: Path, logger: logging.Logger) -> None:
    logger.info("[RUN] " + " ".join(cmd))
    logger.info(f"[RUN] cwd={cwd}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        code = process.wait()
    if code != 0:
        raise RuntimeError(f"Command failed with exit code {code}: {' '.join(cmd)}")


def count_lines(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def concatenate_nt_files(source_dir: Path, final_path: Path, logger: logging.Logger) -> None:
    nt_files = sorted(path for path in source_dir.glob("*.nt") if path.is_file())
    if not nt_files:
        raise FileNotFoundError(f"No .nt files produced in {source_dir}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        final_path.unlink()
    with final_path.open("wb") as out:
        for path in nt_files:
            logger.info(f"[MATERIALIZE] appending {path.name} -> {final_path.name}")
            with path.open("rb") as fh:
                shutil.copyfileobj(fh, out, length=1024 * 1024)
    logger.info(f"[MATERIALIZE] final output: {final_path} ({count_lines(final_path)} lines)")


def clean_target_tmp_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def materialize_target(args, config: configparser.ConfigParser, target: str, logger: logging.Logger) -> None:
    ready_dir, output_dir = get_profile_dirs(config, args.profile)
    require_ready_files(ready_dir, target=target)

    runtime_dir = resolve_in_project(config, config["DIRECTORIES"].get("runtime_config_dir", "output/runtime_configs"))
    tmp_dir = output_dir / f"_tmp_{target}"
    clean_target_tmp_dir(tmp_dir)

    cfg_path = write_morph_config(config, args.profile, target, ready_dir, tmp_dir, runtime_dir)
    python_bin = config["PYTHON"].get("python_bin", sys.executable)
    log_path = output_dir / f"morph_{target}.log"

    run_command([python_bin, "-m", "morph_kgc", str(cfg_path)], log_path, project_dir(config), logger)

    final_name = {
        "actors":        "knowledge-graph_actors.nt",
        "bibliographic": "knowledge-graph_bibliographic.nt",
        "roles":         "knowledge-graph_roles.nt",
    }.get(target, f"knowledge-graph_{target}.nt")
    concatenate_nt_files(tmp_dir, output_dir / final_name, logger)


def merge_outputs(output_dir: Path, logger: logging.Logger) -> Path:
    # Collect all knowledge-graph_*.nt files except the merged output itself,
    # in a deterministic order: actors, bibliographic, roles, then any others.
    priority = ["knowledge-graph_actors.nt", "knowledge-graph_bibliographic.nt",
                "knowledge-graph_roles.nt"]
    found = {p.name: p for p in output_dir.glob("knowledge-graph_*.nt")
             if p.name != "knowledge-graph_merged.nt" and p.is_file()}
    ordered = [found[n] for n in priority if n in found]
    ordered += sorted(p for name, p in found.items() if name not in priority)

    if not ordered:
        raise FileNotFoundError(f"No knowledge-graph_*.nt source files found in {output_dir}")

    # Ensure the two mandatory files are present
    for required in ["knowledge-graph_actors.nt", "knowledge-graph_bibliographic.nt"]:
        if required not in found:
            raise FileNotFoundError(output_dir / required)

    merged = output_dir / "knowledge-graph_merged.nt"
    if merged.exists():
        merged.unlink()
    with merged.open("wb") as out:
        for path in ordered:
            logger.info(f"[MERGE] appending {path.name}")
            with path.open("rb") as fh:
                shutil.copyfileobj(fh, out, length=1024 * 1024)
    logger.info(f"[MERGE] output: {merged} ({count_lines(merged)} lines)")
    return merged


def output_for_target(output_dir: Path, target: str) -> Path:
    names = {
        "actors":        "knowledge-graph_actors.nt",
        "bibliographic": "knowledge-graph_bibliographic.nt",
        "roles":         "knowledge-graph_roles.nt",
        "merged":        "knowledge-graph_merged.nt",
    }
    if target not in names:
        raise ValueError(f"target must be one of {sorted(names)}")
    return output_dir / names[target]


def validate_nt(path: Path, sample_lines: int, logger: logging.Logger) -> None:
    import rdflib

    if not path.exists():
        raise FileNotFoundError(path)

    total = count_lines(path)
    logger.info(f"[VALIDATE] file: {path}")
    logger.info(f"[VALIDATE] line count: {total}")

    bad: list[tuple[int, str, str]] = []
    checked = 0

    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                g = rdflib.Graph()
                g.parse(data=line, format="nt")
            except Exception as exc:
                bad.append((line_no, str(exc), line[:1000]))
                if len(bad) >= 50:
                    break
            checked += 1
            if sample_lines and checked >= sample_lines:
                break

    if bad:
        bad_path = path.with_suffix(".bad-lines.txt")
        with bad_path.open("w", encoding="utf-8") as out:
            for line_no, err, line in bad:
                out.write(f"LINE {line_no}: {err}\n{line}\n\n")
        logger.error(f"[VALIDATE] invalid N-Triples lines found: {len(bad)}")
        logger.error(f"[VALIDATE] details: {bad_path}")
        raise RuntimeError(f"Validation failed for {path}")

    logger.info(f"[VALIDATE] sampled valid non-empty lines: {checked}")


def cmd_preprocess(args, config: configparser.ConfigParser, logger: logging.Logger) -> None:
    ready_dir, _ = get_profile_dirs(config, args.profile)
    if args.force and ready_dir.exists():
        logger.info(f"[PREPROCESS] removing existing ready directory: {ready_dir}")
        shutil.rmtree(ready_dir)
    ready_dir.mkdir(parents=True, exist_ok=True)

    sample = args.sample if args.profile == "sample" else 0
    enriched = _find_enriched_inputs(config, project_dir(config))

    # ── Actors ────────────────────────────────────────────────────────────────
    actors_src = enriched.get("actors_enriched") or enriched.get("actors_optimised")
    if actors_src:
        source_label = "module 06 enriched" if enriched.get("actors_enriched") else "module 05 optimised"
        logger.info(f"[PREPROCESS] actors source: {source_label} ({actors_src.name})")
        preprocess_enriched_actors(
            actors_src,
            enriched.get("actors_minimal"),
            ready_dir,
            sample,
            logger,
        )
    else:
        actors_zip = resolve_in_project(config, config["RAW_INPUTS"]["actors_zip"])
        logger.info(f"[PREPROCESS] actors source: legacy ZIP ({actors_zip.name})")
        preprocess_actors(actors_zip, ready_dir, sample, logger)

    # ── Editions ──────────────────────────────────────────────────────────────
    editions_src = enriched.get("editions_enriched")
    if editions_src:
        logger.info(f"[PREPROCESS] editions source: module 06 enriched ({editions_src.name})")
        preprocess_enriched_bibliographic(editions_src, ready_dir, sample, logger)
    else:
        editions_zip = resolve_in_project(config, config["RAW_INPUTS"]["editions_zip"])
        logger.info(f"[PREPROCESS] editions source: legacy ZIP ({editions_zip.name})")
        preprocess_bibliographic(editions_zip, ready_dir, sample, logger)

    logger.info("[PREPROCESS] done")


def cmd_materialize(args, config: configparser.ConfigParser, logger: logging.Logger) -> None:
    target_arg = getattr(args, "target", "all")
    if target_arg == "all":
        ready_dir, _ = get_profile_dirs(config, args.profile)
        targets = ["actors", "bibliographic"]
        if (ready_dir / READY_FILES["roles"]).exists():
            targets.append("roles")
    else:
        targets = [target_arg]
    for target in targets:
        materialize_target(args, config, target, logger)
    logger.info("[MATERIALIZE] done")


def cmd_merge(args, config: configparser.ConfigParser, logger: logging.Logger) -> None:
    _, output_dir = get_profile_dirs(config, args.profile)
    merge_outputs(output_dir, logger)


def cmd_validate(args, config: configparser.ConfigParser, logger: logging.Logger) -> None:
    _, output_dir = get_profile_dirs(config, args.profile)
    path = output_for_target(output_dir, args.target)
    validate_nt(path, args.sample_lines, logger)


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-contained BnF graph materialisation pipeline")
    parser.add_argument("--config", default="pipeline_config.ini", help="Config file inside 07_graph_materialisation")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preprocess")
    p.add_argument("--profile", choices=["sample", "full"], default="full")
    p.add_argument("--sample", type=int, default=20, help="Rows per raw dataset for sample profile only")
    p.add_argument("--force", action="store_true", help="Delete the selected ready directory before preprocessing")

    p = sub.add_parser("materialize")
    p.add_argument("--profile", choices=["sample", "full"], default="full")
    p.add_argument("--target", choices=["actors", "bibliographic", "roles", "all"], default="all")

    p = sub.add_parser("merge")
    p.add_argument("--profile", choices=["sample", "full"], default="full")

    p = sub.add_parser("validate")
    p.add_argument("--profile", choices=["sample", "full"], default="full")
    p.add_argument("--target", choices=["actors", "bibliographic", "roles", "merged"], default="merged")
    p.add_argument("--sample-lines", type=int, default=10000, help="Number of non-empty lines to validate; 0 means full file")

    p = sub.add_parser("all")
    p.add_argument("--profile", choices=["sample", "full"], default="sample")
    p.add_argument("--sample", type=int, default=20)
    p.add_argument("--force", action="store_true")
    p.add_argument("--sample-lines", type=int, default=10000)

    args = parser.parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config = read_config(config_path)
    logger = setup_logger(config)
    logger.info(f"[START] command={args.command} profile={getattr(args, 'profile', 'n/a')} time={datetime.now().isoformat(timespec='seconds')}")
    logger.info(f"[PROJECT] {project_dir(config)}")

    if args.command == "preprocess":
        cmd_preprocess(args, config, logger)
    elif args.command == "materialize":
        cmd_materialize(args, config, logger)
    elif args.command == "merge":
        cmd_merge(args, config, logger)
    elif args.command == "validate":
        cmd_validate(args, config, logger)
    elif args.command == "all":
        cmd_preprocess(args, config, logger)
        cmd_materialize(args, config, logger)
        cmd_merge(args, config, logger)
        # Validate merged output for all.
        class ValidateArgs:
            profile = args.profile
            target = "merged"
            sample_lines = args.sample_lines
        cmd_validate(ValidateArgs, config, logger)
    else:  # pragma: no cover
        raise AssertionError(args.command)

    logger.info("[DONE]")


if __name__ == "__main__":
    main()
