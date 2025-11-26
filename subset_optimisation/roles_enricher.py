import os
import csv
import zipfile
from collections import defaultdict
from typing import Dict, Set, List
import argparse


# Percorsi di default
ACTORS_ZIP_DEFAULT = "data/bnf_agents_data_querying/actor_queries_results.zip"
EDITIONS_ZIP_DEFAULT = "data/bnf_edition_data/bnf_edition_data_raw.zip"
OUTPUT_DIR_DEFAULT = "subset_optimisation/id_roles"
OUTPUT_FILENAME_DEFAULT = "actor_roles_links.csv"

# Campi di ruolo nelle edizioni
ROLE_FIELDS = ["author", "editor", "translator", "publisher_2", "illustrator"]


def normalise_value(v: str) -> str:
    """
    Normalizza i valori:
    - None -> ""
    - rimuove spazi
    - 'NA', 'N/A', 'null' (case-insensitive) -> ""
    """
    if v is None:
        return ""
    v = str(v).strip()
    if v.upper() in {"NA", "N/A", "NULL", ""}:
        return ""
    return v


def iter_rows_from_zip(zip_path: str):
    """
    Itera su tutte le righe di tutti i CSV contenuti nello ZIP.
    Restituisce (filename_in_zip, dict_row).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name, "r") as f:
                lines = (line.decode("utf-8", errors="replace") for line in f)
                reader = csv.DictReader(lines)
                for row in reader:
                    yield name, row


def collect_actor_ids(actors_zip_path: str) -> Set[str]:
    """
    Estrae l'insieme degli ID attore (campo 'actor') dal pacchetto ZIP degli agenti.
    """
    actor_ids: Set[str] = set()
    for _, row in iter_rows_from_zip(actors_zip_path):
        actor_id = normalise_value(row.get("actor"))
        if actor_id:
            actor_ids.add(actor_id)
    return actor_ids


def build_actor_roles_links(
    actors_zip_path: str,
    editions_zip_path: str,
) -> List[Dict[str, str]]:
    """
    Costruisce la struttura:
    - actor -> insieme di edizioni in cui compare
    - actor -> insieme di ruoli (campi) in cui compare
    e restituisce una lista di dict pronti per l'output CSV.
    """
    # 1) Raccolgo tutti gli ID degli attori
    actor_ids = collect_actor_ids(actors_zip_path)

    # 2) Strutture di aggregazione
    actor_to_editions: Dict[str, Set[str]] = defaultdict(set)
    actor_to_roles: Dict[str, Set[str]] = defaultdict(set)

    # 3) Itero sulle edizioni
    for _, row in iter_rows_from_zip(editions_zip_path):
        # prendo l'ID dell'edizione:
        # preferisco 'bnf_id', se non c'è uso 'edition'
        edition_id = normalise_value(row.get("bnf_id"))
        if not edition_id:
            edition_id = normalise_value(row.get("edition"))
        if not edition_id:
            # se non c'è proprio un identificatore, salto
            continue

        # per ogni colonna di ruolo, controllo se è presente e se contiene un attore noto
        for role_field in ROLE_FIELDS:
            if role_field not in row:
                continue
            raw_val = normalise_value(row.get(role_field))
            if not raw_val:
                continue

            # qui assumiamo che il campo contenga un singolo ID BnF (URI), come da esempio
            # se in futuro fosse multi-valore, si può estendere con uno split
            actor_id = raw_val

            if actor_id in actor_ids:
                actor_to_editions[actor_id].add(edition_id)
                actor_to_roles[actor_id].add(role_field)

    # 4) Costruisco i record per il CSV di output
    records: List[Dict[str, str]] = []

    # Considero solo gli attori che compaiono almeno in una edizione
    for actor_id in sorted(actor_to_editions.keys()):
        editions = sorted(actor_to_editions[actor_id])
        roles = sorted(actor_to_roles[actor_id])

        record = {
            "actor": actor_id,
            "contributed_to": ";".join(editions),
            "roles": ";".join(roles),
        }
        records.append(record)

    return records


def write_output_csv(
    records: List[Dict[str, str]],
    output_dir: str,
    output_filename: str,
) -> str:
    """
    Scrive il CSV di output con colonne: actor, contributed_to, roles.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, output_filename)

    fieldnames = ["actor", "contributed_to", "roles"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate actor -> editions/roles links from BnF actor and edition datasets."
    )
    parser.add_argument(
        "--actors-zip",
        default=ACTORS_ZIP_DEFAULT,
        help=f"Percorso allo ZIP degli attori (default: {ACTORS_ZIP_DEFAULT})",
    )
    parser.add_argument(
        "--editions-zip",
        default=EDITIONS_ZIP_DEFAULT,
        help=f"Percorso allo ZIP delle edizioni (default: {EDITIONS_ZIP_DEFAULT})",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR_DEFAULT,
        help=f"Cartella di output (default: {OUTPUT_DIR_DEFAULT})",
    )
    parser.add_argument(
        "--output-filename",
        default=OUTPUT_FILENAME_DEFAULT,
        help=f"Nome del CSV di output (default: {OUTPUT_FILENAME_DEFAULT})",
    )

    args = parser.parse_args()

    records = build_actor_roles_links(
        actors_zip_path=args.actors_zip,
        editions_zip_path=args.editions_zip,
    )
    out_path = write_output_csv(records, args.output_dir, args.output_filename)
    print(f"Output written to: {out_path}")


if __name__ == "__main__":
    main()


'''
uso base: 
python subset_optimisation/roles_enricher.py
'''

'''
custom:
python subset_optimisation/roles_enricher.py \
  --actors-zip data/bnf_agents_data_querying/actor_queries_results.zip \
  --editions-zip data/bnf_edition_data/bnf_edition_data_raw.zip \
  --output-dir subset_optimisation/id_roles \
  --output-filename actor_roles_links.csv
'''
