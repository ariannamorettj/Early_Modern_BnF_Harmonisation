# Fields Requiring Analysis Only (No Harmonisation)

Based on the dataset sampling stage documented in [README.md](file:///Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/02_sampling/README.md), fields have been classified by whether they require cleaning and normalization (harmonisation).

This report lists the fields that **do not require harmonisation** and only need integrity checks and quantitative profiling during the subsequent analysis phase (`03_analysis`).

---

## 1. Actors Dataset (`actor_data`)

In this dataset, three fields do not require any structural or textual harmonisation. They consist of structured identifiers, types, or attributes that already conform to controlled vocabularies.

| Column | Example | Description and Required Analysis |
| :--- | :--- | :--- |
| **`actor`** | `<http://data.bnf.fr/ark:/12148/cb10274604z#about>` | **Main URI identifier for the actor.**<br>- *Status:* Conforms to standard BnF ARK identifier structures.<br>- *Analysis/Verification:* Verify uniqueness and record completeness to ensure no rows contain missing identifiers. |
| **`entity_type`** | `<http://xmlns.com/foaf/0.1/Person>`<br>`<http://xmlns.com/foaf/0.1/Organization>` | **RDF class of the actor.**<br>- *Status:* Contains only the two expected values (Person or Organization).<br>- *Analysis/Verification:* Run a final check to ensure no rows are empty or have invalid types. |
| **`actor_gender`** | `female`, `male`, `NA` | **Gender of the actor.**<br>- *Status:* Clean values limited to three predefined options.<br>- *Analysis/Verification:* Compute the statistical distribution of gender values across the dataset. |

---

## 2. Bibliographic Resources Dataset (`bnf_edition_data`)

The editions dataset is heavily composed of relationship properties represented as URIs (MARC relators) and numerical IDs that are clean and regular at source.

### A. Identifiers and Relationships (URIs and Codes)

All of the following columns contain resource URIs or numerical IDs. They do not require any string cleaning or normalization. The only required task is verifying presence and completeness during analysis.

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

### B. Temporal Columns

These columns contain dates in formats that are natively consistent and regular, unlike the date fields in the `actor` dataset (which exhibit a high degree of variation and uncertainty).

| Column | Example | Description and Verification |
| :--- | :--- | :--- |
| **`year_first`** | `1747` | **First publication year.**<br>- *Status:* Strictly follows the standard `YYYY` format. No harmonisation needed.<br>- *Analysis/Verification:* Compute distribution statistics by century and year; flag potential temporal outliers. |
| **`year_range`** | `1747` or `1747/1748` | **Publication date range.**<br>- *Status:* Strictly follows the `YYYY` or `YYYY/YYYY` format. No harmonisation needed.<br>- *Analysis/Verification:* Verify range syntax and map multi-year publication spans. |

---

## Recommended Analysis Tasks for These Columns

During the `03_analysis` phase, the automated analysis scripts should perform the following computations for these fields:
1. **Fill Rate Calculation:** Percentage of non-null/non-empty rows where the field is populated.
2. **Cardinality & Frequency Distribution:** Count of unique values and overall frequency count.
3. **Top 10 Values Extraction:** Identify the 10 most common values to understand data skew (e.g., dominant languages, genders, or roles).
4. **Consistency Checks:** Ensure semantic alignment (e.g., checking that `year_first` matches the start of `year_range`, and that all URIs conform to the expected domain patterns).
