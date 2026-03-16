import zipfile
import csv
import io
import os
import random
from datetime import datetime
from collections import Counter

def explore_zip(zf, prefix=""):
    structure = []
    ext_counter = Counter()
    for name in zf.namelist():
        full = os.path.join(prefix, name)
        if name.endswith(".zip"):
            ext_counter["zip"] += 1
            with zf.open(name) as nested:
                data = nested.read()
                with zipfile.ZipFile(io.BytesIO(data)) as nested_zf:
                    sub_structure, sub_counter = explore_zip(nested_zf, full)
                    structure.append((full, "zip"))
                    structure.extend(sub_structure)
                    ext_counter.update(sub_counter)
        else:
            ext = os.path.splitext(name)[1].lower()
            ext_counter[ext] += 1
            structure.append((full, "file"))
    return structure, ext_counter

def extract_csv_info(zf, prefix=""):
    csv_files = {}
    for name in zf.namelist():
        full = os.path.join(prefix, name)
        if name.endswith(".zip"):
            with zf.open(name) as nested:
                data = nested.read()
                with zipfile.ZipFile(io.BytesIO(data)) as nested_zf:
                    csv_files.update(extract_csv_info(nested_zf, full))
        elif name.endswith(".csv"):
            with zf.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8")
                reader = csv.DictReader(text)
                cols = tuple(reader.fieldnames)
                rows = list(reader)
                csv_files[full] = (cols, rows)
    return csv_files

def group_by_columns(csv_files):
    structures = {}
    for path, (cols, rows) in csv_files.items():
        structures.setdefault(cols, []).append((path, rows))
    return structures

def sample_rows(rows):
    if len(rows) <= 10:
        return rows
    return random.sample(rows, 10)

def generate_report(zip_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(
        output_dir,
        f"{os.path.basename(zip_path)}_{timestamp}.txt"
    )

    with zipfile.ZipFile(zip_path) as zf:
        structure, counters = explore_zip(zf)
        csv_files = extract_csv_info(zf)
        groups = group_by_columns(csv_files)

    with open(report_path, "w", encoding="utf-8") as out:
        out.write("ZIP STRUCTURE\n")
        out.write("--------------\n")
        out.write("File counts by extension:\n")
        for ext, count in counters.items():
            out.write(f"{ext}: {count}\n")

        out.write("\nFile tree:\n")
        for path, kind in structure:
            out.write(f"{kind}: {path}\n")

        out.write("\nCSV ANALYSIS\n")
        out.write("-------------\n")
        out.write(f"Total column structures found: {len(groups)}\n")

        for idx, (cols, files) in enumerate(groups.items(), start=1):
            out.write(f"\nStructure {idx}:\n")
            out.write("Columns: " + ", ".join(cols) + "\n")
            out.write("Files:\n")
            for path, _ in files:
                out.write(f"  - {path}\n")

            sample_path, sample_rows_list = random.choice(files)
            out.write(f"Sample taken from: {sample_path}\n")
            for row in sample_rows(sample_rows_list):
                out.write(str(row) + "\n")

    return report_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python zip_sampler.py <output_dir> <zip1> [<zip2> ...]")
        sys.exit(1)
    output = sys.argv[1]
    for z in sys.argv[2:]:
        print("Report:", generate_report(z, output))
