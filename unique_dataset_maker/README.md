# **Unique Dataset Maker**

This module merges multiple year-based BnF export datasets into a single **unified editions dataset**, preserving full provenance, and then splits the result back into **per-year chunks** for modular analysis.

It consists of two main scripts:

1. `dataset_maker.py` – merges and logs provenance
2. `dataset_maker_split_year.py` – splits the unified file into clean per-year CSVs

## Index

* [dataset_maker.py](#dataset_makerpy)
* [dataset_maker_split_year.py](#dataset_maker_split_yearpy)
* [Summary Table](#summary-table)
* [Pipeline summary](#pipeline-summary)

---

<a id="dataset_makerpy"></a>

## **1. Merge & Provenance Logger**

**File:** `unique_dataset_maker/dataset_maker.py`
**Inputs:** CSVs under `data/results_bnf/<YEAR>/**.csv`
**Outputs:**

* `data/unified_dataset/merged_editions_dataset_with_log.csv`
* `data/unified_dataset/merged_editions_sources_log.json`

### **Purpose**

Aggregate all year-based BnF CSVs into a **unique-by-`edition`** dataset and generate a detailed **source log** showing which files contributed each field value.

### **Process Overview**

1. **Traverse year directories** under `data/results_bnf/` with a progress bar.
2. For every `*.csv`:

   * Load via pandas (`dtype=str`, `on_bad_lines='skip'`, `fillna("")`).
   * Drop malformed rows (column count mismatch).
   * Skip if missing the `edition` column.
   * For each record:

     * Record the `edition` itself and its `year_dir` (folder name).
     * Collect every other field’s non-empty values.
     * Track the **source file** for each `(edition, field, value)` pair.
3. **Aggregate results**:

   * Deduplicate values and join them with `;`.
   * Build one consolidated row per edition.
4. **Export:**

   * `merged_editions_dataset_with_log.csv`: unified dataset.
   * `merged_editions_sources_log.json`: full provenance log.

### **Example Outputs**

**CSV structure**

```
"edition","year_dir","actor","record_type","title",...
"https://.../cb12345","1651;1652","Hobbes;Thomas Hobbes","http://purl.org/dc/dcmitype/Text","Leviathan",...
```

**JSON structure**

```json
{
  "https://.../cb12345": {
    "edition": {
      "https://.../cb12345": [
        "data/results_bnf/1651/export.csv",
        "data/results_bnf/1652/export.csv"
      ]
    },
    "year_dir": {
      "1651": ["data/results_bnf/1651/export.csv"]
    },
    "title": {
      "Leviathan": [
        "data/results_bnf/1651/export.csv",
        "data/results_bnf/1652/export.csv"
      ]
    }
  }
}
```

### **Notes**

* All field values are deduplicated within editions.
* Empty or malformed rows are skipped gracefully.
* Quotes are always applied to avoid delimiter issues.
* The `year_dir` column is essential for downstream splitting.

**Usage**

```bash
python unique_dataset_maker/dataset_maker.py
```

**Console output**

```
Processing year directories: 100%|████████████████████████| ...
CSV saved to 'data/unified_dataset/merged_editions_dataset_with_log.csv'
JSON log saved to 'data/unified_dataset/merged_editions_sources_log.json'
```

---

<a id="dataset_maker_split_yearpy"></a>

## **2. Split Unified Dataset by Year**

**File:** `unique_dataset_maker/dataset_maker_split_year.py`
**Input:** `data/unified_dataset/merged_editions_dataset_with_log.csv`
**Output folder:** `data/unified_dataset/unified_chunks/`

### **Purpose**

Split the large unified dataset into **separate CSV files per year**, based on the `year_dir` field.
Each output file is cleaned and ready for targeted analysis (e.g., `final_dataset_analysis/` scripts).

### **Process Overview**

1. Load the merged dataset (`merged_editions_dataset_with_log.csv`).
2. Clean:

   * Replace all double quotes (`"`) with single quotes (`'`) to avoid nesting.
   * Trim whitespace globally.
3. Validate the presence of the `year_dir` column.
4. For each unique `year_dir` value (may contain multiple years separated by `;`):

   * Split it into individual years.
   * Filter the dataset for rows mentioning each year.
   * Export a CSV named `<year>.csv` to `data/unified_dataset/unified_chunks/`.
   * Use safe quoting (`QUOTE_MINIMAL`) and escaping (`\`) to avoid malformed cells.
5. Print confirmation for each chunk.

### **Example Outputs**

* `data/unified_dataset/unified_chunks/1651.csv`
* `data/unified_dataset/unified_chunks/1652.csv`
* …

### **Sample Console Output**

```
 Loading file: data/unified_dataset/merged_editions_dataset_with_log.csv
 Created: data/unified_dataset/unified_chunks/1651.csv (21456 rows)
 Created: data/unified_dataset/unified_chunks/1652.csv (19873 rows)
 Splitting completed without nested quotes.
```

### **Notes**

* Works seamlessly with the output of `dataset_maker.py`.
* Handles multi-year entries like `"1651;1652"` correctly.
* Ensures all quote characters are consistent before writing.
* Each output file maintains the same schema as the unified dataset.

**Usage**

```bash
python unique_dataset_maker/dataset_maker_split_year.py
```

---

<a id="summary-table"></a>

## **Summary Table**

| Python File                     | Purpose                                                                                          | Input                                                       | Output                                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **dataset_maker.py**            | Merge all year-based CSVs into a unique-by-`edition` dataset and generate a full provenance log. | `data/results_bnf/<YEAR>/**.csv`                            | `data/unified_dataset/merged_editions_dataset_with_log.csv`, `data/unified_dataset/merged_editions_sources_log.json` |
| **dataset_maker_split_year.py** | Split the unified dataset by `year_dir` into clean per-year chunks for downstream analysis.      | `data/unified_dataset/merged_editions_dataset_with_log.csv` | `data/unified_dataset/unified_chunks/<year>.csv`                                                                     |

---

<a id="pipeline-summary"></a>
**Pipeline summary:**

```
raw year-based CSVs
      ↓
 dataset_maker.py → merged_editions_dataset_with_log.csv + sources_log.json
      ↓
 dataset_maker_split_year.py → unified_chunks/<year>.csv
```
