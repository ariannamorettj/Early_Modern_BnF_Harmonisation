# 03_ready_dataset_assembly

Assembles the "ready" datasets — one per entity (actors, editions) — that
integrate every available `01_harmonisation/<field>/` output on top of the
raw acquisition data. This is the step between harmonisation and module 05:
optimisation is meant to start from an already-harmonised dataset, and every
correction stays traceable back to its own field-level mapping file.

See `04_harmonisation_and_evaluation/README.md` section 7 for full details.

| Script | Output | Notes |
|---|---|---|
| `assemble_editions_ready.py` | `data/bnf_edition_data/bnf_editions_ready.csv` | Deduplicates raw rows to one per edition (no module-5 equivalent exists for editions) + overlays `publication_place` |
| `assemble_actors_ready.py` | `04_harmonisation_and_evaluation/output/bnf_actors_ready.csv` | Keeps raw row-level granularity (deduplication stays module 5's job) + overlays `actor_name` |

Both scripts pick up more harmonisations automatically as the corresponding
`01_harmonisation/<field>/01_heuristic_rules/<field>_normaliser.py` gets
implemented — extend the `HARMONISATION_SOURCES` list at the top of each
script, no other code changes needed.

## Usage

```bash
python assemble_editions_ready.py \
    --input 01_data_retrieval/01_editions/data/bnf_edition_data_raw.csv \
    --publication-place 04_harmonisation_and_evaluation/01_harmonisation/publication_place/02_tgn_lookup/data/data_final/bnf_publication_place.csv \
    --output data/bnf_edition_data/bnf_editions_ready.csv

python assemble_actors_ready.py \
    --input 01_data_retrieval/02_actors/actors_data/actor_data.csv \
    --actor-name-harmonised 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output/actor_name_harmonised.csv \
    --output 04_harmonisation_and_evaluation/output/bnf_actors_ready.csv
```

Both run with resource-usage monitoring on by default (`--no-monitor` to
disable) and write a JSON report (`report/*_ready_report.json`) recording
row/entity counts and which fields were harmonised vs. still raw.

Tests: `00_test/test_assemble_editions_ready.py`,
`00_test/test_assemble_actors_ready.py`.
