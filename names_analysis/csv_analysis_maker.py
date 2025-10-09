import json
import csv
import os

# Input JSON (può essere classificazione con o senza tuple)
input_json = "names_analysis/names_results/names_classification_report_flair.json"
output_csv = "names_analysis/names_results/names_review_table.csv"

# Load the data
with open(input_json, "r", encoding="utf-8") as f:
    data = json.load(f)

# Prepara le righe per la tabella
rows = []

# Controlla se è output da Flair o normale
for classification_type in data:
    classified_as = "responsible agent name" if classification_type == "classified_as_name" else "not responsible agent name"
    for sub_type in data[classification_type]:  # name, first_name, last_name
        for entry in data[classification_type][sub_type]:
            if isinstance(entry, list) or isinstance(entry, tuple):  # formato: ("original", "non-name part")
                string_value = entry[0]
                non_name_part = entry[1]
            else:
                string_value = entry
                non_name_part = ""
            rows.append({
                "string": string_value,
                "type": sub_type,
                "classified_as": classified_as,
                "not_name_part": non_name_part,
                "human_check": ""
            })

# Scrivi il CSV
os.makedirs(os.path.dirname(output_csv), exist_ok=True)
with open(output_csv, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["string", "type", "classified_as", "not_name_part", "human_check"])
    writer.writeheader()
    writer.writerows(rows)

print(f"✅ Review table created: '{output_csv}' with {len(rows)} entries.")
