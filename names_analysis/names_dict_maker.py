import os
import csv
import json

source_path = "data/results_bnf"
output_json = "names_analysis/names_results/names_dict.json"

# create report dict
name_data = {
    "name": set(),
    "first_name": set(),
    "last_name": set()
}

# categorize column name
def get_category(col_name):
    col = col_name.lower()
    if "first_name" in col:
        return "first_name"
    elif "last_name" in col:
        return "last_name"
    elif "name" in col and "first" not in col and "last" not in col:
        return "name"
    return None

# iterate file CSV
for root, dirs, files in os.walk(source_path):
    for file in files:
        if file.lower().endswith(".csv"):
            full_path = os.path.join(root, file)
            try:
                with open(full_path, newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        for col in row:
                            category = get_category(col)
                            if category:
                                value = row[col].strip()
                                if value:
                                    name_data[category].add(value)
            except Exception as e:
                print(f"Errore nel file {full_path}: {e}")

# Convert set in list to JSON serialisation
for key in name_data:
    name_data[key] = sorted(name_data[key])

# write file JSON
with open(output_json, "w", encoding="utf-8") as f:
    json.dump(name_data, f, ensure_ascii=False, indent=2)

print(f"\n✅ Json file in: '{output_json}' con {sum(len(v) for v in name_data.values())} valori totali.")
