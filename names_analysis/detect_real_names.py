import json
from nameparser import HumanName

# File input/output
input_json = "names_analysis/names_results/names_dict.json"
output_json = "names_analysis/names_results/names_classification_report.json"

# Load input data
with open(input_json, "r", encoding="utf-8") as f:
    name_data = json.load(f)

# Output structure
result = {
    "classified_as_name": {
        "name": [],
        "first_name": [],
        "last_name": []
    },
    "not_recognised_as_names": {
        "name": [],
        "first_name": [],
        "last_name": []
    }
}

# Generic non-name terms in English and French
non_name_terms = {
    "unknown", "none", "editor", "author", "translator", "scientific editor",
    "inconnu", "aucun", "éditeur", "auteur", "traducteur", "éditeur scientifique",
    "collectif", "direction", "société", "anonyme"
}

def is_probably_name(s):
    name = HumanName(s)
    cleaned = s.strip().lower()
    # Accept if there's a plausible first or last name and no digits
    if (name.first or name.last) and len(s) > 1 and not any(char.isdigit() for char in s):
        if cleaned not in non_name_terms:
            return True
    return False

# Avoid duplicates across all categories
seen = {
    "classified_as_name": {"name": set(), "first_name": set(), "last_name": set()},
    "not_recognised_as_names": {"name": set(), "first_name": set(), "last_name": set()}
}

# Analyze entries
for category in name_data:
    for value in name_data[category]:
        value = value.strip()
        if not value:
            continue

        if is_probably_name(value):
            label = "classified_as_name"
        else:
            label = "not_recognised_as_names"

        if value not in seen[label][category]:
            seen[label][category].add(value)
            result[label][category].append(value)

# Sort for readability
for main_cat in result:
    for subcat in result[main_cat]:
        result[main_cat][subcat].sort()

# Write output JSON
with open(output_json, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ Classification complete. Output saved to '{output_json}'")
