#!/usr/bin/env python3
"""
BnF Actor Dataset Optimizer

Reads actor data from a ZIP archive and generates:
1. An optimized CSV with one row per actor (all fields as multi-value)
2. A statistical report on the dataset with merge information
3. A JSON file tracking all merged values per actor

Optionally, it also merges in role/publication information coming from
a CSV file (e.g. subset_optimisation/id_roles/actor_roles_links.csv)
with columns: actor, contributed_to, roles.
"""

import os
import csv
import zipfile
import json
import argparse
import sys
from typing import Dict, Any, List, Tuple, Set

# Increase CSV field size limit to handle very long cells (e.g. contributed_to lists)
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    # fallback in case sys.maxsize is too large for the platform
    csv.field_size_limit(10**9)

# --- CONFIGURATION ---
INPUT_ZIP_DEFAULT = "data/bnf_agents_data_querying/actor_queries_results.zip"
OUTPUT_DIR_DEFAULT = "subset_optimisation/output"
REPORT_DIR_DEFAULT = "subset_optimisation/report"
OUTPUT_FILENAME = "bnf_actors_optimised.csv"
REPORT_FILENAME = "summary_report.txt"
MERGE_TRACKING_FILENAME = "merged_entities.json"

# Default path for id–roles–publications mapping
ROLES_MAPPING_DEFAULT = "subset_optimisation/id_roles/actor_roles_links.csv"

# All data fields (excluding actor which is the ID)
ALL_DATA_FIELDS = [
    'actor_name',
    'actor_first_name',
    'actor_last_name',
    'actor_birth',
    'actor_death',
    'actor_start',
    'actor_end',
    'first_year',
    'entity_type',
    'actor_gender',
    'actor_profession',
    'actor_country',
    'actor_language',
    'actor_link_exact',
    'actor_link_close'
]


def normalise_value(v: Any) -> str:
    """Clean values: remove spaces, handle NA/None."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.upper() in {"NA", "N/A", "NULL", "NONE", ""}:
        return ""
    return s


def process_actor_data(zip_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], int, int]:
    """Read ZIP and aggregate data by actor.

    All fields are treated as potentially multi-value after merge.
    """

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"ZIP file not found: {zip_path}")

    # Structure: actor_id -> field_name -> set of values
    actors_db: Dict[str, Dict[str, Set[str]]] = {}

    # Track merge information
    merge_tracking: Dict[str, Dict[str, Any]] = {}

    # Track row signatures for duplicate detection
    row_signatures: Dict[str, List[str]] = {}

    print(f"Reading ZIP file: {zip_path} ...")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            file_list = [f for f in zf.namelist() if f.lower().endswith(".csv")]
            total_files = len(file_list)
            print(f"Found {total_files} CSV files to process.")

            row_count = 0
            duplicate_count = 0

            for idx, filename in enumerate(file_list):
                try:
                    with zf.open(filename, "r") as f_csv:
                        lines = (line.decode("utf-8", errors="replace") for line in f_csv)
                        reader = csv.DictReader(lines)

                        for row in reader:
                            row_count += 1

                            if row_count % 10000 == 0:
                                print(f"  Processed {row_count:,} rows, {len(actors_db):,} unique actors...")

                            raw_id = row.get("actor", "")
                            if not raw_id or normalise_value(raw_id) == "":
                                continue

                            bnf_id = normalise_value(raw_id)

                            # Create row signature for duplicate detection
                            signature_parts = []
                            for field in ALL_DATA_FIELDS:
                                val = normalise_value(row.get(field))
                                signature_parts.append(val)
                            row_signature = "|".join(signature_parts)

                            # Check for exact duplicate
                            if bnf_id in row_signatures:
                                if row_signature in row_signatures[bnf_id]:
                                    duplicate_count += 1
                                    continue
                                else:
                                    row_signatures[bnf_id].append(row_signature)
                            else:
                                row_signatures[bnf_id] = [row_signature]

                            # Initialize record if new
                            if bnf_id not in actors_db:
                                actors_db[bnf_id] = {"bnf_id": bnf_id}
                                # Initialize all fields as sets
                                for field in ALL_DATA_FIELDS:
                                    actors_db[bnf_id][field] = set()

                                # Initialize merge tracking
                                merge_tracking[bnf_id] = {
                                    "merge_count": 0,
                                    "fields_with_variations": {}
                                }

                            entry = actors_db[bnf_id]
                            tracking = merge_tracking[bnf_id]

                            # Track if this row adds any new values (creates variation)
                            row_creates_variation = False

                            # Add all field values to sets
                            for field in ALL_DATA_FIELDS:
                                val = normalise_value(row.get(field))
                                if val:
                                    # Check if this value creates a variation
                                    if val not in entry[field]:
                                        # This is a new value for this field
                                        if len(entry[field]) > 0:
                                            # Field already had a value, so this is a variation
                                            row_creates_variation = True
                                            if field not in tracking["fields_with_variations"]:
                                                tracking["fields_with_variations"][field] = []
                                            tracking["fields_with_variations"][field].append(val)

                                    entry[field].add(val)

                            # Only increment merge_count if this row actually created variations
                            if row_creates_variation:
                                tracking["merge_count"] += 1

                except Exception as e:
                    print(f"  Warning: Error reading {filename}: {e}")
                    continue

            print(f"Total rows processed: {row_count:,}")
            print(f"Exact duplicates found: {duplicate_count:,}")
            print(f"Unique actors found: {len(actors_db):,}")

    except zipfile.BadZipFile:
        raise ValueError(f"Invalid ZIP file: {zip_path}")

    print("Aggregation complete. Formatting output...")

    # Flatten results for CSV
    flat_records: List[Dict[str, Any]] = []
    for bnf_id, entry in actors_db.items():
        rec: Dict[str, Any] = {"BnF_ID": entry["bnf_id"]}
        # Join all sets with "; " separator
        for field in ALL_DATA_FIELDS:
            rec[field] = "; ".join(sorted(entry[field]))
        flat_records.append(rec)

    flat_records.sort(key=lambda x: x["BnF_ID"])

    return flat_records, merge_tracking, row_count, duplicate_count


def save_merge_tracking(merge_tracking: Dict[str, Dict[str, Any]], report_dir: str) -> str:
    """Save merge tracking information to JSON file (only entities with actual merges)."""
    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, MERGE_TRACKING_FILENAME)

    # Filter: only entities with variations in at least one field
    filtered_tracking = {}
    for bnf_id, tracking in merge_tracking.items():
        if tracking["fields_with_variations"]:
            filtered_tracking[bnf_id] = tracking

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(filtered_tracking, f, ensure_ascii=False, indent=2)

    print(f"Merge tracking saved: {json_path}")
    print(f"  Entities with merges in JSON: {len(filtered_tracking):,}")
    return json_path


def count_merged_entities(merge_tracking: Dict[str, Dict[str, Any]]) -> int:
    """Count entities with multiple records merged."""
    return sum(1 for t in merge_tracking.values() if t["fields_with_variations"])


def generate_stats_report(
        records: List[Dict[str, Any]],
        report_dir: str,
        merge_tracking: Dict[str, Dict[str, Any]],
        total_source_rows: int,
        duplicate_rows: int
):
    """Generate statistical report."""
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, REPORT_FILENAME)

    total_actors = len(records)
    if total_actors == 0:
        print("No actors found. Report not generated.")
        return

    merged_entities = count_merged_entities(merge_tracking)
    net_rows = total_source_rows - duplicate_rows

    # Calculate statistics for ALL fields (all treated as multi-value)
    field_stats: Dict[str, Dict[str, Any]] = {}
    for field in ALL_DATA_FIELDS:
        total_items = 0
        filled_count = 0

        for rec in records:
            val = rec.get(field, "")
            if val:
                filled_count += 1
                items = [x.strip() for x in val.split(";") if x.strip()]
                total_items += len(items)

        avg = total_items / total_actors if total_actors > 0 else 0
        fill_rate = (filled_count / total_actors * 100) if total_actors > 0 else 0

        field_stats[field] = {
            "filled": filled_count,
            "fill_rate": fill_rate,
            "total_items": total_items,
            "average": avg
        }

    # Count fields with variations per entity
    field_variation_counts = {field: 0 for field in ALL_DATA_FIELDS}
    for tracking in merge_tracking.values():
        for field in tracking["fields_with_variations"]:
            field_variation_counts[field] += 1

    # Write report
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("BnF DATASET OPTIMISATION REPORT\n")
        f.write("=" * 70 + "\n\n")

        # Basic statistics
        f.write("BASIC STATISTICS\n")
        f.write("-" * 70 + "\n")
        f.write(f"Total source rows processed: {total_source_rows:,}\n")
        f.write(f"Exact duplicate rows: {duplicate_rows:,}\n")
        f.write(f"Net rows (excluding duplicates): {net_rows:,}\n")
        f.write(f"Total unique entities (actors): {total_actors:,}\n")
        f.write(f"Entities with merged records: {merged_entities:,}\n")
        merge_rate = (merged_entities / total_actors * 100) if total_actors > 0 else 0
        f.write(f"Merge rate: {merge_rate:.2f}%\n")
        f.write(f"Average records per entity: {net_rows / total_actors:.2f}\n\n")

        # All fields statistics
        f.write("=" * 70 + "\n")
        f.write("FIELD STATISTICS (ALL FIELDS)\n")
        f.write("-" * 70 + "\n")
        f.write("(All fields can have multiple values after merge)\n\n")
        f.write(f"{'Field':<25} {'Filled':<15} {'Fill Rate':<15} {'Avg/Entity'}\n")
        f.write("-" * 70 + "\n")

        for field in ALL_DATA_FIELDS:
            stats = field_stats[field]
            f.write(f"{field:<25} {stats['filled']:>8,} {stats['fill_rate']:>12.1f}% {stats['average']:>12.4f}\n")

        # Overall average
        f.write("\n" + "=" * 70 + "\n")
        f.write("OVERALL AVERAGE\n")
        f.write("-" * 70 + "\n")
        # Calculate average of averages across all fields
        overall_avg = sum(s["average"] for s in field_stats.values()) / len(field_stats)
        f.write(f"Average items per entity (across all fields): {overall_avg:.4f}\n\n")

        # Individual averages per field
        f.write("AVERAGE ITEMS PER ENTITY (BY FIELD)\n")
        f.write("-" * 70 + "\n")
        for field in ALL_DATA_FIELDS:
            avg = field_stats[field]["average"]
            f.write(f"{field:<25} {avg:>8.4f}\n")

        # Merge details
        f.write("\n" + "=" * 70 + "\n")
        f.write("MERGE DETAILS - FIELDS WITH VARIATIONS\n")
        f.write("-" * 70 + "\n")
        f.write(f"{'Field':<25} {'Entities with variations'}\n")
        f.write("-" * 70 + "\n")

        for field in ALL_DATA_FIELDS:
            count = field_variation_counts[field]
            if count > 0:
                f.write(f"{field:<25} {count:>8,}\n")

        f.write("\n" + "=" * 70 + "\n")

    print(f"Report generated: {report_path}")


def load_roles_mapping(mapping_path: str) -> Dict[str, Dict[str, str]]:
    """
    Carica il file CSV con le colonne:
      - actor
      - contributed_to
      - roles

    Il metodo esegue due passaggi:
    1) scansione raw per rilevare righe con lunghezza superiore a 131072 caratteri
    2) parsing strutturato tramite csv.DictReader

    Le righe sospette rilevate nella prima passata vengono stampate a terminale.
    """

    mapping: Dict[str, Dict[str, str]] = {}

    if not mapping_path:
        print("No roles mapping path provided; skipping enrichment.")
        return mapping

    if not os.path.exists(mapping_path):
        print(f"Roles mapping file not found: {mapping_path}. Enrichment skipped.")
        return mapping

    print(f"Loading roles mapping from: {mapping_path}")

    # Passata 1: scansione raw per individuare righe oltre il limite di default
    print("\n--- Raw scan for long lines (>131072 chars) ---")
    suspicious_count = 0
    with open(mapping_path, "r", encoding="utf-8", errors="replace") as f_raw:
        for i, raw_line in enumerate(f_raw, start=1):
            if len(raw_line) > 131072:
                suspicious_count += 1
                print(f"\nSuspicious line detected at line {i}")
                print(f"Length: {len(raw_line)}")
                print("Preview:", raw_line[:300], "...", raw_line[-300:])

    if suspicious_count == 0:
        print("No suspicious lines detected.\n")
    else:
        print(f"Total suspicious lines detected: {suspicious_count}\n")

    # Passata 2: parsing tramite DictReader
    print("--- Parsing roles mapping (DictReader) ---")
    with open(mapping_path, "r", encoding="utf-8", newline="") as f:
        try:
            reader = csv.DictReader(f)
        except csv.Error as e:
            print("CSV parsing error during initialisation:", e)
            raise

        for row_i, row in enumerate(reader, start=2):
            try:
                actor_raw = row.get("actor", "")
                if not actor_raw:
                    continue

                actor_id = normalise_value(actor_raw)
                if not actor_id:
                    continue

                contributed_to = normalise_value(row.get("contributed_to", ""))
                roles = normalise_value(row.get("roles", ""))

                mapping[actor_id] = {
                    "contributed_to": contributed_to,
                    "roles": roles,
                }

            except csv.Error as err:
                print(f"CSV error at row {row_i}: {err}")
                raise

    print(f"Loaded roles mapping for {len(mapping):,} actors.\n")
    return mapping


def main():
    parser = argparse.ArgumentParser(
        description="BnF Actor Dataset Optimizer & Reporter",
        epilog="Example: python subset_optimisation/gen_author_links_optm.py"
    )
    parser.add_argument("--input-zip", default=INPUT_ZIP_DEFAULT,
                        help=f"ZIP di input con i dati degli attori (default: {INPUT_ZIP_DEFAULT})")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT,
                        help=f"Cartella di output per il CSV ottimizzato (default: {OUTPUT_DIR_DEFAULT})")
    parser.add_argument("--report-dir", default=REPORT_DIR_DEFAULT,
                        help=f"Cartella di output per il report (default: {REPORT_DIR_DEFAULT})")
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME,
                        help=f"Nome del CSV di output (default: {OUTPUT_FILENAME})")
    parser.add_argument(
        "--roles-mapping",
        default=ROLES_MAPPING_DEFAULT,
        help=(
            "Percorso al CSV con il mapping actor, contributed_to, roles "
            f"(default: {ROLES_MAPPING_DEFAULT})."
        ),
    )

    args = parser.parse_args()

    try:
        print("\n" + "=" * 70)
        print("BnF ACTOR DATASET OPTIMIZER")
        print("=" * 70 + "\n")

        data, merge_tracking, total_source_rows, duplicate_rows = process_actor_data(args.input_zip)

        if not data:
            print("Warning: No data generated!")
            return 1

        # Carica mapping actor -> contributed_to, roles
        roles_mapping = load_roles_mapping(args.roles_mapping)

        # Enrichment: aggiungo contributed_to e roles ai record in base a BnF_ID
        for rec in data:
            actor_id = rec.get("BnF_ID", "")
            if not actor_id:
                rec["contributed_to"] = ""
                rec["roles"] = ""
                continue

            if actor_id in roles_mapping:
                rec["contributed_to"] = roles_mapping[actor_id]["contributed_to"]
                rec["roles"] = roles_mapping[actor_id]["roles"]
            else:
                rec["contributed_to"] = ""
                rec["roles"] = ""

        # Write CSV
        os.makedirs(args.output_dir, exist_ok=True)
        out_path = os.path.join(args.output_dir, args.output_filename)

        # colonne: BnF_ID + campi originali + colonne nuove
        columns_order = ["BnF_ID"] + ALL_DATA_FIELDS + ["contributed_to", "roles"]

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns_order)
            writer.writeheader()
            writer.writerows(data)

        print(f"\nOptimized dataset saved to: {out_path}")
        print(f"  Total unique actors: {len(data):,}")

        # Write minimal CSV
        minimal_path = os.path.join(args.output_dir, "bnf_actors_optimised_minimal.csv")
        minimal_fields = [
            "BnF_ID",
            "actor_link_exact",
            "actor_link_close"
        ]

        print(f"Generating minimal dataset: {minimal_path}")

        with open(minimal_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=minimal_fields)
            writer.writeheader()

            for rec in data:
                writer.writerow({
                    "BnF_ID": rec.get("BnF_ID", ""),
                    "actor_link_exact": rec.get("actor_link_exact", ""),
                    "actor_link_close": rec.get("actor_link_close", ""),
                })

        print(f"Minimal dataset saved to: {minimal_path}")

        # Save merge tracking JSON
        save_merge_tracking(merge_tracking, args.report_dir)

        # Generate report
        generate_stats_report(data, args.report_dir, merge_tracking, total_source_rows, duplicate_rows)

        print("\n" + "=" * 70)
        print("COMPLETED SUCCESSFULLY!")
        print("=" * 70 + "\n")

        return 0

    except FileNotFoundError as e:
        print(f"\nError: File not found - {e}")
        return 1
    except ValueError as e:
        print(f"\nError: Invalid data - {e}")
        return 1
    except Exception as e:
        print(f"\nError: Unexpected error - {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())


'''
default: 

python subset_optimisation/gen_author_links_optm.py
'''

'''
custom:

python subset_optimisation/gen_author_links_optm.py \
  --roles-mapping path/to/alt_actor_roles_links.csv

'''