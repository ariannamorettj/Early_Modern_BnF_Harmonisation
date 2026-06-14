# 01_harmonisation

This module contains the harmonisation scripts for all fields in the BnF dataset
that require cleaning, normalisation, or structural transformation.

Each field has its own subfolder, which in turn contains separate subfolders
for each approach attempted. This multi-level structure supports experimenting
with more than one normalisation strategy per field.

---

## Fields and Subfolders

| Subfolder | Dataset | Field(s) | Status |
|-----------|---------|----------|--------|
| [`actor_name/`](actor_name/) | `actor_data` | `actor_name`, `actor_first_name`, `actor_last_name` | 🔄 In progress |
| [`actor_dates/`](actor_dates/) | `actor_data` | `actor_birth`, `actor_death`, `actor_start`, `actor_end` | 📋 Planned |
| [`external_links/`](external_links/) | `actor_data` | `actor_link_close`, `actor_link_exact` | 📋 Planned |
| [`publication_place/`](publication_place/) | `bnf_edition_data` | `publication_place` (`rdam:P30279`) | ✅ Approach 02 complete |
| [`publisher/`](publisher/) | `bnf_edition_data` | `publisher_1` | 📋 Planned |
| [`language/`](language/) | `bnf_edition_data` | `language` | 📋 Planned |

> **Legend:** ✅ Complete · 🔄 In progress · 📋 Planned (placeholder files present)

---

## Folder Structure Convention

Each field folder follows the same pattern:

```
<field_name>/
├── 01_heuristic_rules/     ← Deterministic approach: regex, lookup dicts, char substitution
│   ├── README.md
│   ├── <field>_normaliser.py   ← Main normalisation script [TODO or implemented]
│   └── ...
└── 02_llm_based/           ← LLM-assisted approach for ambiguous residual cases
    ├── README.md
    ├── llm_<field>_normaliser.py   [TODO]
    └── ...
```

The heuristic approach should always be run first. Its output is consumed by the
LLM-based approach, which targets only the low-confidence or unresolved cases.

---

## Output Format Convention

All normaliser scripts produce a CSV with the following core columns:

| Column | Description |
|--------|-------------|
| `<id_column>` | The primary key URI for the record (e.g. `actor_uri`, `edition_uri`) |
| `<field>_original` | The raw, unmodified value from the source dataset |
| `<field>_harmonised` | The corrected/normalised value |
| `correction_type` | Label of the rule or approach that produced the correction |
| `confidence` | `high` / `medium` / `low` — certainty of the correction |

LLM-based outputs additionally include:
| `llm_explanation` | Free-text justification from the LLM |

---

## Fields NOT Requiring Harmonisation

The following fields were determined to be already clean and do not have a subfolder here.
See [`03_analysis/no_harmonisation_fields_report.md`](../../03_analysis/no_harmonisation_fields_report.md)
for the full classification.

**actor_data:** `actor` (URI), `entity_type`, `actor_gender`

**bnf_edition_data:** `edition` (URI), `bnf_id`, `expression`, `work`, `author`, `editor`,
`translator`, `illustrator`, `publisher_2`, `subject_topic`, `record_type`,
`digital_copy_link`, `year_first`, `year_range`
