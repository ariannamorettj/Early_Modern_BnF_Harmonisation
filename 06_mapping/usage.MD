# 06 — External Mapping & Enrichment — Usage & Technical Notes

## 1. Module overview

Module 06 bridges the BnF dataset with three external authoritative catalogues:

| Script | Target | Method |
|--------|--------|--------|
| `01_map_viaf.py` | VIAF | ID lookup → name-based SRU search |
| `02_map_wikidata.py` | Wikidata | QID lookup → SPARQL label search |
| `03_map_estc_ecco.py` | ESTC / ECCO | Heuristic field matching → LLM translation check |
| `04_merge_mappings.py` | — | Joins all mapping outputs into enriched datasets |

---

## 2. Directory structure

```
06_mapping/
├── 01_map_viaf.py
├── 02_map_wikidata.py
├── 03_map_estc_ecco.py
├── 04_merge_mappings.py
├── usage.MD
│
├── output/
│   ├── viaf_mapping.csv
│   ├── wikidata_mapping.csv
│   ├── estc_mapping.csv
│   ├── bnf_actors_enriched.csv       ← final enriched actor dataset
│   └── bnf_editions_enriched.csv     ← final enriched edition dataset
│
└── report/
    ├── viaf_mapping_report.json
    ├── wikidata_mapping_report.json
    ├── estc_mapping_report.json
    └── merge_report.json
```

---

## 3. Execution order

```bash
# Step 1 — VIAF
python 06_mapping/01_map_viaf.py

# Step 2 — Wikidata (uses VIAF mapping as additional QID source)
python 06_mapping/02_map_wikidata.py \
    --viaf-mapping 06_mapping/output/viaf_mapping.csv

# Step 3 — ESTC/ECCO
# Set ANTHROPIC_API_KEY to enable LLM translation fallback (optional)
export ANTHROPIC_API_KEY=sk-...
python 06_mapping/03_map_estc_ecco.py \
    --bnf-editions  data/bnf_edition_data/bnf_editions_ready.csv \
    --estc-csv      data/estc/estc_raw_sane.csv

# Step 4 — Merge all
python 06_mapping/04_merge_mappings.py
```

---

## 4. Script 1 — `01_map_viaf.py`

### Inputs
- `05_subset_optimisation/output/bnf_actors_optimised.csv`

### Algorithm
**Pass 1 (ID-based):** VIAF URIs already present in `actor_link_exact` /
`actor_link_close` are extracted. The VIAF REST API
(`https://viaf.org/viaf/{id}/justlinks.json` + `viaf.json`) returns:
- Preferred name (`mainHeadings`)
- Birth / death dates
- Co-referent IDs: Wikidata QID, LC, IdRef

**Pass 2 (name-based):** Actors without a VIAF URI trigger a SRU search
(`https://viaf.org/search`) on `local.personalNames`. The top candidate is
accepted if the Levenshtein similarity ratio ≥ `--threshold` (default 0.85).

### Output fields
`BnF_ID, viaf_id, match_type, viaf_name, birth_date, death_date, wikidata_id, lc_id, idref_id, confidence`

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--input` | `05_subset_optimisation/output/bnf_actors_optimised.csv` | Actor dataset |
| `--output` | `06_mapping/output/viaf_mapping.csv` | Output CSV |
| `--threshold` | `0.85` | Min. name similarity for pass-2 acceptance |
| `--sleep` | `0.4` | Seconds between API calls |

---

## 5. Script 2 — `02_map_wikidata.py`

### Inputs
- `05_subset_optimisation/output/bnf_actors_optimised.csv`
- `06_mapping/output/viaf_mapping.csv` (optional, supplies additional QIDs)

### Algorithm
**Pass 1 (ID-based):** Wikidata QIDs from `actor_link_exact` / `actor_link_close`
or from the VIAF mapping's `wikidata_id` column. The MediaWiki Entity API
(`wbgetentities`) returns labels, birth/death dates, and authority IDs
(BnF ARK P268, VIAF P214, ISNI P213, LC P244).

**Pass 2 (SPARQL label search):** A SPARQL query against the Wikidata Query
Service filters `rdfs:label` in French, optionally constrained by birth year
(±2 years). Top candidate accepted if similarity ≥ `--threshold`.

### Output fields
`BnF_ID, qid, match_type, wikidata_label, birth_date, death_date, bnf_ark, viaf_id, isni, lc_id, confidence`

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--viaf-mapping` | `06_mapping/output/viaf_mapping.csv` | Supplementary QID source |
| `--threshold` | `0.85` | Min. similarity for pass-2 acceptance |
| `--sleep` | `0.5` | Seconds between API calls |

---

## 6. Script 3 — `03_map_estc_ecco.py`

### Inputs
- `data/bnf_edition_data/bnf_editions_ready.csv` — BnF harmonised editions
- `data/estc/estc_raw_sane.csv` — COMHIS ESTC CSV (tab-separated)
  - Expected columns: `estc_id`, `title`, `author`, `year` (or variants),
    `language`
  - Source: COMHIS/estc-data-verified on GitHub (access by agreement with
    the British Library / COMHIS group)

### Algorithm

**Pass 1 (ID bridge):** When a VIAF ID is shared between a BnF actor and an
ESTC author record, a direct year-constrained join is performed.  This pass
is currently scaffolded and requires the ESTC author authority table with
VIAF IDs to be loaded via `--viaf-author-table` (forthcoming).

**Pass 2 (heuristic):**
1. Year filter: only ESTC editions within ±`--year-window` years are candidates.
2. Author similarity ≥ `--author-threshold` (default 0.80).
3. Title similarity ≥ `--title-threshold` (default 0.75).
Both checks must pass; confidence = mean of the two scores.

**Pass 3 (LLM translation check, optional):**
When author similarity passes but title similarity fails AND the two datasets
report different languages, a Claude API call asks whether the BnF title is a
translation of the ESTC title.  Requires `ANTHROPIC_API_KEY` in the
environment; silently skipped if absent.

The LLM prompt:
```
Is the title "<bnf_title>" (language: <bnf_lang>) a translation or equivalent
of "<estc_title>" (language: <estc_lang>)?
Answer ONLY with valid JSON: {"match": true or false, "confidence": 0.0 to 1.0}
```

### Output fields
`BnF_edition_id, estc_id, match_type, confidence, estc_title, estc_author, estc_year, estc_language, bnf_title, bnf_year, bnf_language, notes`

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--author-threshold` | `0.80` | Min. author name similarity |
| `--title-threshold` | `0.75` | Min. title similarity |
| `--llm-threshold` | `0.80` | Min. LLM confidence for pass-3 acceptance |
| `--year-window` | `2` | ±years around BnF publication year |
| `--sleep` | `0.3` | Seconds between calls |

---

## 7. Script 4 — `04_merge_mappings.py`

Joins all three mapping CSVs onto the base actor and edition datasets,
producing two enriched CSVs ready for graph materialisation (module 07).

### Actor enrichment adds columns
`viaf_id, viaf_name, viaf_birth_date, viaf_death_date, mapping_confidence_viaf, qid, wikidata_label, isni, lc_id, bnf_ark_wikidata, mapping_confidence_wikidata`

### Edition enrichment adds columns
`estc_id, estc_title, estc_author, estc_year, estc_language, estc_match_type, estc_confidence`

---

## 8. Notes on ECCO vs ESTC

ECCO (Eighteenth Century Collections Online, Gale) does not expose a public
API or downloadable metadata.  The practical access route is via the ESTC,
which underpins ECCO and is available as open data through COMHIS.

The COMHIS ESTC harmonised CSV (`estc_raw_sane.csv`) is the recommended input
for script 03.  Contact the COMHIS group (University of Helsinki) or consult
`https://github.com/COMHIS/estc-data-verified` for access.

---

## 9. LLM pass — notes for reproducibility

The LLM translation check introduces a non-deterministic element.  To ensure
reproducibility:
- All LLM calls and their responses are logged in `report/llm_calls.jsonl`
  (one JSON object per line: `{bnf_id, estc_id, bnf_title, estc_title, response}`).
- The model version is fixed to `claude-sonnet-4-6` in the script constant
  `CLAUDE_MODEL`; update as needed.
- Confidence scores from the LLM are stored in the `confidence` column with
  `match_type = "llm"` for downstream filtering.
