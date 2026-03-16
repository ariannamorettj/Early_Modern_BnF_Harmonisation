import zipfile
import csv
import io
import os
from datetime import datetime

def extract_csvs(zf, prefix=""):
    csv_files = {}
    for name in zf.namelist():
        full = os.path.join(prefix, name)
        if name.endswith(".zip"):
            with zf.open(name) as nested:
                data = nested.read()
                with zipfile.ZipFile(io.BytesIO(data)) as nested_zf:
                    csv_files.update(extract_csvs(nested_zf, full))
        elif name.endswith(".csv"):
            with zf.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8")
                reader = csv.DictReader(text)
                rows = list(reader)
            csv_files[full] = rows
    return csv_files

def collect_values(csv_files, columns, target_file=None):
    values = {col: set() for col in columns}
    for path, rows in csv_files.items():
        if target_file is not None and not path.endswith(target_file):
            continue
        for row in rows:
            for col in columns:
                if col in row and row[col] is not None:
                    values[col].add(row[col])
    return values

def generate_report(zip_path, columns, output_dir, target_file=None):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"column_values_{os.path.basename(zip_path)}_{timestamp}.txt"
    report_path = os.path.join(output_dir, report_name)

    with zipfile.ZipFile(zip_path) as zf:
        csv_files = extract_csvs(zf)

    values = collect_values(csv_files, columns, target_file)

    with open(report_path, "w", encoding="utf-8") as out:
        out.write("COLUMN VALUE REPORT\n")
        out.write("-------------------\n")
        out.write(f"ZIP: {zip_path}\n")
        if target_file:
            out.write(f"Restricted to file: {target_file}\n")
        out.write("Columns: " + ", ".join(columns) + "\n\n")

        for col in columns:
            sorted_values = sorted(values[col], key=lambda x: str(x).lower())
            out.write(f"Column: {col}\n")
            out.write(f"Unique values found: {len(sorted_values)}\n")
            for v in sorted_values:
                out.write(str(v) + "\n")
            out.write("\n")

    return report_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python column_values_reporter.py <zipfile> <output_dir> <col1> [<col2> ...] [--file <csv_name_inside_zip>]")
        sys.exit(1)

    zip_path = sys.argv[1]
    output_dir = sys.argv[2]

    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        columns = sys.argv[3:idx]
        target_file = sys.argv[idx + 1]
    else:
        columns = sys.argv[3:]
        target_file = None

    report = generate_report(zip_path, columns, output_dir, target_file)
    print("Report saved to:", report)


## sample run

'''
python zip_sampler/column_values_reporter.py \
    missing_agent_data_supplement.zip \
    zip_sampler/fields_report \
    actor_last_name entity_type
'''

'''
python zip_sampler/column_values_reporter.py \
    data/bnf_agents_data_querying/actor_queries_results.zip \
    zip_sampler/fields_report \
    actor_profession
'''