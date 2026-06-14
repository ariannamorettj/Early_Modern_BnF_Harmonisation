# 03_analysis

This module contains tools and scripts for the quantitative analysis, profiling, and cardinality mapping of the BnF datasets (actors and bibliographic editions) after their initial extraction and unification.

Its main purpose is to support dataset assessment and run diagnostic metrics to identify clean vs. inconsistent fields.

---

## Files in the Module

### `01_field_values.py`

Given a ZIP dataset, a specific actor name value (such as a family name), and a target field, this script filters the rows and counts how many times each distinct value of the target field appears. Useful for examining specific metadata variations (e.g., external links) for a single actor.

### `02_column_unique_values.py`

Scans CSV files inside one or more ZIP datasets to collect all unique values and their occurrence counts for a single selected column. Supports restriction to specific year sets or internal CSV files.

### `03_subset_by_value.py`

Extracts all rows from a ZIP dataset matching a `field = value` condition (e.g., filtering all actors of type `foaf:Person` or all bibliographic entries written in Latin) and writes the complete set to a CSV output file.

### `04_actor_field_cardinality.py`

Reads the actors ZIP dataset, groups records by actor URI, and calculates the average number of distinct values per field per actor. This measures variability (cardinality) for each attribute, indicating if a field is single-valued (e.g., gender, class) or multi-valued (e.g., external links).

### `05_dataset_profiler.py`

Performs a comprehensive dataset profiling for each field across a ZIP dataset. Computes the total number of non-empty values, number of unique values, fill rate percentage (presence rate), and extracts a frequency-sorted list of the top 10 most common values.

> [!NOTE]
> **Null Value Handling:** All metrics computed by `05_dataset_profiler.py` (total values, unique values, top 10 list) exclude null/missing entries. Null values include empty strings (`""`), missing values (`None`), and common placeholders/sentinels (e.g., `NA`, `N/A`, `null`, `None`). The proportion of these excluded null values determines the remaining portion of the `fill_rate_percent`.

---

## Subfolders & Supporting Toolkits

- **`03_analysis/actors/`**: Focuses on actor-level statistics and field cardinality.
  - `actors_one_to_may_fields_analysis.py`: Computes average tuple counts per field across all role JSON files.
  - `actors_names_to_many_fields_analysis.py`: Computes average values per field grouped by name.
  - **`names/`**: The Names Analysis Toolkit, containing rule-based (`detect_real_names.py`) and AI-enhanced (`enhanced_detect_names.py`) components to filter and classify personal names, identify noise, and generate manual review tables.
- **`03_analysis/bib_resources/`**:
  - `dataset_overview.py`: Iteratively scans raw BnF folders to log unique column headers.
  - `unique_values_per_field.py`: Collects distinct values for selected agent fields to support controlled vocabulary creation.

---

## Fields Requiring Analysis Only (No Harmonisation)

Below is the classification of columns in both datasets that do not require cleaning, normalisation, or structural harmonization, based on the findings from the sampling stage (`02_sampling`). These fields only require quantitative profiling and integrity validation.

### 1. Actors Dataset (`actor_data`)

| Column | Example | Description and Required Analysis |
| :--- | :--- | :--- |
| **`actor`** | `<http://data.bnf.fr/ark:/12148/cb10274604z#about>` | **Main URI identifier for the actor.**<br>- *Status:* Conforms to standard BnF ARK identifier structures.<br>- *Analysis/Verification:* Verify uniqueness and record completeness to ensure no rows contain missing identifiers. |
| **`entity_type`** | `<http://xmlns.com/foaf/0.1/Person>`<br>`<http://xmlns.com/foaf/0.1/Organization>` | **RDF class of the actor.**<br>- *Status:* Contains only the two expected values (Person or Organization).<br>- *Analysis/Verification:* Run a final check to ensure no rows are empty or have invalid types. |
| **`actor_gender`** | `female`, `male`, `NA` | **Gender of the actor.**<br>- *Status:* Clean values limited to three predefined options.<br>- *Analysis/Verification:* Compute the statistical distribution of gender values across the dataset. |

### 2. Bibliographic Resources Dataset (`bnf_edition_data`)

#### A. Identifiers and Relationships (URIs and Codes)

| Column | Example | Resource Type / Description |
| :--- | :--- | :--- |
| **`edition`** | `<http://data.bnf.fr/ark:/12148/cb30000001q#about>` | BnF URI of the specific edition/manifestation resource. |
| **`bnf_id`** | `30000001` | FRBNF numerical identifier (clean and regular). |
| **`expression`** | `<http://data.bnf.fr/ark:/12148/cb30000001q#Expression>` | BnF URI of the related expression. |
| **`work`** | `<http://data.bnf.fr/ark:/12148/cb12008386r#about>` | BnF URI of the work manifested. |
| **`author`** | `<http://data.bnf.fr/ark:/12148/cb10001433g#about>` | URI of the author agent (`marcrel:aut` relationship). |
| **`editor`** | `<http://data.bnf.fr/ark:/12148/cb10001604f#about>` | URI of the editor agent (`marcrel:edt` relationship). |
| **`translator`** | `<http://data.bnf.fr/ark:/12148/cb10006361n#about>` | URI of the translator agent (`marcrel:trl` relationship). |
| **`illustrator`** | `<http://data.bnf.fr/ark:/12148/cb10065619p#about>` | URI of the illustrator agent (`marcrel:ill` relationship). |
| **`publisher_2`** | `<http://data.bnf.fr/ark:/12148/cb10298296q#about>` | URI of the commercial publisher agent (`marcrel:pbl` relationship). |
| **`subject_topic`** | `<http://data.bnf.fr/ark:/12148/cb100013127#about>` | URI of the subject topic. |
| **`record_type`** | `<http://data.bnf.fr/ark:/12148/cb119308418>` | URI of the record type. |
| **`digital_copy_link`** | `<https://gallica.bnf.fr/ark:/12148/bpt6k102030u>` | Direct link to the digital surrogate (Gallica/BnF). |

> _Note: For all the URI columns listed above, the analysis should focus on checking the fill rate (percentage of presence) and identifying any unexpected domain formats._

#### B. Temporal Columns

| Column | Example | Description and Verification |
| :--- | :--- | :--- |
| **`year_first`** | `1747` | **First publication year.**<br>- *Status:* Strictly follows the standard `YYYY` format. No harmonisation needed.<br>- *Analysis/Verification:* Compute distribution statistics by century and year; flag potential temporal outliers. |
| **`year_range`** | `1747` or `1747/1748` | **Publication date range.**<br>- *Status:* Strictly follows the `YYYY` or `YYYY/YYYY` format. No harmonisation needed.<br>- *Analysis/Verification:* Verify range syntax and map multi-year publication spans. |

---

## Recommended Analysis Metrics

For all fields listed in this document, the analysis code should compute:
1. **Fill Rate (Presence %)**: Proportion of rows where the field is populated.
2. **Distinct Value Count**: Total number of unique values.
3. **Top 10 Most Common Values**: Frequency ranking of dominant entities.
4. **Data Conformity Checks**: Verify syntax (e.g., standard ARK formats for URI properties).
