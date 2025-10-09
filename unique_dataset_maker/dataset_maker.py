import os
import json
import csv
import pandas as pd
from collections import defaultdict
from tqdm import tqdm  # Progress bar

# Base folder containing year directories
base_path = "data/results_bnf"

# Data structures
edition_data = defaultdict(lambda: defaultdict(set))
edition_sources = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))

# Get all year directories
year_dirs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]

# Traverse folders with progress bar
for year_dir in tqdm(year_dirs, desc="Processing year directories"):
    year_path = os.path.join(base_path, year_dir)

    for root, _, files in os.walk(year_path):
        for filename in files:
            if not filename.endswith(".csv"):
                continue

            csv_path = os.path.join(root, filename)
            try:
                df = pd.read_csv(csv_path, dtype=str, on_bad_lines='skip').fillna("")

                # Ensure all rows have same number of columns as the header
                expected_cols = len(df.columns)
                df = df[df.apply(lambda row: len(row) == expected_cols, axis=1)]

                if "edition" not in df.columns:
                    continue

                for _, row in df.iterrows():
                    eid = row["edition"]
                    edition_data[eid]["edition"].add(eid)
                    edition_sources[eid]["edition"][eid].add(csv_path)

                    # record year_dir
                    edition_data[eid]["year_dir"].add(year_dir)
                    edition_sources[eid]["year_dir"][year_dir].add(csv_path)

                    # record all other fields
                    for col in df.columns:
                        if col == "edition":
                            continue
                        val = row[col]
                        if val:
                            edition_data[eid][col].add(val)
                            edition_sources[eid][col][val].add(csv_path)

            except Exception as e:
                print(f"⚠️ Error reading {csv_path}: {e}")

# Build flattened dataset and source log
rows = []
log = {}

for eid, fields in edition_data.items():
    row = {}
    log[eid] = {}

    for field, values in fields.items():
        # Remove empty strings, sort and deduplicate
        cleaned_vals = sorted(set(v for v in values if v))
        concatenated = ";".join(cleaned_vals)
        row[field] = concatenated

        # Log source files for each value
        log[eid][field] = {
            v: sorted(list(edition_sources[eid][field][v]))
            for v in cleaned_vals
        }

    rows.append(row)

# Final column order
all_fields = set()
for r in rows:
    all_fields.update(r.keys())
ordered = ["edition"] + sorted(f for f in all_fields if f != "edition")

# Create DataFrame
df_result = pd.DataFrame(rows)[ordered]

# Output paths
os.makedirs("data/unified_dataset", exist_ok=True)
csv_path = "data/unified_dataset/merged_editions_dataset_with_log.csv"
json_log_path = "data/unified_dataset/merged_editions_sources_log.json"

# Save to CSV using proper quoting
df_result.to_csv(
    csv_path,
    index=False,
    encoding="utf-8",
    quoting=csv.QUOTE_ALL,
    quotechar='"'
)

# Save JSON log
with open(json_log_path, "w", encoding="utf-8") as jf:
    json.dump(log, jf, indent=2, ensure_ascii=False)

print(f"✅ CSV saved to '{csv_path}'")
print(f"✅ JSON log saved to '{json_log_path}'")
