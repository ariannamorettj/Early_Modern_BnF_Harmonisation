Here is the English translation of the report:

---

# Detailed Report — Module 04\_harmonisation\_and\_evaluation

**Path:** `/Users/ariannamorettj/Documents/GitHub/New-BnF-Data-Analysis-2/04_harmonisation_and_evaluation/`
**Report date:** 2026-06-22

---

## 1. Purpose and Position in the Pipeline

Module 04 is the core of the data cleaning and quality control pipeline. It receives as input the raw datasets produced by the acquisition stage (module 01) and sampled/analysed in modules 02 and 03, and produces harmonised, integrated "ready" datasets that module 05 optimises into a research-oriented subset, and that module 06 (mapping) and everything downstream can also read directly when the full/extended data is needed rather than module 05's subset.

The module has three sub-modules:

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
    ├── 02_evaluation/            ← QA on the output of each normaliser
    │       [per field]
    │       └── <field>_evaluation.py    ← Child class of Evaluation
    │
    │       Output: <field>_summary.csv | <field>_warnings.csv | <field>_errors.csv
    │
    └── 03_ready_dataset_assembly/ ← Integrates ALL available field-level
            assemble_actors_ready.py     harmonisations on top of the raw data
            assemble_editions_ready.py   into one traceable "ready" dataset
                                          per entity (actors, editions) — see
                                          section 7 below. This is what
                                          module 05 (and, when the full
                                          dataset is needed, module 06+) reads.
```

**General principle:**

1. The heuristic normaliser is run first on all values.
2. Its output is evaluated by the corresponding evaluator.
3. Cases with low or medium confidence, or unresolved by the heuristic normaliser, are forwarded to the LLM normaliser.
4. The LLM output follows the same schema as the heuristic output, with the additional column `llm_explanation`.

**Deterministic-first, LLM-as-last-resort — and why this matters for cost and
reproducibility, not just design taste.** The heuristic step is meant to be
exhaustive: every anomaly category with a clear, rule-based resolution
(regex, lookup table, structural pattern) is handled deterministically
first, and only the residual that genuinely cannot be resolved without
external judgement — free text, ambiguous phrasing, missing context — is
sent to an LLM. Concretely for `actor_dates` (see 3.2 below): the heuristic
rule alone resolves 99.98% of all non-empty date values (1,731,680 of
1,731,972, verified over the full raw dataset); only the
`non_parseable` residual (~0.013%, a few hundred rows) is a candidate for
the LLM step. A heuristic rule is deterministic, free, instant, and its
output is exactly reproducible on re-run — an LLM call is none of those.
Where the LLM step is implemented, it is planned to run **by default** as
the next stage after the heuristic step (so the pipeline stays "one command
= fully harmonised, as far as automatically possible" without a manual
second invocation), with a `--no-llm` flag to skip it — this keeps the
LLM step opt-out rather than opt-in specifically *because* the heuristic
step already carries the vast majority of the load; the LLM is there to
close the small remaining gap, not to be the primary mechanism.

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
**Overall status:** ✅ Heuristic normaliser + LLM residual step both implemented.

**Real anomaly categories (superseding the anomaly table originally listed
here, which predates the full implementation)** — from a full run of
`name_normaliser.py` against the real dataset (124,695 unique actors,
deduplicated by actor URI from the raw dataset's 551,622 rows):

| `correction_type` | Count | Meaning |
|---|---:|---|
| `none` | 106,538 | No anomaly — value passed through unchanged |
| `derived_from_first_last` | 14,046 | `actor_name` was empty; filled from `actor_first_name`/`actor_last_name` |
| `stripped_rdf_literal_tag` | 2,507 | RDF quoted-literal-with-language-tag syntax leaking through (e.g. `'"William Blake trust"@fr'`) |
| `stripped_title_role` | 1,460 | Embedded title/role removed (e.g. `"Sieur de Malherbe"` → `"Malherbe"`) |
| `initials_or_abbreviation_unresolved` | 59 | Bare initials/abbreviation, no fuller form available — **LLM residual** |
| `unresolved_multiple_values` | 47 | Looks like two concatenated names — **LLM residual** |
| `alias_split` | 17 | Alias marker found (e.g. `"dit le"`), primary name kept |
| `unresolved_brackets_or_separators` | 16 | Bracket/quote present but doesn't cleanly wrap the whole string — **LLM residual** |
| `preferred_first_last_over_initials` | 3 | Initials-only `actor_name` replaced by a more informative `first_name`+`last_name` |
| `unresolved_missing` | 2 | All three source fields empty — nothing to derive from |

**01\_heuristic\_rules/ — Implemented**

`name_normaliser.py`: a 7-rule cascade (RDF-literal unwrap → bracket/quote
stripping, only when it fully resolves the anomaly → alias-marker split →
title/role stripping → multiple-values flagging (never auto-split) →
initials/abbreviation preference for a fuller first/last-name form →
passthrough), plus the empty-`actor_name` derivation above. See the
module's own docstring for the exact rule order and the empirical
justification behind each (e.g. why `stripped_rdf_literal_tag` is checked
before the generic bracket rule: it accounts for 2,507 of 2,519 cases that
would otherwise come out only half-cleaned).

`actors_id_matching.py` / `actors_name_matching.py` / `actors_deduplication.py`
— ✅ Implemented (identity resolution across distinct BnF URIs sharing a
name; see that script's own docs).

`name_correction_dict.json` — **NOT implemented, not planned for
automation**: a curated known-error lookup requires manual annotation of
real cases, which is out of scope for this codebase to fabricate.

**02\_llm\_based/ — Implemented**

`llm_name_normaliser.py` resolves the three genuinely-unresolved residual
categories marked above (`unresolved_brackets_or_separators`,
`unresolved_multiple_values`, `initials_or_abbreviation_unresolved` — 122
rows total on the real dataset, a small and cheap residual). Deliberately
does NOT revisit `alias_split`/`stripped_title_role` (medium confidence,
but already resolved by a clear rule match) or `unresolved_missing` (no
source value at all to derive from) — same "never re-touch an
already-resolved value, never invent from nothing" principle as
`llm_dates_normaliser.py`/`llm_publisher_normaliser.py`. Same conventions
throughout: deduplicated by `(raw value, correction_type)` pair, JSON
response cache, Claude Opus 5 via structured output
(`client.messages.parse()`), default-on after the heuristic step
(`--no-llm` to skip). For `initials_or_abbreviation_unresolved` specifically,
the system prompt explicitly forbids guessing a historical identity from
outside knowledge — that is authority-linking's job (module 06), not this
step's.

---

### 3.2 actor\_dates/ — Actor Dates

**Dataset:** actor\_data
**Fields:** `actor_birth`, `actor_death`, `actor_start`, `actor_end`
**Overall status:** In progress — heuristic rule implemented

**Target output format:** EDTF (Extended Date/Time Format, extended ISO 8601)

**Real anomaly categories (superseding the free-text categories originally
speculated here — see note below)**

A full scan of the raw dataset (~1.73M non-empty date values across the
four fields) found the BnF source already uses a structured *numeric*
convention, not free text ("ca. 1750", "vers 1720", "XVIIIe siècle" etc. do
not occur at all):

| Category | Examples | EDTF output | Confidence | Meaning | Share (of all values incl. missing) |
|---|---|---|---|---|---|
| `exact_year` | `1750`, `43`, `-43`/`- 43` (1-4 digits, optional BCE sign, no zero-padding) | `1750`, `0043`, `-0043` | high — pure zero-padding, no digit invented | Full year known, day/month not recorded | 50.6% |
| `exact_date` | `1594-06-14` | `1594-06-14` | high — year zero-padded, month/day pass through | Exact day known | 22.8% |
| `missing` | `NA`, empty | *(empty)* | low — nothing to harmonise | Source has no value at all (not a parsing failure) | 21.5% |
| `masked_precision` | `17..`, `1...`, `17XX` (trailing `.`/`X` mask unspecified digits) | `17XX`, `1XXX` | high — digit-for-digit `.`/`X` → EDTF `X` substitution | Only century/decade/millennium known; source never recorded the rest (structural gap, not an approximation — see below) | 4.1% |
| `year_month` | `1564-04` | `1564-04` | high — year zero-padded, month passes through | Month known, day not recorded | 0.9% |
| `non_parseable` | `150.-02-20`, `1799-03-2.`, `14??` (mask char inside a full date, masked day instead of year, unexpected mask char, etc.) | *(empty)* | low — deliberately not attempted | Real but rare hybrid/malformed forms; left for future LLM step / manual review rather than special-cased | 0.013% |

**Why `masked_precision` maps to EDTF's `X` and not `~`/`?`:** EDTF's `~`
(approximate) and `?` (uncertain) qualifiers express epistemic doubt about a
value that IS known but imprecisely so. `masked_precision` is different: the
BnF source structurally never recorded those trailing digits at all — it is
a gap in the record, not a judgement call about an otherwise-known date.
EDTF Level 2 defines `X` as the standard "unspecified digit" character for
exactly this case, so the `.`/`X` → `X` substitution here is a faithful
transcription of what the source already expresses, not an inference.

**01\_heuristic\_rules/ — Implemented**

`dates_normaliser.py`:

- `detect_date_format(raw_value)` → classifies into the six categories above
- `normalise_date(raw_value)` → converts to EDTF, returns `{harmonised, format_detected, confidence}`
- `run(input_path, output_dir)` → processes full CSV/ZIP, one output row per (actor, field)

Output schema: `actor_uri | field | date_original | date_harmonised | date_format_detected | confidence`

**BCE (negative year) handling:** the source marks BCE years with a leading
`-` (e.g. `-43`, `- 43`). Strict EDTF/ISO 8601-2 negative years use
*astronomical* numbering (year `0000` = 1 BCE, so 43 BCE would be `-0042`).
This implementation does **not** apply that offset — it zero-pads the
digits already present and keeps the sign as-is (43 BCE → `-0043`). This
was verified empirically: one actor has `actor_birth="- 384"`,
`actor_death="- 322"` — Aristotle's well-known dates (384–322 BCE) match
those digits exactly with no shift, which astronomical numbering would not
produce. The source already uses ordinary historical BCE counting (common
in GLAM/library linked data), so applying an unverified astronomical offset
would introduce a silent one-year error rather than fix one. See the
`dates_normaliser.py` module docstring for the full reasoning.

Monitoring, CLI (`--input`/`--output`/`--no-monitor`) and tests
(`00_test/test_dates_normaliser.py`) follow the same conventions as
`actor_name/01_heuristic_rules/name_normaliser.py`.

This heuristic rule deliberately does not attempt `non_parseable` values
(~0.02%) — see 02_llm_based below, which resolves that residual.

**02\_llm\_based/ — Implemented**

`llm_dates_normaliser.py` resolves the `non_parseable` residual left by the
heuristic rule above (only that residual — never the 99.98% the heuristic
step already resolved with high confidence). Deduplicated by raw value
(many non_parseable rows share the same malformed source string) and cached
to disk, so re-running the pipeline never re-queries an already-resolved
value. Uses Claude Opus 5 with structured output (a Pydantic schema via
`client.messages.parse()`, not free-text JSON parsing) so the response is
always a parseable `{harmonised, confidence, explanation}` triple; the
system prompt gives the model the same EDTF conventions documented above
(mask characters -> `X`, BCE sign kept literal with no astronomical
offset), so its output stays consistent with the heuristic step's.

By default, running `dates_normaliser.py` also runs this step immediately
afterwards (single command = fully harmonised, as far as automatically
possible) and merges the result back into the same output file, adding an
`llm_explanation` column; pass `--no-llm` to skip it and get the
heuristic-only output. This default-on choice is still "prefer the lighter
resolution" in practice — see section 1 above — because the LLM step only
ever processes the small residual (currently a few hundred rows, deduplicated
to under two dozen unique raw values) the heuristic step could not resolve;
it never re-processes anything already resolved deterministically.

Monitoring, CLI (`--heuristic-output`/`--output`/`--cache`/`--model`/
`--effort`/`--no-monitor`) and tests (`00_test/test_llm_dates_normaliser.py`,
10 tests using a fake client — no real API calls) follow the same
conventions as the rest of the pipeline. Requires the `anthropic` package
(added to `pyproject.toml`) and an Anthropic API credential to actually run
against the API — see the script's module docstring.

---

### 3.3 external\_links/ — External Authority Links

**Dataset:** actor\_data
**Fields:** `actor_link_close`, `actor_link_exact`
**Overall status:** ✅ Heuristic normaliser implemented. No LLM step (nothing ambiguous for an LLM to add — see below).

**Real anomaly categories (superseding the speculative categories
originally listed here — see note below)**

A full scan of the real raw dataset (01\_data\_retrieval/02\_actors/actors\_data/actor\_data.csv,
551,622 rows) found a much simpler and more regular picture than what was
originally speculated:

| Category | Examples | Share |
|---|---|---|
| Every non-empty value RDF-wrapped | `<http://viaf.org/viaf/23356192/>` | 100% — 0 exceptions |
| Multi-value cells | none — each `skos:exactMatch`/`closeMatch` binding is already its own row (see the row-multiplicity note in 01\_data\_retrieval's README) | 0 |
| Distinct domains | VIAF, Wikidata, ISNI, LC Name Authority, DNB/GND, IdRef, BNE, Wikipedia, DBpedia, IMSLP, MusicBrainz, Biblissima, FranceArchives, Persée, GeoNames, INSEE, Archives Nationales, POP-Culture, FAO-AIMS, PURL, ORCID | 23 total |
| Scheme inconsistency | only `fr.wikipedia.org` and `imslp.org` show both `http` and `https` in the data — every other domain (viaf.org, wikidata.org, isni.org, id.loc.gov, d-nb.info, www.idref.fr, datos.bne.es, ...) appears with exactly one scheme only | 2/23 domains |
| Malformed (empty scheme + host) | `<://43102>` | ~1,006 rows on a full run |

None of the originally speculated "www vs no-www" or "deprecated/redirect
URI" anomalies occur in the data — `www.idref.fr` always carries `www.`
with no bare-domain form present, and there is no evidence of a deprecated
URI pattern to resolve.

**01\_heuristic\_rules/ — Implemented**

`external_links_normaliser.py`:

- `strip_wrapping(raw)` → removes the RDF `<...>` wrapper (the single most
  important step; not part of the original plan)
- `normalise_link(raw)` → classifies into `missing` / `malformed` /
  `scheme_upgraded_https` (only the two evidenced domains) /
  `passthrough` (known authority, single observed scheme) /
  `unknown_authority` (well-formed URI, domain not yet in `AUTHORITY_TABLE`)
- No `http`→`https` upgrade is applied to a domain unless the raw data
  itself demonstrates both schemes resolve — same "don't invent digits"
  principle as `actor_dates`' BCE-offset decision (see 3.2 below):
  upgrading a domain never observed as https would be guessing, not
  harmonising.

A full run against the real dataset: 224,184 `passthrough`, 7,922
`scheme_upgraded_https`, 1,006 `malformed`, **0 `unknown_authority`** —
confirming `AUTHORITY_TABLE` covers every domain actually present.

**02\_llm\_based/ — not implemented, not planned**

A link either resolves against a known authority structurally or it
doesn't; unlike `actor_dates`' `non_parseable` residual, there is no
ambiguous natural-language judgement call here for an LLM to usefully add.

Output schema: `actor_uri | field | link_original | link_harmonised | authority | correction_type | confidence` (one row per distinct raw value actually present — see module docstring for why there is no "missing" placeholder row per actor the way `actor_dates` emits one)

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
**Overall status:** ✅ Heuristic normaliser implemented — 100% deterministic coverage, no lookup dictionary or LLM step needed.

**Target output format:** Three-letter ISO 639-2 codes (BnF standard)

**IMPORTANT — this supersedes the free-text anomaly categories originally
speculated here.** A full scan of the real raw dataset
(01\_data\_retrieval/01\_editions/data/bnf\_edition\_data\_raw.csv, 1,344,914
rows) found that none of the speculated free-text forms ("français",
"vieux français", "Latin et français", "???", etc.) occur at all. Every one
of the 106 distinct non-empty raw values is instead an RDF-wrapped LOC
vocabulary URI:

    "<http://id.loc.gov/vocabulary/iso639-2/fre>"
    "<http://id.loc.gov/vocabulary/iso639-2/lat>"

— 0 exceptions. "mul" (multiple languages) and "zxx" (no linguistic
content) are already the source's own controlled codes for those cases, so
multi-language expressions are already handled upstream, not left as
concatenated free text.

Because of this, the whole field reduces to one deterministic rule: strip
the `<...>` wrapper, take the URI's trailing path segment, validate it is 3
lowercase letters. **No `language_lookup.json` is needed** — the originally
planned lookup-dictionary approach does not apply here.

**01\_heuristic\_rules/ — Implemented**

`language_normaliser.py`:

- `detect_language_format(raw)` → `iso_code_uri` / `missing` /
  `non_parseable` (safety net for future data — 0/106 currently)
- `normalise_language(raw)` → strips the wrapper, extracts the code,
  returns `{harmonised, correction_type, confidence}`

A full run against the real dataset: 748,624 `iso_code_uri` (high
confidence), 65,407 `missing`, **0 `non_parseable`** — 100% deterministic
resolution of every non-empty value.

**02\_llm\_based/ — not implemented, not planned**

Nothing is left unresolved to route to an LLM.

Output schema: `edition | language_original | language_harmonised | correction_type | confidence`

---

### 3.6 publisher/ — Publisher

**Dataset:** bnf\_edition\_data
**Field:** `publisher` (free text; distinct from `publisher_2` which is a URI)
**Overall status:** ✅ Heuristic normaliser + LLM residual step implemented.

Unlike `external_links` and `language` above, this field's originally
speculated anomaly categories ARE confirmed by the real raw dataset
(01\_data\_retrieval/01\_editions/data/bnf\_edition\_data\_raw.csv, 128,811
distinct non-empty values):

| Category | Real examples found |
|---|---|
| Sine-nomine markers | `[s.n.]` (93,251×), `[sans nom]` (2,730×) |
| Self-published markers (agent known, not a formal publisher — kept distinct from sine-nomine) | `Auteur` (7,016×), `l'auteur` (4,006×), `chez l'auteur` (2,438×) |
| Abbreviation + case variants of the same publisher | `Impr. royale` (19,364×), `Imp. royale` (5,305×), `imp. royale` (4,827×) — all collapse to `Imprimerie royale` |
| Bracketed, editorially-supplied names | `[G. L. Le Rouge]`, `[J. Audran et F. Chéreau]` |
| Multiple publishers concatenated in one cell | `Vve F. Muguet et H. Muguet`, `Vve Saugrain et. - P. Prault` |

128,811 distinct values makes full pairwise fuzzy-distance clustering
impractical to get right in one pass, and the project's existing
fuzzy-matching convention is stdlib `difflib`/normalised-key comparison
(see `06_mapping/01_map_viaf.py`'s Levenshtein-ratio use via
`difflib.SequenceMatcher`), not a new dependency like RapidFuzz. This
implementation uses **normalised-key clustering** instead (accent/case/
punctuation-insensitive key, merging onto the dataset's most frequent
literal form) — cheap, and it already resolves the case/abbreviation
variants shown above. True fuzzy-distance clustering (catching genuine
misspellings that don't share a normalised key) is intentionally NOT
attempted — documented as a follow-up, same incremental philosophy as
`actor_name`'s `derive_from_first_last`-only first cut.

**01\_heuristic\_rules/ — Implemented**

`publisher_normaliser.py` + `publisher_abbreviations.json`:

1. Sine-nomine / self-published detection (kept as two distinct categories)
2. Multi-value delimiter flagging (`;` / ` - ` / `\bet\b`) — **flagged, not
   split**: guessing which of two concatenated names is "the" publisher
   would invent information; known false-positive risk documented in the
   module docstring (an idiomatic single-firm name using "et" would also
   be flagged)
3. Trailing-location stripping (`"Chaignieau aîné (Paris)"` →
   `"Chaignieau aîné"`), careful not to strip a year-range parenthesis
   (`"J. Smith (1750-1780)"` is left alone)
4. Abbreviation expansion via `publisher_abbreviations.json`
   (Impr./Imp./imp. → Imprimerie, Éd./Ed. → Éditeur, Lib. → Libraire,
   Vve → Veuve, etc.)
5. Normalised-key clustering onto the most frequent literal form (pass 2.5,
   `cluster_by_canonical_key()`)
6. Fuzzy-similarity clustering (pass 2.6, `cluster_by_fuzzy_similarity()`):
   among the distinct canonical keys pass 5 left standing, values are
   blocked by a 4-character canonical-key prefix and compared pairwise with
   `difflib.SequenceMatcher` (threshold 0.87 by default, `--fuzzy-threshold`
   to override), merged via a small union-find for transitive matches
   (A~B~C merge even without a direct A~C match). Catches genuine
   near-misses — a typo, an OCR-style substitution — that an exact
   canonical key can't. `correction_type='fuzzy_clustered'` carries
   `confidence='medium'`, deliberately lower than pass 5's `'high'`, since
   fuzzy matching risks merging two different but similar-looking names.
   `--no-fuzzy-clustering` restores the exact-key-only behaviour.

A full heuristic-only run against the real dataset (814,031 editions,
128,809 distinct values, with fuzzy clustering enabled): 275,799
`passthrough`, 264,479 `missing`, 98,681 `abbreviation_expanded`, 48,627
`sine_nomine`, 33,683 `bracketed_uncertain`, 22,336 `canonical_clustered`,
**16,186 `fuzzy_clustered`** (8,411 distinct raw values relabelled; 25
oversized blocks skipped rather than compared, see `MAX_FUZZY_BLOCK_SIZE`),
5,891 `self_published`, 1,008 `location_stripped`, and **47,341
`multi_value`** (flagged for the LLM residual step below, or manual
review).

Output schema: `edition | publisher_original | publisher_harmonised | correction_type | confidence`

**02\_llm\_based/ — Implemented**

`llm_publisher_normaliser.py` resolves the `multi_value` residual left by
the heuristic step (only that residual — `missing`/`sine_nomine`/
`self_published` rows are already definitive and are never sent to the
LLM). Same conventions as `actor_dates`' LLM step: deduplicated by raw
value, JSON response cache, Claude Opus 5 via structured output
(`client.messages.parse()`), default-on after the heuristic step (`--no-llm`
to skip). **Not yet run against the real residual** — 47,341 editions carry
a `multi_value` value, but deduplicated by distinct raw string (the LLM is
only called once per unique value, see module docstring) that is 18,334
API calls; run it deliberately rather than as an automatic side effect of
this session.

---

## 4. Sub-module 02\_evaluation — QA Evaluation System

### 4.1 Architecture

The evaluation system is built on an abstract base class from which all field-specific evaluators inherit.

```
Evaluation (evaluation_base.py)          — abstract base class
├── PersonNameEvaluation                 — actor_name_evaluation.py    ✅ Complete
├── ActorDatesEvaluation                 — actor_dates_evaluation.py   ✅ Complete
├── ExternalLinksEvaluation              — external_links_evaluation.py 🔄 Skeleton
├── PublicationPlaceEvaluation           — publication_place_evaluation.py ✅ Complete
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
def evaluate_value(self, value: Optional[str], row: Optional[Dict[str, str]] = None) -> Tuple[List[str], Dict[str, str]]:
    # `row` is the full current CSV row as {header: value}, for evaluators
    # that need to cross-validate multiple columns together (see
    # ActorDatesEvaluation, PublicationPlaceEvaluation). Ignored by
    # evaluators that only validate one isolated field.
    # Returns:
    #   warnings: list of warning labels
    #   errors: dict { label: substitution_value }
```

**Execution flow of the `run()` method**

1. Iterates over CSVs (single file or all CSVs within a ZIP)
2. For each file: reads header, identifies index of the target column
3. For each row: calls `evaluate_value(value, row_dict)` (`row_dict` is the whole row as `{header: value}`)
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

**Status:** ✅ Complete

Validates that harmonised values match one of the four real shapes
`dates_normaliser.py` actually produces (`exact_year`, `exact_date`,
`year_month`, `masked_precision`) — the original placeholder's EDTF regex
matched *none* of `exact_date`/`year_month` and only a single-'X' subset of
`masked_precision`, so it would have misclassified the majority of real
output as errors. Uses `row['date_format_detected']` to tell an *expected*
empty value (`missing` — nothing to convert) apart from a documented,
still-unresolved one (`non_parseable` — a warning, not an error) apart from
a genuinely wrong one (any other empty case — `missing_value` error).

**Warnings**

- `decade_level` / `century_level` / `millennium_level` — masked_precision's
  1/2/3 trailing `X`s respectively (this is what the `decade_level` TODO
  asked for)
- `approximate_date` / `uncertain_date` / `date_range` — `~`/`?`/`/`,
  defensive checks: this project's normaliser deliberately never emits
  these (see `dates_normaliser.py`'s own docstring), so seeing one flags a
  likely regression, not a currently-expected case
- `unresolved_residual` — empty value where `date_format_detected ==
  'non_parseable'`, i.e. the heuristic step's own documented residual

**Errors**

- `missing_value` — empty value that isn't explained by `missing`/
  `non_parseable` in `date_format_detected`
- `non_edtf_format` — non-empty value matching none of the four real shapes

**Verified against the real harmonised output** (124,695 actors × 4 date
fields, 498,780 rows): `century_level` 22,553 + `millennium_level` 405 +
`decade_level` 1 = 22,959, exactly matching `dates_normaliser.py`'s own
`masked_precision` count; `unresolved_residual` 24, exactly matching its
`non_parseable` count. **0** `non_edtf_format` errors — confirming the
rewrite, unlike the placeholder it replaced, actually recognises every real
shape the normaliser produces.

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

**Status:** ✅ Complete

Row-level validation (`row['tgn_id']`/`publication_country`/`longitude`/
`latitude` alongside `publication_place`) via `evaluation_base.py`'s
`evaluate_value(value, row)` contract — the placeholder's own architectural
note asked for exactly this. Also fixes the placeholder's column names
(`uncertainty_expressions_brackets` etc.), which didn't match the real
`bnf_place_harmonisation.py` output (`place_uncertainty_brackets` etc.).

**Warnings**

- `unmatched_place` — `place_original` had a value but TGN lookup *and*
  country fallback both failed — the harmoniser's own documented
  "unmatched" outcome, expected to happen, not a defect
- `missing_coordinates` — `tgn_id` present but longitude/latitude aren't

**Errors** (row-level contract checks: `bnf_place_harmonisation.py`'s own
logic always sets city/tgn_id/country together from one TGN-table lookup,
so these combinations should never occur on a correctly-behaving run)

- `missing_value` — no raw place and nothing resolved
- `missing_tgn_id` — `publication_place` resolved without a `tgn_id`
- `missing_publication_country` — `publication_place` resolved without a country
- `invalid_coordinates` — longitude/latitude outside [-180,180]/[-90,90]
- `residual_bracket_in_harmonised` / `_parenthesis_in_harmonised` /
  `_question_mark_in_harmonised` — a `[`/`]`/`(`/`)`/`?` character survived
  inside the harmonised `publication_place` string, which
  `harmonise_city_string()` should always have stripped

**Known, accepted limitation:** the uncertainty *boolean columns*
(`place_uncertainty_brackets` etc.) are computed by the harmoniser from the
city portion only, after its own `str_after_last_parentheses()` split —
fully cross-validating those flag columns against the raw `place_original`
would mean re-deriving that split here. Not attempted; the
`residual_*_in_harmonised` checks above are the part that's verifiable
without duplicating that parsing logic.

**Verified against the real harmonised output** (200k-row sample of
`bnf_publication_place.csv`): `unmatched_place` 5.33%, `missing_value`
12.94% — both expected outcome sizes. Two small, genuine findings the old
single-field check couldn't have surfaced: `residual_parenthesis_in_harmonised`
on 0.68% of resolved rows, and `missing_tgn_id` on 0.02% — real, if minor,
gaps in `bnf_place_harmonisation.py`'s own output, worth a look but outside
this evaluator's job to fix.

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
| `actor_name`/`first_name`/`last_name` | actor\_data | ✅ Complete (`name_normaliser.py` — 7-rule cascade, validated against the full 124,695-actor dataset) | Implemented (`llm_name_normaliser.py` — resolves the ~122-row unresolved-brackets/multiple-values/initials residual via Claude Opus 5; default-on, `--no-llm` to disable) | ✅ Complete (`PersonNameEvaluation`) | `name_correction_dict.json` (manual curation) not attempted; matching/dedup scripts implemented; output consumed by module 05 |
| `actor_birth`/`death`/`start`/`end` | actor\_data | ✅ Complete (`dates_normaliser.py` — numeric BnF convention → EDTF, 99.98% of values) | Implemented (`llm_dates_normaliser.py` — resolves the `non_parseable` residual via Claude Opus 5; default-on after the heuristic step, `--no-llm` to disable — see section 1) | ✅ Complete (validates all 4 real EDTF shapes + decade/century/millennium precision, cross-checked against 498,780 real rows) | Target: EDTF; output consumed by `03_ready_dataset_assembly/assemble_actors_ready.py` |
| `actor_link_close`/`exact` | actor\_data | ✅ Complete (`external_links_normaliser.py` — RDF-wrapper stripping + known-authority classification; 0 `unknown_authority` on a full run) | — | 🔄 Skeleton (domain list synced to the real 23-domain set) | No LLM approach planned/needed; consumed by `03_ready_dataset_assembly/assemble_actors_ready.py` |
| `place` | bnf\_edition\_data | — (empty) | — | 🔄 Skeleton | TGN approach implemented |
| `place` (TGN lookup) | bnf\_edition\_data | ✅ Complete (`bnf_place_harmonisation.py`, integrated with monitor/report/tests; `.R` version not yet updated) | — | ✅ Complete (row-level: tgn_id + coordinates + city + country together, cross-checked against real data) | Output in `bnf_publication_place.csv`; consumed by `03_ready_dataset_assembly/assemble_editions_ready.py` |
| `language` | bnf\_edition\_data | ✅ Complete (`language_normaliser.py` — LOC iso639-2 URI → code; 100% deterministic, 0 `non_parseable` on a full run) | — (not needed) | 🔄 Skeleton (code set synced to the real 106-code set) | No lookup dict needed (data is already URI-typed, not free text); consumed by `03_ready_dataset_assembly/assemble_editions_ready.py` |
| `publisher` | bnf\_edition\_data | ✅ Complete (`publisher_normaliser.py` — sine-nomine/self-published detection, abbreviation expansion, location stripping, normalised-key + fuzzy-similarity clustering) | Implemented (`llm_publisher_normaliser.py` — resolves the `multi_value` residual; default-on, `--no-llm` to disable; not yet run against the full 18,334-distinct-value residual) | 🔄 Skeleton | Consumed by `03_ready_dataset_assembly/assemble_editions_ready.py` |

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

Once a `<field>_harmonised.csv` (or, for `place`, `bnf_publication_place.csv`) exists for a
field, `03_ready_dataset_assembly/` (see section 7) picks it up automatically
on the next run — no code changes needed elsewhere.

---

## 7. Sub-module `03_ready_dataset_assembly` — Assembling the Ready Datasets

**Status:** 🔄 In progress — assembles whichever field-level harmonisations
exist so far; the output becomes "practically perfect" as more of the
`01_harmonisation/<field>/` normalisers get implemented.

**Purpose:** there is no separate merge step elsewhere that combines the
raw acquisition data with every field-level harmonisation output into one
integrated, traceable dataset per entity. This sub-module is that step —
it runs *after* `01_harmonisation` and *before* module 05, so that "the
optimisation happens starting from an already-harmonised dataset" and every
correction stays traceable back to its own `<field>_harmonised.csv` /
`<field>_original` mapping (the audit trail lives in those per-field files;
this assembly only integrates the *current best value* per field).

| File | Entity | Behaviour |
|---|---|---|
| `assemble_editions_ready.py` | editions | Deduplicates/aggregates the raw rows to one row per edition (there is no module-5 equivalent for editions — this is the only place that happens) + overlays three fields as new columns alongside the raw ones (never replacing `place`/`language`/`publisher` in place, since each overlay carries its own `correction_type`/`confidence` audit trail): `publication_place`/`publication_country`/`tgn_id`/coordinates/uncertainty flags from `bnf_publication_place.csv`, `language_harmonised`/`language_correction_type`/`language_confidence` from `language_harmonised.csv`, and `publisher_harmonised`/`publisher_correction_type`/`publisher_confidence` from `publisher_harmonised.csv`. Writes `data/bnf_edition_data/bnf_editions_ready.csv`, the path module 6 already expects. |
| `assemble_actors_ready.py` | actors | Preserves raw row-level granularity (deduplication is module 5's job) + overlays three fields: `actor_name` from `actor_name_harmonised.csv` (fills only when empty at the source — an existing name is never second-guessed); `actor_birth`/`actor_death`/`actor_start`/`actor_end` from `actor_dates_harmonised.csv` (**replaces** the raw value whenever an EDTF form is available, even if the raw field was already populated — harmonising a date always means reformatting it, e.g. `"17.."` → `"17XX"`); and `actor_link_exact`/`actor_link_close` from `external_links_harmonised.csv` (**replaces**, but keyed per `(actor_uri, field, raw value)` rather than per actor, since a single actor can carry multiple distinct links per field — see that normaliser's row-multiplicity note). Writes `04_harmonisation_and_evaluation/output/bnf_actors_ready.csv`, read by `05_subset_optimisation/gen_subset_optm.py`. |

Both scripts:
- register their harmonisation overlays in a `HARMONISATION_SOURCES` list at
  the top of the file — all fields with an implemented normaliser are now
  wired in (`actor_name`, `actor_dates`, `external_links` for
  `assemble_actors_ready.py`; `publication_place`, `language`, `publisher`
  for `assemble_editions_ready.py`); only edition-side `dates` and the
  role/agent-URI columns remain unregistered, since no normaliser exists
  for those yet;
- write a JSON report (`report/*_ready_report.json`) recording row/entity
  counts and, per field, whether it was harmonised or is still carrying raw
  values;
- use the same `00_monitor/monitor.py` embedded monitoring mechanism as the
  rest of the pipeline (periodic checkpoints + a final checkpoint, on by
  default via CLI, `--no-monitor` to disable);
- are covered by tests in `00_test/test_assemble_editions_ready.py` and
  `00_test/test_assemble_actors_ready.py`.

Run order (after the relevant `01_harmonisation` normalisers):

```bash
python 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/name_normaliser.py
python 04_harmonisation_and_evaluation/01_harmonisation/actor_dates/01_heuristic_rules/dates_normaliser.py
python 04_harmonisation_and_evaluation/01_harmonisation/external_links/01_heuristic_rules/external_links_normaliser.py
python 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/bnf_place_harmonisation.py
python 04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/language_normaliser.py
python 04_harmonisation_and_evaluation/01_harmonisation/publisher/01_heuristic_rules/publisher_normaliser.py
python 04_harmonisation_and_evaluation/03_ready_dataset_assembly/assemble_actors_ready.py
python 04_harmonisation_and_evaluation/03_ready_dataset_assembly/assemble_editions_ready.py
```