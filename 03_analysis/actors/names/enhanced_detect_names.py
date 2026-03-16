import json
from flair.models import SequenceTagger
from flair.data import Sentence

# Load multilingual NER tagger
tagger = SequenceTagger.load("flair/ner-multi")

# File input/output
input_json = "names_analysis/names_results/names_dict.json"
output_json = "names_analysis/names_results/names_classification_report_flair.json"

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

# Cache to avoid duplicates
seen = {
    "classified_as_name": {"name": set(), "first_name": set(), "last_name": set()},
    "not_recognised_as_names": {"name": set(), "first_name": set(), "last_name": set()}
}

# Helper function using Flair NER
def is_person_flair(text):
    sentence = Sentence(text)
    tagger.predict(sentence)
    for entity in sentence.get_spans("ner"):
        if entity.get_label("ner").value == "PER":
            return True
    return False

# Analyze values in each category
for category in name_data:
    for value in name_data[category]:
        value = value.strip()
        if not value:
            continue

        label = "classified_as_name" if is_person_flair(value) else "not_recognised_as_names"

        if value not in seen[label][category]:
            seen[label][category].add(value)
            result[label][category].append(value)

# Sort the results
for main_cat in result:
    for subcat in result[main_cat]:
        result[main_cat][subcat].sort()

# Save to JSON file
with open(output_json, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ Multilingual AI classification complete using Flair. Output saved to '{output_json}'")
