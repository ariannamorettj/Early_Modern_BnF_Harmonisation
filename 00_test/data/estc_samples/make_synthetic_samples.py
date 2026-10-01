#!/usr/bin/env python3
"""Write SYNTHETIC ESTC fixtures with the column structure of the COMHIS tables.

The COMHIS ESTC tables (data/estc/estc_core.csv, estc_actor_links.csv,
estc_actors.csv) are licensed data and are not distributed with this
repository. The three files next to this script have the same columns, in
the same order, as those tables, but every value is invented: names, ESTC
ids (prefix "Z", which the ESTC does not use), VIAF ids (prefix "99999"),
titles and dates. They describe no real record.

Run from the repository root to regenerate them (deterministic):
    python 00_test/data/estc_samples/make_synthetic_samples.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent
N_ACTORS = 30
N_RECORDS = 30

ACTOR_COLUMNS = [
    "actor_id", "actor_id_type", "old_actor_ids", "bbti_link", "viaf_link", "is_organization",
    "name_unified", "name_unified_source", "nametype", "name_first", "name_last", "name_remainder",
    "name_variants", "names_for_gender", "actor_titles", "actor_gender", "actor_gender_source",
    "year_birth_viaf", "year_death_viaf", "year_bio_start_bbti", "year_bio_end_bbti",
    "year_birth_estc", "year_death_estc", "year_birth", "year_death", "year_birth_source",
    "year_death_source", "year_active_first_estc", "year_active_last_estc",
    "year_active_first_bbti", "year_active_last_bbti", "year_pub_first_estc", "year_pub_last_estc",
]
LINK_COLUMNS = [
    "estc_id", "actor_id", "actor_id_methods", "source_tags", "actor_name_primary",
    "actor_names_other", "actor_is_anonymous", "actor_roles_all", "actor_addresses",
    "actor_ids_old", "actor_role_author", "actor_role_printer", "actor_role_publisher",
    "actor_role_bookseller", "actor_role_unknown", "actor_role_corporate_author",
    "actor_role_geographic_record", "actor_role_corporate_unknown", "actor_role_translator",
    "actor_role_attributed_name", "actor_role_editor", "actor_role_engraver", "actor_role_other",
    "publisher_statement", "brackets_in_booktrade_name", "actor_has_assigns", "actor_assigns_text",
]
CORE_COLUMNS = [
    "estc_id", "primary_language", "gatherings.original", "width.original", "height.original",
    "obl.original", "gatherings", "width", "height", "obl", "area", "record_creation_date",
    "original", "publication_year_from", "publication_year_till", "publication_year",
    "publication_decade", "publication_century", "uncertain", "circa", "range", "org_500_a",
    "total_price", "tried_to_parse", "freq", "annual", "is_periodical", "short_title", "work_id",
    "publication_place", "publication_country", "false_imprint", "org_260_a",
    "org_260_a_square_brackets", "org_752_a", "org_752_b", "org_752_d", "longitude", "latitude",
    "geo_id", "pagecount.multiplier", "pagecount.squarebracket", "pagecount.plate",
    "pagecount.arabic", "pagecount.roman", "pagecount.sheet", "pagecount", "volnumber",
    "volcount", "parts", "pagecount_from", "pagecount.orig", "singlevol", "multivol", "issue",
    "document.items", "paper", "document_type",
]

FIRST = ["Agatha", "Barnaby", "Cornelius", "Dorothea", "Ezekiel", "Fenella", "Gideon",
         "Hester", "Ignatius", "Jemima", "Lucius", "Mehitabel", "Obadiah", "Prudence"]
LAST = ["Quillfeather", "Inkwell", "Foliobrook", "Vellumby", "Typesetter", "Margent",
        "Colophon", "Quarto", "Octavo", "Gatherwood", "Platen", "Chaseworth"]
WORDS = ["treatise", "sermon", "discourse", "essay", "letter", "account", "inquiry",
         "vindication", "observations", "remarks", "dialogue", "history"]
TOPICS = ["imaginary islands", "the art of nothing", "invented customs", "fictional tides",
          "unknown comets", "the moral uses of fog", "a city that never was"]
PLACES = [("Imaginaria", "Nowhere"), ("Fabletown", "Nowhere"), ("Placebury", "Nowhere")]
TRUE_FALSE = ("TRUE", "FALSE")


def na_row(columns: list[str]) -> dict:
    return {c: "NA" for c in columns}


def make_actors(rng: random.Random) -> list[dict]:
    actors = []
    for i in range(1, N_ACTORS + 1):
        viaf = f"99999{i:06d}"
        is_org = i % 10 == 0
        row = na_row(ACTOR_COLUMNS)
        if is_org:
            name = f"Society of {rng.choice(LAST)}s"
            row.update(nametype="org", actor_gender="corporate")
        else:
            first, last = rng.choice(FIRST), rng.choice(LAST)
            name = f"{last}, {first}"
            birth = rng.randint(1600, 1760)
            death = birth + rng.randint(30, 80)
            row.update(nametype="unknown", name_first=first, name_last=last,
                       actor_gender=rng.choice(["male", "female", "unknown"]),
                       year_birth_viaf=str(birth), year_death_viaf=str(death),
                       year_birth=str(birth), year_death=str(death),
                       year_birth_source="viaf", year_death_source="viaf")
        first_pub = rng.randint(1650, 1790)
        row.update(actor_id=f"viaf_{viaf}", actor_id_type="viaf",
                   viaf_link=f"https://viaf.org/viaf/{viaf}", is_organization=TRUE_FALSE[not is_org],
                   name_unified=name, name_unified_source="synthetic", name_variants=name,
                   actor_gender_source="synthetic", year_pub_first_estc=str(first_pub),
                   year_pub_last_estc=str(first_pub + rng.randint(0, 10)))
        actors.append(row)
    return actors


def make_core(rng: random.Random) -> list[dict]:
    records = []
    for i in range(1, N_RECORDS + 1):
        year = rng.randint(1650, 1799)
        place, country = rng.choice(PLACES)
        title = f"A {rng.choice(WORDS)} on {rng.choice(TOPICS)}"
        row = na_row(CORE_COLUMNS)
        row.update({
            "estc_id": f"Z{i:06d}", "primary_language": "English",
            "gatherings.original": "8vo", "obl.original": "FALSE", "gatherings": "8vo",
            "width": "11", "height": "18", "obl": "0", "area": "198",
            "record_creation_date": "2000-01-01", "original": str(year),
            "publication_year_from": str(year), "publication_year": str(year),
            "publication_decade": str(year - year % 10), "publication_century": str(year - year % 100),
            "uncertain": "FALSE", "circa": "FALSE", "range": "FALSE", "is_periodical": "FALSE",
            "short_title": title, "work_id": f"{i}-{title.lower()}",
            "publication_place": place, "publication_country": country, "false_imprint": "FALSE",
            "org_260_a": f"{place} :", "org_260_a_square_brackets": "FALSE",
            "org_752_a": country, "org_752_d": place,
            "pagecount": str(rng.randint(8, 400)), "volcount": "1", "pagecount_from": "original",
            "singlevol": "TRUE", "multivol": "FALSE", "issue": "FALSE",
            "document.items": "1", "paper": "1", "document_type": "Book",
        })
        records.append(row)
    return records


def make_links(rng: random.Random, actors: list[dict], records: list[dict]) -> list[dict]:
    links = []
    for record in records:
        for role in ("author", "publisher"):
            actor = rng.choice(actors)
            row = na_row(LINK_COLUMNS)
            row.update({c: "FALSE" for c in LINK_COLUMNS if c.startswith("actor_role_")})
            row.update({
                "estc_id": record["estc_id"], "actor_id": actor["actor_id"],
                "actor_id_methods": f"{role}:synthetic", "source_tags": "100" if role == "author" else "260",
                "actor_name_primary": actor["name_unified"], "actor_is_anonymous": "FALSE",
                "actor_roles_all": role, f"actor_role_{role}": "TRUE",
            })
            links.append(row)
    return links


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rng = random.Random(20261001)
    actors = make_actors(rng)
    records = make_core(rng)
    links = make_links(rng, actors, records)
    write(OUT / "estc_actors_sample.csv", ACTOR_COLUMNS, actors)
    write(OUT / "estc_core_sample.csv", CORE_COLUMNS, records)
    write(OUT / "estc_actor_links_sample.csv", LINK_COLUMNS, links)
    print(f"{len(actors)} actors, {len(records)} records, {len(links)} links (synthetic) -> {OUT}")


if __name__ == "__main__":
    main()
