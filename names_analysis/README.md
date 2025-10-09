# **Names Analysis Toolkit**

This module automates the extraction, classification, and review of **agent name data** (authors, translators, editors, etc.) from BnF-derived CSV datasets.
It includes both **rule-based** and **AI-assisted (Flair)** components for multilingual name detection and noise filtering.

## Index

* [names_dict_maker.py](#names_dict_makerpy)
* [detect_real_names.py](#detect_real_namespy)
* [enhanced_detect_names.py](#enhanced_detect_namespy)
* [enhanced_detect_names_cleaner.py](#enhanced_detect_names_cleanerpy)
* [csv_analysis_maker.py](#csv_analysis_makerpy)
* [Summary Table](#summary-table)

---

<a id="names_dict_makerpy"></a>

## **1. Build Unified Names Dictionary**

**File:** `names_analysis/names_dict_maker.py`

**Purpose**
Aggregate all name-like values from BnF CSV exports into a unified JSON dictionary, grouped by `name`, `first_name`, and `last_name`.

**Inputs**

* Folder: `data/results_bnf/` (recursive search for `*.csv`)

**Process**

* Detect columns whose names contain:

  * `"first_name"` → → **first_name**
  * `"last_name"` → → **last_name**
  * `"name"` (but not `"first"`/`"last"`) → → **name**
* Trim and collect all non-empty values.
* Deduplicate with Python sets, then sort.

**Output**

* `names_analysis/names_results/names_dict.json`

  ```json
  {
    "name": ["Thomas Hobbes", "Direction"],
    "first_name": ["Thomas"],
    "last_name": ["Hobbes"]
  }
  ```

**Usage**

```bash
python names_analysis/names_dict_maker.py
```

---

<a id="detect_real_namespy"></a>

## **2. Detect Real Names (Rule-based)**

**File:** `names_analysis/detect_real_names.py`

**Purpose**
Apply heuristic classification using [`nameparser`](https://github.com/derek73/python-nameparser) and a bilingual stoplist to separate personal names from non-names (roles, collectives, placeholders).

**Inputs**

* `names_analysis/names_results/names_dict.json`

**Process**

* Parse each string with `HumanName`.
* Accept if:

  * Has `.first` or `.last` components.
  * No digits, min length > 1.
  * Not in the bilingual stoplist (e.g., *auteur*, *direction*, *anonyme*).
* Store in `"classified_as_name"` or `"not_recognised_as_names"`.

**Output**

* `names_analysis/names_results/names_classification_report.json`

**Example**

```json
{
  "classified_as_name": {"name": ["Thomas Hobbes"], "first_name": ["Thomas"], "last_name": ["Hobbes"]},
  "not_recognised_as_names": {"name": ["Anonyme", "Direction"], "first_name": ["Inconnu"], "last_name": ["Société"]}
}
```

**Usage**

```bash
python names_analysis/detect_real_names.py
```

---

<a id="enhanced_detect_namespy"></a>

## **3. Detect Real Names (AI-enhanced, Flair NER)**

**File:** `names_analysis/enhanced_detect_names.py`

**Purpose**
Use the multilingual **Flair NER model (`flair/ner-multi`)** to classify entries as person names (`PER`) vs. non-names.

**Inputs**

* `names_analysis/names_results/names_dict.json`

**Process**

* Load pretrained `SequenceTagger("flair/ner-multi")`.
* For each string:

  * Predict named entities.
  * If any has label `"PER"`, classify as `"classified_as_name"`.
* Deduplicate and sort.

**Output**

* `names_analysis/names_results/names_classification_report_flair.json`

**Example**

```json
{
  "classified_as_name": {"name": ["Thomas Hobbes"], "first_name": ["Thomas"], "last_name": ["Hobbes"]},
  "not_recognised_as_names": {"name": ["Direction"], "first_name": ["Inconnu"], "last_name": ["Société"]}
}
```

**Dependencies**

```bash
pip install flair
```

**Usage**

```bash
python names_analysis/enhanced_detect_names.py
```

---

<a id="enhanced_detect_names_cleanerpy"></a>

## **4. Flair-Assisted Noise Extraction**

**File:** `names_analysis/enhanced_detect_names_cleaner.py`

**Purpose**
Detect strings that contain **extraneous non-name fragments**, such as roles or notes (e.g. `"Thomas Hobbes (translator)"`), using Flair NER and extract the leftover “noise” portion.

**Inputs**

* `names_analysis/names_results/names_dict.json`

**Process**

* Run NER tagging on each string.
* Extract all **PER spans**.
* Concatenate text segments **outside** those spans → `non_name_part`.
* If any non-name remainder exists, record `(original, non_name_part)`.

**Output**

* `names_analysis/names_results/names_noise_removed_flair.json`

**Example**

```json
{
  "not_classified_as_name": {
    "name": [
      ["Thomas Hobbes (translator)", " (translator)"],
      ["Direction", "Direction"]
    ],
    "first_name": [],
    "last_name": []
  }
}
```

**Usage**

```bash
python names_analysis/enhanced_detect_names_cleaner.py
```

---

<a id="csv_analysis_makerpy"></a>

## **5. Review Table Builder**

**File:** `names_analysis/csv_analysis_maker.py`

**Purpose**
Flatten JSON classification results (from either `detect_real_names` or `enhanced_detect_names`) into a human-reviewable CSV table.

**Inputs**

* `names_analysis/names_results/names_classification_report_flair.json`
  *(or `names_classification_report.json`)*

**Process**

* For each classified item, create a row with:

  * `string`, `type` (name/first/last),
  * `classified_as`,
  * `not_name_part` (if present, from tuples),
  * `human_check` (empty, for manual validation).
* Write to CSV.

**Output**

* `names_analysis/names_results/names_review_table.csv`

**Example**

```csv
string,type,classified_as,not_name_part,human_check
Thomas Hobbes,name,responsible agent name,,
Direction,name,not responsible agent name,,
Thomas Hobbes (translator),name,responsible agent name, (translator),
```

**Usage**

```bash
python names_analysis/csv_analysis_maker.py
```

---

## **Summary Table**

| File                                 | Purpose                                                   | Input                                                  | Output                                                 |
| ------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------ |
| **names_dict_maker.py**              | Collect all name-like values from CSVs into unified JSON  | `data/results_bnf/*.csv`                               | `names_results/names_dict.json`                        |
| **detect_real_names.py**             | Rule-based name classification using `nameparser`         | `names_results/names_dict.json`                        | `names_results/names_classification_report.json`       |
| **enhanced_detect_names.py**         | AI-based name classification using Flair multilingual NER | `names_results/names_dict.json`                        | `names_results/names_classification_report_flair.json` |
| **enhanced_detect_names_cleaner.py** | Extract non-name noise fragments using Flair              | `names_results/names_dict.json`                        | `names_results/names_noise_removed_flair.json`         |
| **csv_analysis_maker.py**            | Build manual review CSV from classification outputs       | `names_results/names_classification_report_flair.json` | `names_results/names_review_table.csv`                 |

---

<a id="summary-table"></a>
