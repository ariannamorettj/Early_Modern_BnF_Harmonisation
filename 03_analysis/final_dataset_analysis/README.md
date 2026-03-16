# **Final Dataset Analysis – Scripts Overview**

This section documents all analysis scripts under `final_dataset_analysis/`.
Each script processes the unified dataset chunks stored in
`data/unified_dataset/unified_chunks/`, generating reports used to verify data structure, linkage consistency, and record typing in the BnF dataset.

## Index

* [counting_types.py](#counting_typespy)
* [edition_record_type_analysis.py](#edition_record_type_analysispy)
* [editions_additional_analysis.py](#editions_additional_analysispy)
* [editions_analysis.py](#editions_analysispy)
* [fetch_bnf_ark_titles.py](#fetch_bnf_ark_titlespy)
* [find_entities_without_record_type.py](#find_entities_without_record_typepy)
* [no_type_random_sample.py](#no_type_random_samplepy)
* [stupid_counter.py](#stupid_counterpy)
* [Summary Table](#summary-table)
* [Results Summary Appendix](#results-summary-appendix)

---

<a id="counting_typespy"></a>

## **1. Record Type Counting**

**File:** `final_dataset_analysis/counting_types.py`
**Inputs:** CSV files in `data/unified_dataset/unified_chunks/`
**Outputs:**

* `final_dataset_analysis/reports/record_type_counts.json`
* `final_dataset_analysis/reports/record_type_entity_cardinality.json`

**Purpose**
Count global occurrences of each `record_type` and compute the distribution of how many `record_type` values each entity has (0, 1, 2, …).

**Process / Logic**

* Scan all CSVs (auto-detect delimiter, try encodings `utf-8-sig`, `utf-8`, `latin-1`).
* Parse and split the `record_type` field on `;`.
* For each row:

  * Count how many distinct `record_type` values it has.
  * Increment totals per unique type.
* Write two JSON files with per-type counts and entity cardinalities.

**Usage**

```bash
python final_dataset_analysis/counting_types.py
```

---

<a id="edition_record_type_analysispy"></a>

## **2. Edition → Allowed Record Types**

**File:** `final_dataset_analysis/edition_record_type_analysis.py`
**Inputs:**

* `final_dataset_analysis/reports/bnf_ark_titles.json`
* CSVs in `data/unified_dataset/unified_chunks/`
  **Output:**
  `final_dataset_analysis/reports/edition_to_allowed_record_types.json`

**Purpose**
Create a mapping from **edition URIs** to lists of allowed `record_type` values (and their labels), based on a whitelist from `bnf_ark_titles.json`.

**Process / Logic**

* Load the whitelist of allowed types (`bnf_ark_titles.json`).
* For each CSV row:

  * Keep only those where *all* `record_type` values belong to the whitelist.
  * Build labeled lists `{ record_type_uri: label }`.
  * Assign them to each edition URI.
* Skip rows missing `edition` or `record_type`.

**Usage**

```bash
python final_dataset_analysis/edition_record_type_analysis.py
```

---

<a id="editions_additional_analysispy"></a>

## **3. Editions / Expressions / Works Link Analysis**

**File:** `final_dataset_analysis/editions_additional_analysis.py`
**Inputs:** CSVs in `data/unified_dataset/unified_chunks/`
**Outputs:**

* `final_dataset_analysis/reports/work_link_summary.json`
* `final_dataset_analysis/reports/edition_expression_checks.json`
* `final_dataset_analysis/reports/focus_uris.json` *(optional)*

**Purpose**
Analyze the structure and cardinality of edition–expression–work relationships, with optional filtering by `record_type`.

**Process / Logic**

* Parse each row, split multiple URIs, drop empties.
* Build bidirectional maps:

  * edition ↔ expression
  * work ↔ edition, work ↔ expression
* Compute:

  1. **`work_link_summary.json`** — count how many works have editions/expressions/both/neither.
  2. **`edition_expression_checks.json`** — detect editions with multiple expressions or missing links.
  3. **`focus_uris.json`** *(optional)* — show detailed connections for specific URIs of interest.

**Usage**

```bash
python final_dataset_analysis/editions_additional_analysis.py \
  --record-type http://purl.org/dc/dcmitype/Text
```

---

<a id="editions_analysispy"></a>

## **4. Editions / Expressions / Works Duplicate and Co-occurrence Analysis**

**File:** `final_dataset_analysis/editions_analysis.py`
**Inputs:** CSVs in `data/unified_dataset/unified_chunks/`
**Output:** `final_dataset_analysis/reports/duplicates_report.json`

**Purpose**
Detect duplicates, identify one-to-many relationships, and record co-occurrences among editions, expressions, and works.

**Process / Logic**

1. Read all CSVs, parse semicolon-separated URIs.
2. Count total and unique occurrences for editions, expressions, works.
3. Build relationship maps:

   * edition → works / expressions
   * work → editions / expressions
   * expression → editions / works
4. Record **co-occurrences** of entities appearing together.
5. Generate JSON with three main sections:

   * `general` → global counts (total, unique)
   * `occurrences` → duplicated URIs
   * `detail` → many-to-many relationships and co-occurrence pairs.

**Output Example**

```json
{
  "general": { "editions": {"total": 100, "unique": 80}, ... },
  "occurrences": { "editions": {"uri1": 2, ...} },
  "detail": { "works_with_multiple_editions": {...}, "paired_works": {...} }
}
```

**Usage**

```bash
python final_dataset_analysis/editions_analysis.py
```

---

<a id="fetch_bnf_ark_titlespy"></a>

## **5. Fetch BnF ARK Titles**

**File:** `final_dataset_analysis/fetch_bnf_ark_titles.py`
**Input:** `final_dataset_analysis/reports/record_type_counts.json`
**Output:** `final_dataset_analysis/reports/bnf_ark_titles.json`

**Purpose**
Fetch and extract the human-readable titles of BnF entities whose URIs appear in `record_type_counts.json`.

**Process / Logic**

* Filter URIs beginning with `data.bnf.fr/ark:/12148/`.
* Fetch the HTML page (with retry logic).
* Extract title from:

  1. `h1[itemprop="name"]`
  2. `div.page_title h1`
  3. `#presentation h1`
  4. `h1#page-title`
  5. `h1.page-title`
  6. `meta[property="og:title"]`
  7. `meta[name="DC.title"]`
  8. `<title>`
* Save JSON `{ url: title }`.

**Usage**

```bash
python final_dataset_analysis/fetch_bnf_ark_titles.py
```

---

<a id="find_entities_without_record_typepy"></a>

## **6. Find Editions Without Record Type**

**File:** `final_dataset_analysis/find_entities_without_record_type.py`
**Inputs:** CSVs in `data/unified_dataset/unified_chunks/`
**Outputs:**

* `final_dataset_analysis/reports/editions_without_record_type.json`
* `final_dataset_analysis/reports/editions_without_record_type.csv`

**Purpose**
Identify edition entities lacking any declared `record_type`.

**Process / Logic**

* Parse each CSV (auto-detect delimiter and encoding).
* For each row:

  * If `record_type` is empty or missing → mark editions as “without type.”
* Output deduplicated lists of such editions (JSON + CSV).

**Usage**

```bash
python final_dataset_analysis/find_entities_without_record_type.py
```

---

<a id="no_type_random_samplepy"></a>

## **7. No-Type Random Sample (BnF Catalogue H1)**

**File:** `final_dataset_analysis/no_type_random_sample.py`
**Inputs:** CSVs in `data/unified_dataset/unified_chunks/`
**Output:** `final_dataset_analysis/reports/no_type_random_sample.csv`

**Purpose**
Randomly select 100 editions without a `record_type`, fetch their BnF *catalogue* page, and extract the `<h1>` title to assess whether they can be classified as textual.

**Process / Logic**

* Collect editions with no record type (as in script 6).
* Draw reproducible random sample (seed 42).
* Convert each to `https://catalogue.bnf.fr/ark:/12148/...`.
* Fetch with retries and extract H1 (`div.titrenotices h1` etc.).
* Write CSV with `edition`, `edition_catalogue`, and `title_h1`.

**Usage**

```bash
python final_dataset_analysis/no_type_random_sample.py
```

---

<a id="stupid_counterpy"></a>

## **8. Quick Count Utility**

**File:** `final_dataset_analysis/stupid_counter.py`
**Input:** `final_dataset_analysis/reports/edition_to_allowed_record_types.json`
**Output:** Console print of total edition count.

**Purpose**
Simple diagnostic script that prints the number of edition entries with allowed record types.

**Usage**

```bash
python final_dataset_analysis/stupid_counter.py
```

---

## **Summary Table**

| Python File                            | Purpose                                                                      | Input                                       | Output                                                                        |
| -------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------- |
| `counting_types.py`                    | Count and categorize `record_type` values and per-entity cardinality.        | `data/unified_dataset/unified_chunks/*.csv` | `record_type_counts.json`, `record_type_entity_cardinality.json`              |
| `edition_record_type_analysis.py`      | Map editions to allowed record types (based on whitelist).                   | `bnf_ark_titles.json`, CSV chunks           | `edition_to_allowed_record_types.json`                                        |
| `editions_additional_analysis.py`      | Analyze edition–expression–work relations (cardinality and connectivity).    | CSV chunks                                  | `work_link_summary.json`, `edition_expression_checks.json`, `focus_uris.json` |
| `editions_analysis.py`                 | Detect duplicates and co-occurrences among editions, expressions, and works. | CSV chunks                                  | `duplicates_report.json`                                                      |
| `fetch_bnf_ark_titles.py`              | Fetch and extract human-readable titles from BnF ARK pages.                  | `record_type_counts.json`                   | `bnf_ark_titles.json`                                                         |
| `find_entities_without_record_type.py` | Identify editions with missing or empty `record_type`.                       | CSV chunks                                  | `editions_without_record_type.json`, `editions_without_record_type.csv`       |
| `no_type_random_sample.py`             | Sample 100 editions without record type and extract their BnF `<h1>` title.  | CSV chunks                                  | `no_type_random_sample.csv`                                                   |
| `stupid_counter.py`                    | Quick count of editions with allowed record types.                           | `edition_to_allowed_record_types.json`      | Console output (edition count)                                                |

---

## **Results Summary Appendix**

These reports were generated from the unified dataset chunks in
`data/unified_dataset/unified_chunks/`, filtered to records of type:

```
http://purl.org/dc/dcmitype/Text
```

### **Work Link Summary (`work_link_summary.json`)**

Summarises how many *work IDs* are connected to at least one edition and/or expression.

| Metric                               | Count  |
| ------------------------------------ | ------ |
| Total works analysed                 | 3,958  |
| Works with ≥1 edition                | 3,958  |
| Works with ≥1 expression             | 3,958  |
| Works with both edition & expression | 3,958  |
| Works with neither                   | 0      |
| Unique editions linked from works    | 22,238 |
| Unique expressions linked from works | 22,238 |

**Interpretation:**
Every work ID in this subset is linked to at least one edition and one expression; there are no works without connections.

---

### **Edition–Expression Pairing (`edition_expression_checks.json`)**

Checks cardinality and pairing between editions and expressions.

| Metric                             | Count   |
| ---------------------------------- | ------- |
| Total editions                     | 465,542 |
| Total expressions                  | 465,542 |
| Editions with multiple expressions | 0       |
| Editions without any expression    | 0       |
| Expressions without any edition    | 0       |

**Interpretation:**
There is a strict **1:1 pairing** between editions and expressions.
No editions are linked to multiple expressions, and all editions have an expression (and vice versa).

---

### **Comparative Results (Unfiltered vs Filtered Dataset)**

| Metric                             | Full Dataset | Filtered (`dc/dcmitype/Text`) |
| ---------------------------------- | ------------ | ----------------------------- |
| Editions (unique)                  | 875,018      | 465,542                       |
| Expressions (unique)               | 786,991      | 465,542                       |
| Works (unique)                     | 31,195       | 3,958                         |
| Editions with multiple expressions | 0            | 0                             |
| Editions without expression        | 0            | 0                             |
| Expressions without edition        | 0            | 0                             |

**Conclusion:**
Structural consistency is maintained across analyses — no edition has multiple expressions, and every edition–expression pairing is complete.
Differences in totals reflect dataset filtering: only **textual resources** were considered in the second run.

---
