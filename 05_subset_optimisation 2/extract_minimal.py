#!/usr/bin/env python3
"""
extract_minimal.py

Reads bnf_actors_optimised.csv and writes a filtered bnf_actors_optimised_minimal.csv
with columns: BnF_ID, actor_name, actor_link_exact, actor_link_close.
It drops rows where both actor_link_exact and actor_link_close are empty.
"""

import os
import csv
import sys
import argparse

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


def extract_minimal(input_csv: str, output_csv: str):
    if not os.path.exists(input_csv):
        print(f"Error: Input file {input_csv} does not exist.")
        sys.exit(1)

    print(f"Reading full optimised dataset: {input_csv}")
    
    # Target fields for minimal output
    minimal_fields = ["BnF_ID", "actor_name", "actor_link_exact", "actor_link_close"]
    
    records_written = 0
    records_dropped = 0
    total_processed = 0

    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)

    with open(input_csv, "r", encoding="utf-8", newline="") as infile, \
         open(output_csv, "w", encoding="utf-8", newline="") as outfile:
        
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=minimal_fields, extrasaction="ignore")
        writer.writeheader()

        for row in reader:
            total_processed += 1
            
            # Extract and clean values
            bnf_id = row.get("BnF_ID", "").strip()
            actor_name = row.get("actor_name", "").strip()
            link_exact = row.get("actor_link_exact", "").strip()
            link_close = row.get("actor_link_close", "").strip()

            # Check if both links are empty
            # Values like 'NA', 'N/A', 'NULL', 'NONE' are also treated as empty
            def is_empty(val: str) -> bool:
                return not val or val.upper() in {"NA", "N/A", "NULL", "NONE", ""}

            if is_empty(link_exact) and is_empty(link_close):
                records_dropped += 1
                continue

            writer.writerow({
                "BnF_ID": bnf_id,
                "actor_name": actor_name,
                "actor_link_exact": link_exact,
                "actor_link_close": link_close
            })
            records_written += 1

    print(f"Extraction complete:")
    print(f"  Total processed rows: {total_processed:,}")
    print(f"  Rows written        : {records_written:,}")
    print(f"  Rows dropped (empty): {records_dropped:,}")
    print(f"  ✓ Minimal dataset   → {output_csv}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract a minimal linking subset from the optimised actors dataset, dropping rows without links."
    )
    parser.add_argument(
        "--input", "-i",
        default="output/bnf_actors_optimised.csv",
        help="Path to the full optimised actors CSV (default: output/bnf_actors_optimised.csv)"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/bnf_actors_optimised_minimal.csv",
        help="Path to the minimal output CSV (default: output/bnf_actors_optimised_minimal.csv)"
    )
    
    args = parser.parse_args()
    extract_minimal(args.input, args.output)


if __name__ == "__main__":
    main()
