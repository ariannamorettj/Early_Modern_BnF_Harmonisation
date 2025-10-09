import os
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations

# Directory containing the CSV files
CSV_DIR = "data/unified_dataset/unified_chunks"
# Output JSON path
OUTPUT_PATH = "final_dataset_analysis/reports/duplicates_report.json"

# Helper: split semicolon-separated fields and normalize
def parse_multiple_uris(value):
    if not value:
        return []
    return [uri.strip() for uri in value.split(';') if uri.strip()]

# First pass: Collect all entity links per record
all_editions = []
all_expressions = []
all_works = []

edition_to_expressions = defaultdict(set)
edition_to_works = defaultdict(set)

work_to_editions = defaultdict(set)
work_to_expressions = defaultdict(set)

expression_to_editions = defaultdict(set)
expression_to_works = defaultdict(set)

# For co-occurrence analysis
paired_works = defaultdict(set)
paired_expressions = defaultdict(set)
paired_editions = defaultdict(set)

# Process all CSVs
for filename in os.listdir(CSV_DIR):
    if filename.endswith(".csv"):
        file_path = os.path.join(CSV_DIR, filename)
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                editions = parse_multiple_uris(row.get("edition", ""))
                expressions = parse_multiple_uris(row.get("expression", ""))
                works = parse_multiple_uris(row.get("work", ""))

                # Accumulate for statistics
                all_editions.extend(editions)
                all_expressions.extend(expressions)
                all_works.extend(works)

                # Build direct relations
                for ed in editions:
                    edition_to_expressions[ed].update(expressions)
                    edition_to_works[ed].update(works)
                for wk in works:
                    work_to_editions[wk].update(editions)
                    work_to_expressions[wk].update(expressions)
                for ex in expressions:
                    expression_to_editions[ex].update(editions)
                    expression_to_works[ex].update(works)

                # Co-occurrence (mutual pairing)
                for pair in combinations(set(works), 2):
                    a, b = sorted(pair)
                    paired_works[a].add(b)
                    paired_works[b].add(a)
                for pair in combinations(set(expressions), 2):
                    a, b = sorted(pair)
                    paired_expressions[a].add(b)
                    paired_expressions[b].add(a)
                for pair in combinations(set(editions), 2):
                    a, b = sorted(pair)
                    paired_editions[a].add(b)
                    paired_editions[b].add(a)

# Count global occurrences
edition_counts = Counter(all_editions)
expression_counts = Counter(all_expressions)
work_counts = Counter(all_works)

# Build structured report
report = {
    "general": {
        "editions": {
            "total": len(all_editions),
            "unique": len(set(all_editions))
        },
        "expressions": {
            "total": len(all_expressions),
            "unique": len(set(all_expressions))
        },
        "works": {
            "total": len(all_works),
            "unique": len(set(all_works))
        }
    },
    "occurrences": {
        "editions": {k: v for k, v in edition_counts.items() if v > 1},
        "expressions": {k: v for k, v in expression_counts.items() if v > 1},
        "works": {k: v for k, v in work_counts.items() if v > 1}
    },
    "detail": {
        "editions_with_multiple_works": {k: sorted(list(v)) for k, v in edition_to_works.items() if len(v) > 1},
        "editions_with_multiple_expressions": {k: sorted(list(v)) for k, v in edition_to_expressions.items() if len(v) > 1},
        "works_with_multiple_editions": {k: sorted(list(v)) for k, v in work_to_editions.items() if len(v) > 1},
        "works_with_multiple_expressions": {k: sorted(list(v)) for k, v in work_to_expressions.items() if len(v) > 1},
        "expressions_with_multiple_editions": {k: sorted(list(v)) for k, v in expression_to_editions.items() if len(v) > 1},
        "expressions_with_multiple_works": {k: sorted(list(v)) for k, v in expression_to_works.items() if len(v) > 1},
        "paired_works": {k: sorted(list(v)) for k, v in paired_works.items() if v},
        "paired_editions": {k: sorted(list(v)) for k, v in paired_editions.items() if v},
        "paired_expressions": {k: sorted(list(v)) for k, v in paired_expressions.items() if v}
    }
}

# Create output folder if it doesn't exist
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# Save report to JSON
with open(OUTPUT_PATH, "w", encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

# Summary printout
print("\n--- Duplicates in the dataset (URIs treated individually) ---")
print(f"Duplicate editions: {'Yes' if any(v > 1 for v in edition_counts.values()) else 'No'}")
print(f"Duplicate expressions: {'Yes' if any(v > 1 for v in expression_counts.values()) else 'No'}")
print(f"Duplicate works: {'Yes' if any(v > 1 for v in work_counts.values()) else 'No'}")
print(f"\n✅ Report saved to: {OUTPUT_PATH}")
