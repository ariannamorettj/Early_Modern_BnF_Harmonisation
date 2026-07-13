Here is the English translation of the report:

---

# Detailed Report — Module 04\_harmonisation\_and\_evaluation

**Path:** `/Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/04_harmonisation_and_evaluation/`
**Report date:** 2026-06-22

---

## 1. Purpose and Position in the Pipeline

Module 04 is the core of the data cleaning and quality control pipeline. It receives as input the raw datasets produced by the acquisition stage (module 01) and sampled/analysed in modules 02 and 03, and produces harmonised datasets that will subsequently be optimised (05), enriched with external authority records (06), and materialised as an RDF graph (07).

The module is divided into two symmetric sub-modules operating in cascade:

```
01_data_retrieval (raw CSV)
        │
        ▼
04_harmonisation_and_evaluation/
    ├── 01_harmonisation/         ← Field-level normalisation
    │       [per field]
    │           ├── 01_heuristic_rules/   ← Deterministic approach (regex, lookup, parsing)
    │           └── 02_llm_based/         ← LLM approach (low-confidence residuals)
    │
    └── 02_evaluation/            ← QA on the output of each normaliser
            [per field]
            └── <field>_evaluation.py    ← Child class of Evaluation

        Output: <field>_summary.csv | <field>_warnings.csv | <field>_errors.csv
```

**General principle:**

1. The heuristic normaliser is run first on all values.
2. Its output is evaluated by the corresponding evaluator.
3. Cases with low or medium confidence, or unresolved by the heuristic normaliser, are forwarded to the LLM normaliser.
4. The LLM output follows the same schema as the heuristic output, with the additional column `llm_explanation`.

---

## 2. Output Conventions Common to All Normalisers

Each normalisation script produces a CSV with the following core schema:

| Column | Description |
|---|---|
| `<id_column>` | Primary key URI of the record (e.g. `actor_uri`, `edition_uri`) |
| `<field>_original` | Raw unmodified value |
| `<field>_harmonised` | Normalised value |
| `correction_type` | Label of the rule/approach that produced the correction |
| `confidence` | `high` / `medium` / `low` |
| `llm_explanation` | (LLM output only) Textual justification from the model |

---

## 3. Sub-module 01\_harmonisation — Fields and Status

### 3.1 actor\_name/ — Actor Names

**Dataset:** actor\_data
**Fields:** `actor_name`, `actor_first_name`, `actor_last_name`
**Overall status:** 🔄 In progress

**Anomalies identified (from 03\_analysis)**

| Category | Examples |
|---|---|
| Initials-only | `M D`, `G.`, `M. B. L.` |
| Abbreviations | `Th.`, `J.` |
| Embedded titles/roles | `Veuve de`, `Sieur de`, `Abbé`, `Chevalier` |
| Aliases/alternative names | `dit le`, `alias`, `detto il`, `surnommé` |
| Multiple values in cell | `Pietro and Giovanni`, `Martinus Et` |
| Encoding / noise | `[Dumas]`, `(Voltaire)`, `***`, `null`, `nan` |
| Roman numerals | `Julien I`, `Louis XIV` |

**01\_heuristic\_rules/**

| File | Status | Function |
|---|---|---|
| `name_normaliser.py` | 📋 to be completed | Main normaliser: regex, particle handling, bracket stripping, alias detection → CSV |
| `actors_id_matching.py` | ✅ Implemented | Groups rows by actor URI (`actor` column); for each repeated URI, aggregates distinct values per field with counts → JSON in `data/actors_matched_ids/` |
| `actors_name_matching.py` | ✅ Implemented | Same logic as `actors_id_matching.py` but keyed on normalised name (case/punctuation insensitive) → JSON in `data/actors_matched_names/` |
| `actors_deduplication.py` | 📋 Placeholder | Deduplication based on results from the two preceding matching scripts |
| `name_correction_dict.json` | 📋 to be completed | Lookup dictionary: erroneous string → correct form |

**`actors_id_matching.py` — Detailed implementation:**

- Reads CSVs from `data/unified_agents/`
- Relevant columns considered: `year`, `actor`, `actor_birth`, `actor_country`, `actor_death`, `actor_end`, `actor_gender`, `actor_language`, `actor_link_close`, `actor_link_exact`, `actor_name`, `actor_profession`, `actor_start`
- Identifies URIs appearing more than once
- For each repeated URI: for each other relevant column, computes the frequency of each distinct value (sorted by count descending, then value ascending for determinism)
- Ignores empty/whitespace-only values
- Output: `actors_<role>.json` for each role

**Implementation plan for `name_normaliser.py`:**

1. Strip null markers (`***`, `null`, `nan`) → flag `MISSING`
2. Remove wrapping brackets/separators → extract inner value
3. Split multiple values → flag `multi_value` or split
4. Remove embedded titles/roles → extract clean name
5. Handle initials → flag or expand via lookup dict

**02\_llm\_based/**

| File | Status | Function |
|---|---|---|
| `llm_name_normaliser.py` | 📋 to be completed | Filters rows with confidence ≠ `high` from heuristic output → calls LLM → writes final CSV |
| `prompt_templates.py` | 📋 to be completed | Structured prompt templates for `actor_name`, `actor_first_name`, `actor_last_name` |
| `llm_responses_cache/` | 📋 to be completed | JSON cache of LLM responses (avoids re-querying) |

**LLM flow (once implemented):**

1. Load heuristic output
2. Filter rows where `confidence != 'high'`
3. Build structured prompt per row (raw value + warning/error labels + context: actor URI, year)
4. Call LLM API; parse JSON response: `{"harmonised": str, "confidence": str, "explanation": str}`
5. Light post-validation (regex check) on the returned value
6. Write `actor_name_harmonised_llm.csv`

---

### 3.2 actor\_dates/ — Actor Dates

**Dataset:** actor\_data
**Fields:** `actor_birth`, `actor_death`, `actor_start`, `actor_end`
**Overall status:** 📋 Planned

**Target output format:** EDTF (Extended Date/Time Format, extended ISO 8601)

| EDTF Format | Example |
|---|---|
| Exact year | `1750` |
| Approximate year | `1750~` |
| Uncertain year | `1750?` |
| Range | `1700/1800` |
| Partial decade/century | `17XX` |

**Categories of anomalies to handle**

| Category | Examples |
|---|---|
| Dates with qualifiers | `ca. 1750`, `vers 1720`, `ante 1700`, `après 1700` |
| Century-level expressions | `18th century`, `XVIIIe siècle`, `début XIXe` |
| Decade-level expressions | `1750s`, `années 1750` |
| Uncertain/qualified | `1750?`, `[1750]`, `(1750)`, `1750 environ` |
| Ranges | `1750-1800`, `1750/1800` |
| Non-parseable | `actif au XVIIIe`, `flourished c.1700`, `***`, empty strings |

**01\_heuristic\_rules/**

`dates_normaliser.py` — Placeholder/to be completed

Planned functions:

- `detect_date_format(raw_value)` → classifies into: `exact_year`, `approximate`, `uncertain`, `century`, `decade`, `range`, `qualified_activity`, `non_parseable`
- `normalise_date(raw_value)` → converts to EDTF, returns `{harmonised, format_detected, confidence}`
- `run(input_path, output_dir)` → processes full CSV/ZIP

Output schema: `actor_uri | field | date_original | date_harmonised | date_format_detected | confidence`

**02\_llm\_based/**

`llm_dates_normaliser.py` — Placeholder/to be completed

Target: values classified as `non_parseable` or with `low` confidence by the heuristic normaliser. The LLM must:

1. Identify the type of temporal expression
2. Extract year(s) or century
3. Apply EDTF modifiers for approximation/uncertainty
4. Return a structured JSON response

---

### 3.3 external\_links/ — External Authority Links

**Dataset:** actor\_data
**Fields:** `actor_link_close`, `actor_link_exact`
**Overall status:** 📋 Planned

**Anomalies to handle**

| Category | Examples |
|---|---|
| Mixed URIs (http/https) | `http://viaf.org/viaf/12345` vs `https://viaf.org/viaf/12345` |
| www / no-www variants | `www.viaf.org` vs `viaf.org` |
| Non-URIs (free text, local IDs, partial paths) | — |
| Deprecated/redirected URIs | Old merged VIAF clusters |
| Multi-value in cell | URIs separated by `;` or `\|` |

**01\_heuristic\_rules/**

`external_links_normaliser.py` — Placeholder/to be completed

Implementation plan:

1. Parse URIs with `urllib.parse`
2. Schema normalisation: `http` → `https` for known authorities
3. `www.` prefix normalisation (removal if known authority uses bare domain)
4. Detection and splitting of multi-value cells
5. Flagging non-URI values for manual review
6. Resolution of deprecated URI patterns via lookup table

Output schema: `actor_uri | field | link_original | link_harmonised | authority | correction_type | confidence`

---

### 3.4 publication\_place/ — Publication Place

**Dataset:** bnf\_edition\_data
**Field:** `place` (from `rdam:P30279`)
**Overall status:** ✅ Approach 02 (`02_tgn_lookup`) complete

This is the most advanced field in the module, with a fully implemented approach.

**01\_heuristic\_rules/ — Approach 01 (empty folder)**
The pure heuristic approach has been superseded by the TGN lookup approach.

**02\_tgn\_lookup/ — TGN Approach (✅ Complete)**

Implementations: R (`bnf_place_harmonisation.R`) and Python (`bnf_place_harmonisation.py`)

Data source: Getty Thesaurus of Geographic Names (TGN) — ODC Attribution License.

Final output: `data/data_final/bnf_publication_place.csv`

**Output CSV schema:**

| Column | Type | Description |
|---|---|---|
| `edition` | URI | Unique BnF record identifier |
| `place_original` | string | Raw value from `rdam:P30279` |
| `tgn_id` | ID | TGN identifier of the place |
| `publication_place` | string | Name of the publication place (city level) |
| `publication_country` | string | Country name (e.g. `France`, `Great Britain`) |
| `longitude` | float | Longitude of the place |
| `latitude` | float | Latitude of the place |
| `uncertainty_expressions_brackets` | boolean | `TRUE` if the original value contains `[...]` |
| `uncertainty_expressions_question_mark` | boolean | `TRUE` if the original value contains `?` |
| `uncertainty_expressions_parentheses` | boolean | `TRUE` if the original value contains `(...)` |

**Intermediate working files (`data/data_work/`):**

- `bnf_country_harmonisation_table.csv` — country-level harmonisation table
- `bnf_place_name_harmonisation_table_final.csv` — final place name normalisation table
- `bnf_unique_raw_country_values.csv` — unique raw values of country fields

---

### 3.5 language/ — Language

**Dataset:** bnf\_edition\_data
**Field:** `language` (language of the bibliographic Expression)
**Overall status:** 📋 Planned

**Target output format:** Three-letter ISO 639-2 codes (BnF standard)

**Anomalies to handle**

| Category | Examples |
|---|---|
| Language names in free text (multilingual) | `français`, `latin`, `French`, `Latein`, `italiano` |
| ISO codes already present (but mixed) | `fre`, `lat`, `fr`, `la` (ISO 639-1 and 639-2) |
| Multi-language expressions | `Latin et français`, `en français et en latin` |
| Archaic languages or dialects | `vieux français`, `moyen français`, `occitan`, `picard` |
| Placeholders/encoding errors | `???`, `inconnu`, `unknown`, empty strings |

**Target mappings:**

| Raw | ISO 639-2 |
|---|---|
| `français` | `fre` |
| `Latin` | `lat` |
| `greek` | `grc` |
| `vieux français` | `fro` |
| `occitan` | `oci` |

**01\_heuristic\_rules/**

`language_normaliser.py` — Placeholder/to be completed

Implementation plan:

1. Build `language_lookup.json` (raw string → ISO 639-2 code) using the most frequent values (from 03\_analysis profiling)
2. Apply the lookup (case-insensitive, stripped)
3. Detect multi-language expressions and split them
4. Flag unmappable strings for LLM or manual review

Output schema: `edition_uri | language_original | language_harmonised | correction_type | confidence`

---

### 3.6 publisher/ — Publisher

**Dataset:** bnf\_edition\_data
**Field:** `publisher_1` (free text; distinct from `publisher_2` which is a URI)
**Overall status:** 📋 Planned

**Anomalies to handle**

| Category | Examples |
|---|---|
| Spelling variants of the same publisher | `Imprimerie royale`, `Impr. royale`, `Impr. Royale` |
| Abbreviations and partial names | `Impr.`, `Lib.`, `s.n.` (sine nomine) |
| Embedded geographic information | `Chaignieau aîné (Paris)`, `Renard, Bordeaux` |
| Embedded date spans | `J. Smith [1750-1780]` |
| Multiple publishers concatenated | `Baudouin et Renard`, `Smith ; Jones` |
| Non-publisher content (notes, print descriptions) | — |

**01\_heuristic\_rules/**

`publisher_normaliser.py` — Placeholder/to be completed

Implementation plan:

1. Detection and normalisation of known abbreviations via lookup dict (`publisher_abbreviations.json`)
2. Strip embedded geographic information (city/country in parentheses)
3. Detection and flagging of multi-publisher cells for splitting
4. Identification of *sine nomine* and null-equivalent patterns
5. Fuzzy string matching (e.g. RapidFuzz) to cluster spelling variants into canonical names

Output schema: `edition_uri | publisher_original | publisher_harmonised | correction_type | confidence`

**02\_llm\_based/**
Folder present but content to be defined after the heuristic approach is implemented.

---

## 4. Sub-module 02\_evaluation — QA Evaluation System

### 4.1 Architecture

The evaluation system is built on an abstract base class from which all field-specific evaluators inherit.

```
Evaluation (evaluation_base.py)          — abstract base class
├── PersonNameEvaluation                 — actor_name_evaluation.py    ✅ Complete
├── ActorDatesEvaluation                 — actor_dates_evaluation.py   🔄 Skeleton
├── ExternalLinksEvaluation              — external_links_evaluation.py 🔄 Skeleton
├── PublicationPlaceEvaluation           — publication_place_evaluation.py 🔄 Skeleton
├── PublisherEvaluation                  — publisher_evaluation.py     🔄 Skeleton
└── LanguageEvaluation                   — language_evaluation.py      🔄 Skeleton

run_evaluation.py                        — CLI Dispatcher ✅ Complete
__init__.py                              — Package with all exports ✅ Complete
input_harmonising_dicts/                 — JSON configuration dictionaries
output_reports/                          — Evaluator output directory
names_with_multiple_ids.py               — Utility: actors with > 1 ID ✅
```

---

### 4.2 Base Class Evaluation — `evaluation_base.py`

**Responsibilities**

- CSV/ZIP reading (native support for compressed archives)
- Row-by-row iteration with progress bar (`tqdm`)
- Warning and error counting and aggregation
- Writing the three output files

**Constructor**

```python
Evaluation(config: dict, csv_filepath: str, field_name: Optional[str] = None)
```

- `config`: dictionary with keys `field`, `warning` (list of labels), `error` (list of labels or `[label, pattern]`)
- `csv_filepath`: path to CSV or ZIP
- `field_name`: column name; overrides `config["field"]` if provided

**Method to implement in child classes**

```python
def evaluate_value(self, value: Optional[str]) -> Tuple[List[str], Dict[str, str]]:
    # Returns:
    #   warnings: list of warning labels
    #   errors: dict { label: substitution_value }
```

**Execution flow of the `run()` method**

1. Iterates over CSVs (single file or all CSVs within a ZIP)
2. For each file: reads header, identifies index of the target column
3. For each row: calls `evaluate_value(value)`
4. Accumulates:
   - `case_counter`: `Counter[(label, type)]` → count
   - `warnings_detail`: `{value → Counter[label → count]}`
   - `errors_detail`: `{value → {label → {subst, count}}}`
5. Writes the three output CSVs

**The three output CSVs**

`<field>_summary.csv`

```
case | case_type | total_occurrences | percentage_on_total_entities | files_considered
```
One row per `(label, type)` found; `files_considered` reported only in the first row.

`<field>_warnings.csv`

```
value | case | occurrences
```
One row per original value that generated at least one warning; `case`: label(s) separated by `;`.

`<field>_errors.csv`

```
value | case | substitution_value | occurrences
```
One row per original value that generated at least one error; `substitution_value`: suggested value (empty string if unavailable).

---

### 4.3 PersonNameEvaluation — `actor_name_evaluation.py`

**Status:** ✅ Fully implemented

Works on fields `actor_name`, `actor_first_name`, `actor_last_name`. Configuration loaded from `input_harmonising_dicts/person_names.json`.

**Warnings detected (13 categories)**

| Warning label | Detection logic |
|---|---|
| `initials only` | ≥2 tokens, every significant token ≤2 characters, ignoring particles (`de`, `di`, `von`, `van`…) |
| `dotted initials only` | Tokens like `M.`, `G.`, `L.J.`, `M. B. L.` (dotted initials only) |
| `undefined number of undeciphered characters` | Presence of `...` (3+ consecutive dots) |
| `possibly missing name or surname` | Single-token value (not applied to `first_name`/`last_name`) |
| `possibly contains multiple values` | Internal conjunction (`et`, `and`, `und`, `y`, `e`); excluding Spanish compound patterns like `Fernando de Toledo y Pimentel` |
| `probably contains alternative names` | Presence of `alias`, `dit le`, `detto il`, `surnommé`, `also known as`, etc. (multilingual) |
| `possibly contains an article (...)` | Last token is an article (`le`, `la`, `il`, `the`, `der`…) |
| `possibly contains a preposition (...)` | Last token is a preposition (`de`, `van`, `von`, `of`…) |
| `possible abbreviation` | Single token of 2–3 letters + dot: `Th.` |
| `contain possible personal title or role` | Token is a noble title/role: `veuve`, `sieur`, `abbé`, `comte`, `chevalier`, `dame`, etc.; or bigram/trigram: `veuve de`, `sieur de`, `son of`, etc. |
| `possibly contains only part of multiple values` | Conjunction as last token: `Martinus And`, `Mario e` |
| `possibly contains a Roman numeral (...)` | Last token is a Roman numeral: `Julien I`, `Louis XIV` |
| `contains also dotted initials` | Sequence of dotted initials + normal words in the same string |

**Errors detected (5 categories)**

| Error label | Logic | Substitution |
|---|---|---|
| `missing value` | Value = `***` | Empty string |
| `contains number (non-Roman)` | Contains Arabic digits (Roman numerals excluded) | Empty string |
| `contains non-alphanumerical characters (excluding * and .)` | Non-alphanumeric characters except `*` and `.` | Empty string |
| `contains null marker` | Presence of `null` or `nan` as a token | Empty string |
| `contains brackets or surrounding separators` | Presence of `[]`, `()`, `{}`, `""`, `<>`, `//` | Inner value extracted (`_strip_wrapping_punctuation()`) |

**Important note:** For `actor_first_name` and `actor_last_name`, the warning `possibly missing name or surname` is disabled (a single token is normal). The warning `initials only` is suppressed if `dotted initials only` has already been emitted.

---

### 4.4 ActorDatesEvaluation — `actor_dates_evaluation.py`

**Status:** 🔄 Skeleton — awaiting output schema from `dates_normaliser`

Validates that harmonised values are valid EDTF strings.

**Warnings (detected on EDTF qualifiers)**

- `approximate_date` — presence of `~`
- `uncertain_date` — presence of `?`
- `date_range` — presence of `/`
- `century_level` — presence of `XX`
- `decade_level` — (to be fully implemented)

**Errors**

- `missing_value` — null/empty value
- `non_edtf_format` — does not match the base EDTF pattern: `^-?\d{4}[X~?%]?(?:/(-?\d{4}[X~?%]?))?$`
- `non_parseable` — (to be fully implemented)

---

### 4.5 ExternalLinksEvaluation — `external_links_evaluation.py`

**Status:** 🔄 Skeleton

Known authorities (`KNOWN_AUTHORITY_DOMAINS`): `viaf.org`, `www.wikidata.org`, `id.loc.gov`, `isni.org`, `www.isni.org`, `dbpedia.org`, `data.bnf.fr`, `d-nb.info`, `catalogue.bnf.fr`

Authorities requiring HTTPS (`HTTPS_ONLY_AUTHORITIES`): `www.wikidata.org`, `viaf.org`, `isni.org`, `www.isni.org`

**Warnings**

- `insecure_http_for_known_authority` — URI uses `http://` for an authority in `HTTPS_ONLY_AUTHORITIES`
- `unknown_authority_domain` — domain not among known authorities
- `www_prefix_variant` — domain with `www.` when the bare-domain variant is the canonical one

**Errors**

- `missing_value` — null/empty value
- `not_a_uri` — does not match pattern `^https?://\S+$`
- `multi_value_not_split` — presence of `;` or `|` (multi-value cells not yet split)

Implemented logic: uses `urllib.parse.urlparse` to extract scheme and domain.

---

### 4.6 PublicationPlaceEvaluation — `publication_place_evaluation.py`

**Status:** 🔄 Skeleton

Validates the output of the `02_tgn_lookup` harmoniser against the schema: `edition | place_original | tgn_id | publication_place | publication_country | longitude | latitude | uncertainty_*`

**Warnings**

- `uncertainty_bracket` — residual presence of `[` or `]` in the normalised value
- `uncertainty_question_mark` — residual presence of `?`
- `uncertainty_parentheses` — residual presence of `(` or `)`
- `missing_coordinates` — missing coordinates

**Errors**

- `missing_tgn_id` — no TGN ID assigned
- `missing_publication_place` — empty city name
- `missing_publication_country` — empty country name
- `missing_value` — null/empty value

**Architectural note:** For complete row-level validation (TGN ID + coordinates + city + country together), `run()` must be overridden to pass additional columns to `evaluate_value()`. The current implementation validates only the `publication_place` field in isolation.

---

### 4.7 PublisherEvaluation — `publisher_evaluation.py`

**Status:** 🔄 Skeleton

**Warnings**

- `sine_nomine` — patterns `s.n.`, `sine nomine`, `sans nom`, `ohne Verlag`, etc. (multilingual)
- `residual_abbreviation` — unexpanded abbreviations: `Impr.`, `Lib.`, `Éd.`, `Ed.`
- `residual_location_in_name` — residual geographic information in parentheses
- `low_confidence_correction` — (to be implemented)

**Errors**

- `missing_value` — null/empty value
- `multi_value_not_split` — presence of `;`
- `non_alphanumeric_noise` — non-alphanumeric characters except `.`, `,`, `-`, `'`, `()`, `&`

---

### 4.8 LanguageEvaluation — `language_evaluation.py`

**Status:** 🔄 Skeleton (basic logic implemented)

Validates that the harmonised value is a valid ISO 639-2 code. The set of known codes is currently a hardcoded subset; to be replaced with a complete `language_lookup.json` file.

**Special codes handled:**

- `und` — undetermined
- `mul` — multiple languages
- `zxx` — no linguistic content

**Warnings**

- `multi_language_value` — presence of `;` or `,` in the value (multi-language expressions)
- `archaic_or_dialectal_language` — codes `fro`, `frm`, `pro`, `oci` (Old French, Middle French, Provençal, Occitan)
- `low_confidence_mapping` — valid 3-letter format but not in the known set

**Errors**

- `missing_value` — null/empty value
- `not_iso_639_2_format` — does not match regex `^[a-z]{3}$`
- `unknown_iso_code` — (to be fully implemented)
- `non_parseable_language` — (to be implemented)

---

### 4.9 Dispatcher `run_evaluation.py` — ✅ Complete

CLI entry point for running any evaluator.

```bash
# Syntax
python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    <input_file> \
    --column <column_name> \
    [--output_dir <dir>] \
    [--config <json_config_path>]
```

**Routing by column name:**

| Accepted columns | Evaluator |
|---|---|
| `actor_name`, `actor_first_name`, `actor_last_name` | `PersonNameEvaluation` |
| `actor_birth`, `actor_death`, `actor_start`, `actor_end`, `date_harmonised` | `ActorDatesEvaluation` |
| `actor_link_close`, `actor_link_exact`, `link_harmonised` | `ExternalLinksEvaluation` |
| `publication_place`, `place_original` | `PublicationPlaceEvaluation` |
| `publisher_1`, `publisher_harmonised` | `PublisherEvaluation` |
| `language`, `language_harmonised` | `LanguageEvaluation` |

**Practical examples:**

```bash
# Evaluate actor names on a raw ZIP file
python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    data/actor_data.zip --column actor_name

# Evaluate publication places on harmonised output
python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_final/bnf_publication_place.csv \
    --column publication_place \
    --output_dir 04_harmonisation_and_evaluation/02_evaluation/output_reports/
```

---

## 5. Overall Module Status Table

| Field | Dataset | Heuristic normaliser | LLM normaliser | Evaluator | Notes |
|---|---|---|---|---|---|
| `actor_name`/`first_name`/`last_name` | actor\_data | 📋 to be completed (`name_normaliser.py`) | 📋 to be completed | ✅ Complete (`PersonNameEvaluation`) | Matching scripts implemented |
| `actor_birth`/`death`/`start`/`end` | actor\_data | 📋 to be completed (`dates_normaliser.py`) | 📋 to be completed | 🔄 Skeleton | Target: EDTF |
| `actor_link_close`/`exact` | actor\_data | 📋 to be completed (`external_links_normaliser.py`) | — | 🔄 Skeleton | No LLM approach planned |
| `place` | bnf\_edition\_data | — (empty) | — | 🔄 Skeleton | TGN approach implemented |
| `place` (TGN lookup) | bnf\_edition\_data | ✅ Complete (`bnf_place_harmonisation.py`/`.R`) | — | 🔄 Skeleton | Output ready in `bnf_publication_place.csv` |
| `language` | bnf\_edition\_data | 📋 to be completed (`language_normaliser.py`) | — | 🔄 Skeleton (basic logic) | Lookup dict to be built |
| `publisher_1` | bnf\_edition\_data | 📋 to be completed (`publisher_normaliser.py`) | 📋 to be completed (folder present) | 🔄 Skeleton | Fuzzy matching planned |

**Fields NOT requiring harmonisation (documented in README):**

- `actor_data`: `actor` (URI), `entity_type`, `actor_gender`
- `bnf_edition_data`: `edition`, `bnf_id`, `expression`, `work`, `author`, `editor`, `translator`, `illustrator`, `publisher_2`, `subject_topic`, `record_type`, `digital_copy_link`, `year_first`, `year_range`

---

## 6. Complete Data Flow of Module 04

```
Input:
  actor_data.zip / bnf_edition_data_raw.zip
          │
          ▼
  01_harmonisation/<field>/01_heuristic_rules/<field>_normaliser.py
          │
          │  <field>_harmonised.csv
          │  (actor_uri | <field>_original | <field>_harmonised | correction_type | confidence)
          │
          ├──────────────────────────────────────────────────┐
          ▼                                                  ▼
  02_evaluation/run_evaluation.py                01_harmonisation/<field>/02_llm_based/
  (for rows with confidence=high)                (for rows with confidence ≠ high)
          │                                                  │
          ▼                                                  ▼
  output_reports/                           <field>_harmonised_llm.csv
  ├── <field>_summary.csv                   (+ llm_explanation column)
  ├── <field>_warnings.csv
  └── <field>_errors.csv
```