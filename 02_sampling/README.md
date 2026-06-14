# 02_sampling

This module supports exploratory inspection of zipped datasets produced during the BnF acquisition workflow.

Its purpose is to help with **manual assessment of dataset contents** by generating reports that describe:

- the internal structure of one or more ZIP archives;
- the CSV column schemas found inside them;
- small row samples for structural inspection.

Shared internal logic is kept in:

- `02_sampling/sampling_utils.py`

---

## Files in the Module

### `01_zip_tree.py`

Generates a tree-style structural report for one or more ZIP datasets.

Traverses each input ZIP recursively, including nested ZIP files, and writes a text report containing file counts by extension together with the full internal archive tree.

### `02_column_names.py`

Reports all column names found across one or more ZIP datasets.

Scans CSV files contained in each input ZIP, including nested ZIP archives, and returns the complete set of discovered column names and, for each column, the internal CSV files where that column is present. Supports optional filtering by year and by internal CSV filename.

### `03_full_row_sample.py`

Extracts the first N best-populated rows from a ZIP dataset for quick structural inspection.

Uses an iterative fallback strategy: first attempts to collect rows where every field is non-null; if fewer than N rows are found, it retries allowing 1 null field per row, increasing the tolerance by 1 at each attempt until enough rows are collected. Null values are detected as `None`, empty strings, or any of the literal null sentinels used in the BnF CSVs (`NA`, `N/A`, `None`, `none`, `null`, `NULL`). The attempt that succeeded is reported in the console output.

### `04_column_value_sample.py`

Samples a set of well-distributed unique values for one or more columns across ZIP datasets.

Scans the dataset to collect unique non-empty values for either a specific requested column or for all discovered columns. It then returns `N` values evenly distributed along the alphabetically sorted list of unique values, providing a structural sample of the variations (length, prefixes, special characters) present in the data. If no specific column is requested, it generates a separate report for each column found.

### `sampling_utils.py`

Internal utility module used by all entry scripts in this module and by the scripts in `03_analysis`.

Contains the shared logic for:

- recursive ZIP traversal and support for nested ZIP archives;
- CSV extraction and loading;
- grouping CSV files by column structure;
- row sampling;
- collection of distinct column values and grouped value counts;
- timestamped output-name construction;
- report rendering and writing.

Not intended to be launched directly from the terminal.

---

## Input Datasets

The module works on ZIP datasets. It supports:

- plain ZIP archives containing CSV files;
- ZIP archives containing nested ZIP files;
- multiple ZIP inputs passed in a single execution.

Typical inputs:

- `01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip`
- `01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip`
- `01_data_retrieval/02_actors/data/old_zip/actor_data.zip`

---

## Output Policy

By default, reports are written to:

```
02_sampling/data
```

unless another output directory is explicitly passed via `--output-dir`.

Each output filename includes the entry script name, relevant runtime parameters, an optional dataset index when multiple ZIP files are processed in one run, and a timestamp. The input dataset path is intentionally excluded from the output filename.

If multiple input datasets are processed in a single run, the reports are distinguished with dataset indices such as `set01`, `set02`, `set03`.

---

## Script Usage

All scripts are run from the project root.

---

### `01_zip_tree.py`

```
python 02_sampling/01_zip_tree.py <input1> [<input2> ...] [options]
```

**Options**

- `--output-dir` — directory where reports will be written. Default: `02_sampling/data`
- `--encoding` — CSV decoding encoding. Default: `utf-8`
- `--skip-missing` — skip missing input datasets instead of stopping execution

**Output:** one `.txt` report per input ZIP

**Sample runs**

```python
python 02_sampling/01_zip_tree.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip
```

```python
python 02_sampling/01_zip_tree.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 02_sampling/data \
  --skip-missing
```

---

### `02_column_names.py`

```
python 02_sampling/02_column_names.py <input1> [<input2> ...] [options]
```

**Options**

- `--output-dir` — directory where reports will be written. Default: `02_sampling/data`
- `--encoding` — CSV decoding encoding. Default: `utf-8`
- `--target-file` — optional internal CSV filename restriction
- `--years` — optional list of years used to restrict the internal CSV files considered
- `--skip-missing` — skip missing input datasets instead of stopping execution

**Output:** one `.txt` report per input ZIP

**Sample runs**

```python
python 02_sampling/02_column_names.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip
```

```python
python 02_sampling/02_column_names.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --years 1454 1455 1456
```

```python
python 02_sampling/02_column_names.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --target-file raw_edition_data_for_the_year_1454.csv
```

```python
python 02_sampling/02_column_names.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 02_sampling/data \
  --skip-missing
```

---

### `03_full_row_sample.py`

```
python 02_sampling/03_full_row_sample.py <input> [options]
```

**Options**

- `--n-rows` — number of rows to collect. Default: `10`
- `--output-dir` — directory where the output CSV will be written. Default: `02_sampling/data`
- `--encoding` — CSV decoding encoding. Default: `utf-8`

**Output:** one `.csv` file with the N best-populated rows, plus an `__internal_csv_path` provenance column. The console output reports how many null fields per row were allowed to reach the target count.

**Sample runs**

```python
python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --output-dir 02_sampling/data
```

```python
python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/01_editions/data/old_zip/edition_raw_data_by_year.zip \
  --output-dir 02_sampling/data
```

```python
python 02_sampling/03_full_row_sample.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --output-dir 02_sampling/data
```

---

### `04_column_value_sample.py`

```
python 02_sampling/04_column_value_sample.py <input1> [<input2> ...] [options]
```

**Options**

- `--column` — specific column to sample. If not provided, generates a sample for every column found.
- `--n-values` — number of well-distributed values to sample per column. Default: `10`
- `--output-dir` — directory where reports will be written. Default: `02_sampling/data`
- `--encoding` — CSV decoding encoding. Default: `utf-8`
- `--target-file` — optional internal CSV filename restriction
- `--years` — optional list of years used to restrict the internal CSV files considered
- `--skip-missing` — skip missing input datasets instead of stopping execution

**Output:** one `.txt` report per column processed.

**Sample runs**

```python
python 02_sampling/04_column_value_sample.py \
  01_data_retrieval/01_editions/data/old_zip/bnf_edition_data_raw.zip \
  --n-values 150
```

```python
python 02_sampling/04_column_value_sample.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --column "actor_name" \
  --n-values 20
```

```python
python 02_sampling/04_column_value_sample.py \
  01_data_retrieval/02_actors/data/old_zip/actor_data.zip \
  --n-values 150
```

---

## Recommended Inspection Order

When using the module for manual dataset assessment, the recommended sequence is:

1. run `01_zip_tree.py` to understand the internal structure of the archive;
2. run `02_column_names.py` to discover the CSV schemas present;
3. run `03_full_row_sample.py` to inspect a concrete sample of the data;
4. run `04_column_value_sample.py` to inspect the variety of values stored within specific columns.

This order separates structural inspection of the archive from semantic inspection of the actual field contents.

---

## Dependency Summary

These scripts rely on:

- base Python (`zipfile`, `csv`, `io`, `os`, `re`, `json`, `random`)
- `02_sampling/sampling_utils.py` for all shared logic

They do not require network access and do not modify the input datasets.

---

## Transition to Analysis: Data Harmonisation Findings

Based on a manual assessment of the outputs generated by the `04_column_value_sample.py` script, several columns require harmonisation before proceeding with quantitative analysis or graph materialisation. The table below summarises the harmonisation needs for the `actor` dataset:

| Column | Needs Harmonisation | Examples | Possible Harmonisations and Checks |
| :--- | :---: | :--- | :--- |
| **`actor_birth`** | **Yes** | `- 0...`<br>`0823-06-13`<br>`1402` | - Remove all characters that are not dashes or numbers.<br>- Flag dates that do not follow the standard `YYYY-MM-DD` convention.<br>- Manage leading zeros (remove or add homogeneously).<br>- Extract certainty metadata based on: (1) extra characters (e.g. dots), (2) precision to the day, (3) to the month, (4) to the year. |
| **`actor_death`** | **Yes** | *See `actor_birth`* | - Same rules as `actor_birth`.<br>- Interpret uncertainty signs: determine if dots (`...`) represent the exact number of missing digits or act as a generic placeholder.<br>- Compare the use of dots with question marks (`?`), treating them separately from other special characters. |
| **`actor_start`** | **Yes** | *See `actor_birth`* | - Same rules as date fields, but appears to follow exclusively the shortened `YYYY` format. |
| **`actor_end`** | **Yes** | *See `actor_birth`* | - Same rules as date fields, again with an apparent shortened `YYYY` format. |
| **`first_year`** | **Yes** | `820`<br>`1402` | - See other year fields. Incidence seems limited to simple years. |
| **`actor_country`** | **Yes** | `<.../countrycodes/aa>`<br>`<.../countries/ag>` | - Verify and map the vocabularies in use (BnF, LoC, or others).<br>- Resolve the URI and append the full textual country name in square brackets (e.g. `[Country Name]`).<br>- Check for other placeholders besides `"NA"`. |
| **`actor_language`** | **Yes** | `<.../iso639-2/fre>` | - Same approach as `actor_country`: resolve the URI and append the full language string in square brackets. |
| **`actor_first_name`** | **Yes** | `Arn.`<br>`Charles-Nicolas-Sigisbert`<br>`Alexandre Roger en religion le P` | - Clean extra characters (e.g. `:`), trailing/leading spaces, or double spaces.<br>- Identify and remove titles, appellatives, and epithets (e.g. introduced by "dit").<br>- Evaluate dash removal to facilitate matching.<br>- Assign a precision score based on punctuated initials.<br>- Identify formulas for unknown authors.<br>- Evaluate words in parentheses and collect name variants. |
| **`actor_last_name`** | **Yes** | *See `actor_first_name`* | - Same rules for spacing, extra characters, and variants specified for `actor_first_name`. |
| **`actor_name`** | **Yes** | *Full name string* | - Adopt the same cleaning rules as first and last names.<br>- Congruence check: does the string match `actor_first_name + actor_last_name`?<br>- Remove quotation marks and identify language tags (e.g. `@fr`).<br>- Logical interpretation of visual placeholders (`***`, `...`, `?`). |
| **`actor_profession`** | **Yes** | `Acteur et auteur dramatique. - A dirigé le théâtre...` | - Treat as free text: remove punctuation and extra characters.<br>- Frequency analysis of exact repetitions.<br>- Tokenise and list single repeated words and their frequencies to evaluate mapping to a controlled vocabulary of professions. |
| **`actor_link_close`** | **Yes** | *Link URI* | - Evaluate base URLs (`http` vs `https` protocols).<br>- Normalise URI format and identify absence placeholders.<br>- Verify value uniqueness within the field.<br>- Cross-match with author identifiers. |
| **`actor_link_exact`** | **Yes** | *Link URI* | - Same URI checks as `link_close`.<br>- Combined analysis of the two fields (`link_exact` and `link_close`) for the same author. |
| **`actor`** | **No** | `<.../ark:/12148/cb10274604z#about>` | - No harmonisation needed: values appear to adhere to the standard base identifier structure. |
| **`entity_type`** | **No** | `<.../foaf/0.1/Person>`<br>`<.../foaf/0.1/Organization>` | - Features only the two expected values. A final check is sufficient to ensure no rows are empty. |
| **`actor_gender`** | **No** | `female`, `male`, `NA` | - Compliant and limited to the 3 predefined options. No textual harmonisation needed. |

The table below summarises the harmonisation needs for the `bibliographic resources` dataset:

| Column | Needs Harmonisation | Examples | Possible Harmonisations and Checks |
| :--- | :---: | :--- | :--- |
| **`author`** | **No** | `<.../cb10001433g#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis (not in harmonisation). |
| **`bnf_id`** | **No** | `30000001` | - Only numerical identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`description`** | **Yes** | `VIII-316-[2] p. ; [3-1 bl.]-220 p.` | - Free text field. Normalise spacing, remove leading/trailing quotation marks.<br>- Evaluate English translation.<br>- Use preliminary analysis (and potentially LLMs) to highlight patterns and understand conventions behind page, volume, and folio numerations. |
| **`digital_copy_link`** | **No** | `<https://gallica.bnf.fr/...>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`edition`** | **No** | `<.../cb30000001q#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`editor`** | **No** | `<.../cb10001604f#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`expression`** | **No** | `<.../cb30000001q#Expression>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`illustrator`** | **No** | `<.../cb10065619p#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`language`** | **Yes** | `<.../iso639-2/afr>` | - Same approach as `actor_language`: resolve the URI and append the full language string in square brackets.<br>- Post-harmonisation: calculate language distribution during the analysis phase. |
| **`place`** | **Yes** | `(S. l. n. d.) In-4°, 1 p. (inconnu)` | - Free text field. Remove extra characters.<br>- Classify entries containing "(inconnu)" and find other expressions denoting uncertainty (e.g. "(S. l. n. d.)").<br>- Pre-cleaning: calculate the frequency of entities containing uncertainty expressions.<br>- Understand conventions for brackets, parentheses, and question marks.<br>- Evaluate LLM usage to determine incidence of this field being used as a generic description field.<br>- Integrate previous work on cleaning location strings. |
| **`publisher`** | **Yes** | `[Henry Sara, ... et Jean Paslé,...]` | - Free text field. Apply the same harmonisation as other free text string fields.<br>- Evaluate if the ID in `publisher_2` identifies the publisher in this free-entry field, or if they refer to two distinct values.<br>- Track keywords and uncertainty indicators (dots, question marks, uncertainty expressions). |
| **`publisher_2`** | **No** | `<.../cb10298296q#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`record_type`** | **No** | `<.../cb119308418>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`subject_topic`** | **No** | `<.../cb100013127#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`title`** | **Yes** | `Déclaration... [le 28 août 1747...]`<br>`[Buste de John Leland...] : [estampe]` | - Free text field. Apply the same observations and interventions as other free entry fields regarding uncertainty, excess characters, and use of square brackets.<br>- Note specific bracketed tags like "[estampe]". |
| **`translator`** | **No** | `<.../cb10006361n#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`work`** | **No** | `<.../cb12008386r#about>` | - Only URI identifiers. Appear regular. Verify presence across all rows during analysis. |
| **`year_first`** | **No** | *YYYY* | - Appears strictly as YYYY. No harmonisation needed. |
| **`year_range`** | **No** | *YYYY or YYYY/YYYY* | - Appears strictly as YYYY or YYYY/YYYY. No harmonisation needed. Verify regularity during analysis phase. |

---

### TO DO: Overall Analysis Module

For the upcoming `03_analysis` module, implement a comprehensive calculation for each field in the dataset that includes:
- The number of unique values.
- The total number of values.
- The percentage of presence (fill rate) of the field across the complete dataset.
- A list of the top 10 most used values.