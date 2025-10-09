import os
import pandas as pd
import csv

# Input and output paths
input_csv = "data/unified_dataset/merged_editions_dataset_with_log.csv"
output_dir = "data/unified_dataset/unified_chunks"
os.makedirs(output_dir, exist_ok=True)

# Function to clean double quotes from values
def clean_quotes(value):
    if pd.isna(value):
        return ""
    return str(value).replace('"', "'").strip()  # replaces " with ' and avoids nesting

# Load the full dataset
print(f"📥 Loading file: {input_csv}")
df = pd.read_csv(input_csv, dtype=str).fillna("")

# Clean double quotes globally
df = df.applymap(clean_quotes)

# Check for 'year_dir' column
if "year_dir" not in df.columns:
    raise ValueError("❌ 'year_dir' column not found in the CSV file")

# Split by year
for year in df["year_dir"].dropna().unique():
    years = [y.strip() for y in year.split(";") if y.strip()]
    for y in years:
        df_subset = df[df["year_dir"].str.contains(rf"\b{y}\b", na=False)]
        output_path = os.path.join(output_dir, f"{y}.csv")

        df_subset.to_csv(
            output_path,
            index=False,
            encoding="utf-8",
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            escapechar='\\'
        )
        print(f"✅ Created: {output_path} ({len(df_subset)} rows)")

print("🎉 Splitting completed without nested quotes.")
