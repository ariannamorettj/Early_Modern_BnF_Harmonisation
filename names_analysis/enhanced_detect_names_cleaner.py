import json
from flair.models import SequenceTagger
from flair.data import Sentence

# Load multilingual NER model
tagger = SequenceTagger.load("flair/ner-multi")

# File input/output
input_json = "names_analysis/names_results/names_dict.json"
output_json = "names_analysis/names_results/names_noise_removed_flair.json"

# Load the input JSON
with open(input_json, "r", encoding="utf-8") as f:
    name_data = json.load(f)

# Output structure: only problematic entries
result = {
    "not_classified_as_name": {
        "name": [],
        "first_name": [],
        "last_name": []
    }
}


# Helper: extract non-name parts
def extract_non_name_parts(text):
    sentence = Sentence(text)
    tagger.predict(sentence)

    person_spans = [ent for ent in sentence.get_spans("ner") if ent.get_label("ner").value == "PER"]

    if not person_spans:
        return text  # whole string is non-name
    else:
        # Rebuild full text from spans to extract what's outside
        spans = [(span.start_position, span.end_position) for span in person_spans]
        non_name_parts = []
        current = 0
        for start, end in spans:
            if current < start:
                non_name_parts.append(text[current:start])
            current = end
        if current < len(text):
            non_name_parts.append(text[current:])

        cleaned = "".join(non_name_parts).strip()
        return cleaned if cleaned else None


# Iterate through all values
for category in name_data:
    for value in name_data[category]:
        value = value.strip()
        if not value:
            continue

        non_name_part = extract_non_name_parts(value)
        if non_name_part:
            result["not_classified_as_name"][category].append((value, non_name_part))

# Save the result
with open(output_json, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ Extraction complete. Problematic strings saved to '{output_json}'")
