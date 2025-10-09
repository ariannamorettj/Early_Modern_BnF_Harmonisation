import json

with open("final_dataset_analysis/reports/edition_to_allowed_record_types.json", encoding="utf-8") as f:
    print(len(json.load(f)))
