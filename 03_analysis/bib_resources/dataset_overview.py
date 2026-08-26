import os
import csv
import sys
from datetime import datetime

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2192 (→) used below, raising
# UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# list all columns names
source_path = "data/results_bnf"
report_path = "report.txt"
colonne_trovate = set()

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# recursive scan of input dir
for root, dirs, files in os.walk(source_path):
    for file in files:
        if file.lower().endswith(".csv"):
            full_path = os.path.join(root, file)
            try:
                with open(full_path, newline='', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    headers = next(reader, None)
                    if headers:
                        colonne_trovate.update(headers)
                        print(f"[{file}] → {headers}")
            except Exception as e:
                print(f"Errore nel file {full_path}: {e}")

# Scrittura del report (append se esiste)
with open(report_path, "a", encoding='utf-8') as report:
    report.write(f"\n\n=== New code run - COLUMN NAMES FINDER at {timestamp}===\n")
    for colonna in sorted(colonne_trovate):
        report.write(colonna + "\n")

print(f"\n Unique column names in input dir: {len(colonne_trovate)}")
print(f"Report written in '{report_path}'")
