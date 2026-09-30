# 06 — External Mapping & Enrichment — Usage & Technical Notes

## 1. Module overview

Module 06 bridges the BnF dataset with three external authoritative catalogues:

| Script | Target | Method |
|--------|--------|--------|
| `01_map_viaf.py` | VIAF | ID lookup → name-based SRU search |
| `02_map_wikidata.py` | Wikidata | QID lookup → SPARQL label search |
| `03_map_estc_ecco.py` | ESTC / ECCO (editions) | Heuristic field matching → LLM translation check |
| `05_map_estc_actors.py` | ESTC actor authority (`estcr` package) | VIAF ID bridge → order-invariant name + date matching |
| `04_merge_mappings.py` | — | Joins all mapping outputs into enriched datasets |

---

## 2. Directory structure

```
06_mapping/
├── 01_map_viaf.py
├── 02_map_wikidata.py
├── 03_map_estc_ecco.py
├── 05_map_estc_actors.py
├── 04_merge_mappings.py
├── README.md
│
├── output/
│   ├── viaf_mapping.csv
│   ├── wikidata_mapping.csv
│   ├── estc_mapping.csv
│   ├── estc_actor_mapping.csv        ← BnF actor <-> ESTC actor overlap
│   ├── bnf_actors_enriched.csv       ← final enriched actor dataset
│   └── bnf_editions_enriched.csv     ← final enriched edition dataset
│
└── report/
    ├── viaf_mapping_report.json
    ├── wikidata_mapping_report.json
    ├── estc_mapping_report.json
    ├── estc_actor_mapping_report.json
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

# Step 5 — ESTC actor-authority overlap (usable independently of steps 2-4:
# only needs the two actor tables, so it can be run as soon as an actors
# dataset and data/estc/estc_actors.csv are available, e.g. for an early
# author-level deliverable before the edition/translation pipeline is done.
# Running Step 1 first is recommended, not required: this script defaults
# to reading its viaf_mapping.csv for additional VIAF IDs Pass 1 would
# otherwise miss, but proceeds fine without it if that file isn't there yet)
python 06_mapping/05_map_estc_actors.py \
    --bnf-actors  "05_subset_optimisation/output/bnf_actors_optimised.csv" \
    --estc-actors data/estc/estc_actors.csv
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
Service filters `rdfs:label` in French, constrained by birth year and/or
death year (±2 years each), whichever the BnF actor record has available:
- both known → both constraints apply (`AND`);
- only one known (birth *or* death) → only that constraint applies;
- neither known → no date filter, name match only.

A candidate is never rejected solely because *it* lacks a birth or death date
on Wikidata — the constraint only excludes candidates whose known date falls
outside the ±2-year window. This means an actor with only a death year
recorded in the BnF data (a common case, since death years are generally
better attested than birth years for early-modern figures) still benefits
from a date-narrowed search, instead of falling back to an unconstrained
name-only lookup as in earlier versions of this script.
Top candidate accepted if similarity ≥ `--threshold`.

### Output fields
`BnF_ID, qid, match_type, wikidata_label, birth_date, death_date, bnf_ark, viaf_id, isni, lc_id, confidence`

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--viaf-mapping` | `06_mapping/output/viaf_mapping.csv` | Supplementary QID source |
| `--threshold` | `0.85` | Min. similarity for pass-2 acceptance |
| `--sleep` | `0.5` | Seconds between API calls |
| `--monitor-script` | `00_monitor/monitor.py` | Path to the resource-monitoring module (see below) |
| `--no-monitor` | off | Disable the resource-usage monitor report |

### Resource-usage monitoring

`02_map_wikidata.py` is integrated with the same "embedded state-based
monitoring" mechanism used by module 1's `query_agents.R` and
`query_editions.R` (see `00_monitor/README.md` for the full mechanism
description). Concretely:

- when run from the command line, monitoring is **on by default** (pass
  `--no-monitor` to disable it — mirrors module 1, where the R scripts also
  default the CLI entry point to `use_monitor = TRUE`);
- at start-up it loads `00_monitor/monitor.py` and opens a monitoring state
  (`start_monitor_state`);
- one checkpoint is written per processed actor (`update_monitor_state`),
  tagged with a context string identifying the `BnF_ID` and the resulting
  `match_type` (`id`, `name`, or `unmatched`), plus one final checkpoint on
  completion;
- the state is closed cleanly at the end of the run (`stop_monitor_state`).

Each checkpoint records system CPU/memory/disk, GPU utilisation (if
available), network throughput, and process CPU/memory — the same metrics
described in `00_monitor/README.md`. Reports are written to:

```
00_monitor/report/02_map_wikidata_<YYYYMMDD_HHMMSS>_py.txt
```

If called programmatically (e.g. from tests or another script) via
`run_mapping(...)`, monitoring defaults to **off** (`use_monitor=False`) and
must be opted into explicitly — again matching the function-level default
used by the R equivalents in module 1.

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

**Pass 2 (heuristic — "same edition in both catalogues"):**
1. Year filter: only ESTC editions within ±`--year-window` years are candidates.
2. Author similarity ≥ `--author-threshold` (default 0.80).
3. Title similarity ≥ `--title-threshold` (default 0.75).
Both checks must pass; confidence = mean of the two scores; `match_type = "heuristic"`.
The year filter makes sense here because it targets the *same* print run
appearing in both catalogues, which is necessarily close in time. A Pass-2
match always takes priority over anything found in Pass 3.

**Pass 3 (LLM translation check, optional):**
A translation can be published decades — or centuries — after the original
work, so this pass does **not** reuse the year-windowed Pass-2 candidate
pool. It searches two candidate pools instead:
- the Pass-2 year-windowed candidates whose title didn't match (still
  checked, in case the translation *does* happen to fall within the window);
- a **year-unconstrained** pool retrieved via `author_index`, an index built
  by blocking ESTC records on the first token of the normalised author name
  (the standard library-authority "Surname, Firstname" convention). This
  lets Pass 3 find a translation published at any distance in time from the
  BnF edition, as long as the author name matches (similarity ≥
  `--author-threshold`) — capped at `--max-author-candidates` records per
  BnF edition for performance.

For every candidate in either pool whose author matches, whose title does
not, and whose language differs from the BnF edition's, a single Claude API
call asks whether the BnF title is a translation of the ESTC title.  Requires
`ANTHROPIC_API_KEY` in the environment; silently skipped if absent.

The LLM prompt:
```
Is the title "<bnf_title>" (language: <bnf_lang>) a translation or equivalent
of "<estc_title>" (language: <estc_lang>)?
Answer ONLY with valid JSON: {"match": true or false, "confidence": 0.0 to 1.0}
```

**Ambiguous translations:** if the LLM check accepts (match=true, confidence
≥ `--llm-threshold`) more than one ESTC candidate for the *same* BnF edition,
the match is not auto-resolved. This is expected for prolific or classical
authors with several independent translations — e.g. a French and an English
translation of a Latin original are not translations of *each other*, even
though both would independently pass the author-match + language-mismatch
check against the BnF edition. In that case `match_type = "ambiguous_translation"`:
the highest-confidence candidate is still recorded in the output row
(`estc_id`, `confidence`, etc.), but the `notes` field lists the discarded
alternates, and the row is meant for manual review rather than being treated
as a confident link. When exactly one candidate is accepted, `match_type = "llm"`
as before.

### Output fields
`BnF_edition_id, estc_id, match_type, confidence, estc_title, estc_author, estc_year, estc_language, bnf_title, bnf_year, bnf_language, notes`

`match_type` is one of: `heuristic`, `llm`, `ambiguous_translation`, `unmatched`.

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--author-threshold` | `0.80` | Min. author name similarity |
| `--title-threshold` | `0.75` | Min. title similarity |
| `--llm-threshold` | `0.80` | Min. LLM confidence for pass-3 acceptance |
| `--year-window` | `2` | ±years around BnF publication year (Pass 2 only) |
| `--max-author-candidates` | `2000` | Cap on ESTC candidates per BnF edition retrieved via `author_index` (Pass 3) |
| `--sleep` | `0.3` | Seconds between calls |
| `--monitor-script` | `00_monitor/monitor.py` | Path to the resource-monitoring module (see below) |
| `--no-monitor` | off | Disable the resource-usage monitor report |

### Resource-usage monitoring

Same "embedded state-based monitoring" mechanism as module 1
(`query_agents.R` / `query_editions.R`) and `02_map_wikidata.py` (see
`00_monitor/README.md`): one checkpoint every 100 BnF editions
(`MONITOR_CHECKPOINT_EVERY`) and at the last one, plus a final checkpoint, on by default from the CLI (`--no-monitor` to disable),
off by default when `run_mapping(...)` is called programmatically. Reports
are written to:

```
00_monitor/report/03_map_estc_ecco_<YYYYMMDD_HHMMSS>_py.txt
```

---

## 7. Script 5 — `05_map_estc_actors.py` (author-level overlap)

Matches BnF actors directly against the ESTC **actor-authority** table
(`estc_actors.csv`, from the COMHIS `estcr` R package —
https://github.com/COMHIS/estcr — distinct from `estc_raw_sane.csv`, which is
edition-level and consumed by script 03 above). This is the standalone
deliverable for an author-level BnF/ESTC overlap: it only needs the two
actor-side tables, so it can be produced before the edition/translation
pipeline (script 03) is complete.

### Inputs
- Any BnF actor dataset — module 4's ready dataset (id column `actor`) or
  module 5's optimised subset (id column `BnF_ID`); both accepted.
- `data/estc/estc_actors.csv` — the ESTC actor-authority table.

### Algorithm
**Pass 1 (VIAF ID bridge):** both sides can carry a VIAF URI (BnF's
`actor_link_exact`/`actor_link_close`; ESTC's `viaf_link`, or `actor_id`
itself when `actor_id_type == "viaf"`). A shared numeric VIAF ID is treated
as certain identity — `match_type = "viaf_id"`, confidence 1.0.

**Pass 2 (order-invariant name + date fallback):** BnF names are typically
"Given Family" while ESTC's `name_unified` is typically the library-
authority "Family, Given" — comparing raw strings would treat identical
names as different people. Both sides are reduced to a normalised **token
set** instead (preferring structured first/last-name fields when both
datasets have them), so naming-convention order doesn't matter. Within a
token-set match, birth/death years are compared with a ±`--year-window`
(default 2) tolerance:
- a comparable year pair falling outside the window discards that candidate
  (same name, conflicting lifespan → different person, not ambiguous);
- exactly one candidate surviving → `match_type = "name_and_dates"`;
- more than one surviving → `match_type = "ambiguous_name_and_dates"`
  (alternates listed in `notes`, never auto-resolved);
- none surviving but some had no comparable date at all →
  `match_type = "ambiguous_name_only"` (same name, no evidence either way);
- no name-token overlap, or every same-name candidate had conflicting
  dates → `match_type = "unmatched"`.

ESTC rows with `is_organization == TRUE` are excluded (persons only).

### VIAF-mapping enrichment (Pass 1)

`01_map_viaf.py` can resolve a VIAF ID for a BnF actor via name-based SRU
search even when the raw BnF record carries none in
`actor_link_exact`/`actor_link_close`. Its output (`viaf_mapping.csv`) is
fed in as an additional per-`BnF_ID` VIAF-ID source for Pass 1 — the same
role `viaf_mapping.csv` already plays for `02_map_wikidata.py`. Enabled by
default from the CLI (`--viaf-mapping`); off by default when
`run_mapping(...)` is called programmatically. A missing mapping file is
not an error — matching simply relies only on the VIAF IDs already present
in the BnF data. To get the fullest benefit, run `01_map_viaf.py` on the
same actor dataset before this script.

### Deduplication of BnF-side duplicates

Each BnF actor row is matched independently, so a BnF actor duplicated
under two or more URIs (see `actors_deduplication.py`) would otherwise
appear as separate — possibly conflicting — rows in the output.
`collapse_by_canonical()` folds duplicates identified by that script's
`actor_dedup_mapping.csv` onto a single row per canonical actor, keeping
whichever duplicate found the highest-confidence match (ranked by
`MATCH_TYPE_PRIORITY`: `viaf_id` > `name_and_dates` >
`ambiguous_name_and_dates` > `ambiguous_name_only` > `unmatched`). Enabled
by default from the CLI (`--dedup-mapping`); off by default when
`run_mapping(...)` is called programmatically (pass a path to opt in). A
missing mapping file is not an error — collapsing is silently skipped.

### Output files (same columns in all three, one row per distinct actor)
`BnF_ID, estc_actor_id, match_type, confidence, bnf_actor_name, estc_actor_name, estc_viaf_link, bnf_birth_year, bnf_death_year, estc_birth_year, estc_death_year, notes`

| File | Contents |
|------|----------|
| `estc_actor_mapping.csv` | Every distinct actor, including `unmatched` |
| `estc_actor_mapping_confident.csv` | `viaf_id` + `name_and_dates` only — safe to use directly |
| `estc_actor_mapping_review.csv` | `ambiguous_name_only` + `ambiguous_name_and_dates` only — needs manual confirmation before use |

`unmatched` rows appear only in the full file, never in either split.

`estc_actor_mapping_report.json` carries `total_bnf_actor_records`
(pre-dedup), `distinct_actors_after_dedup`, `duplicates_collapsed`, and
per-match_type counts over the distinct actors.
`estc_actor_mapping_report.txt` — the same numbers as plain-language
sentences, written automatically on every run (template-filled from the
counts already computed, not LLM-generated), for checking the outcome
without parsing JSON.

### Parameters
| Param | Default | Description |
|-------|---------|-------------|
| `--bnf-actors` | `05_subset_optimisation/output/bnf_actors_optimised.csv` | BnF actor dataset (either ID schema) |
| `--estc-actors` | `data/estc/estc_actors.csv` | ESTC actor-authority table (a sample or the full COMHIS export — this script makes no assumption about completeness) |
| `--year-window` | `2` | ±years tolerance for birth/death comparison |
| `--viaf-mapping` | `06_mapping/output/viaf_mapping.csv` | `01_map_viaf.py` output; supplies additional VIAF IDs for Pass 1; pass `''` to disable |
| `--dedup-mapping` | `.../actor_name/01_heuristic_rules/output/actor_dedup_mapping.csv` | `actors_deduplication.py` output; pass `''` to disable collapsing |
| `--monitor-script` / `--no-monitor` | — | Same monitoring mechanism as the rest of this module |

### Resource-usage monitoring
Same "embedded state-based monitoring" mechanism as the rest of module 06,
but checkpointed every `MONITOR_CHECKPOINT_EVERY` (1,000) processed BnF
actor records rather than every single one — per-record checkpointing was
the main bottleneck on a ~93k-actor run — plus a final checkpoint, on by
default from the CLI. Reports land in
`00_monitor/report/05_map_estc_actors_<YYYYMMDD_HHMMSS>_py.txt`.

### On the `estcr` data files
`data/estc/estc_core.csv` (~264MB) and `data/estc/estc_actor_links.csv`
(~314MB) are **not committed** (gitignored) — too large for this repo's
git-lfs quota alongside everything already tracked. They are not needed by
this script (only `estc_actors.csv`, ~34MB, is — and it *is* committed).
Small samples of all three (a few hundred rows each) live in
`00_test/data/estc_samples/` for tests. `estc_core.csv` /
`estc_actor_links.csv` become relevant once the edition-level crosswalk
(attaching editions/roles to the actor overlap) is tackled — not yet
implemented.

---

## 8. Notes on ECCO vs ESTC

ECCO (Eighteenth Century Collections Online, Gale) does not expose a public
API or downloadable metadata.  The practical access route is via the ESTC,
which underpins ECCO and is available as open data through COMHIS.

The COMHIS ESTC harmonised CSV (`estc_raw_sane.csv`) is the recommended input
for script 03.  Contact the COMHIS group (University of Helsinki) or consult
`https://github.com/COMHIS/estc-data-verified` for access.

---

## 9. Script 4 — `04_merge_mappings.py`

Joins all mapping CSVs onto the base actor and edition datasets, producing
two enriched CSVs ready for graph materialisation (module 07).

### Actor enrichment adds columns
`viaf_id, viaf_name, viaf_birth_date, viaf_death_date, mapping_confidence_viaf, qid, wikidata_label, isni, lc_id, bnf_ark_wikidata, mapping_confidence_wikidata, estc_actor_id, estc_actor_name, estc_actor_match_type, estc_actor_confidence`

The last four columns join in script 5's actor-level ESTC overlap
(`estc_actor_mapping.csv`, keyed by `BnF_ID`) — decided to merge it in
rather than leave it standalone, so `bnf_actors_enriched.csv` stays the
single "actor + all known external authorities" dataset, matching how
VIAF/Wikidata are already merged rather than left separate. A missing
`estc_actor_mapping.csv` (script 5 not run yet) is not an error — those
four columns are simply empty, same behaviour as a missing VIAF/Wikidata
mapping.

### Edition enrichment adds columns
`estc_id, estc_title, estc_author, estc_year, estc_language, estc_match_type, estc_confidence`

### Parameters (new)
| Param | Default | Description |
|-------|---------|-------------|
| `--estc-actors` | `06_mapping/output/estc_actor_mapping.csv` | `05_map_estc_actors.py` output |

---

## 10. LLM pass — notes for reproducibility

The LLM translation check introduces a non-deterministic element.  To ensure
reproducibility:
- All LLM calls and their responses are logged in `report/llm_calls.jsonl`
  (one JSON object per line: `{bnf_id, estc_id, bnf_title, estc_title, response}`).
- The model version is fixed to `claude-sonnet-4-6` in the script constant
  `CLAUDE_MODEL`; update as needed.
- Confidence scores from the LLM are stored in the `confidence` column with
  `match_type = "llm"` for downstream filtering.
