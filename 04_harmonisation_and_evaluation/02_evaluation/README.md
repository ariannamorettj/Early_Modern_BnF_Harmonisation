# 02_evaluation

This module contains evaluators for assessing the quality of each harmonisation
script produced in `01_harmonisation/`.

For each field and each normalisation approach, an evaluator reads the
harmonised output CSV and produces:
- A **summary CSV** with aggregate statistics per correction/warning category.
- A **warnings CSV** mapping original values to the warning labels raised.
- An **errors CSV** mapping original values to the corrected form (substitution).

---

## Architecture

All evaluators inherit from the `Evaluation` base class ([`evaluation_base.py`](evaluation_base.py)).

```
Evaluation (base class — evaluation_base.py)
│
├── PersonNameEvaluation       (actor_name_evaluation.py)
├── ActorDatesEvaluation       (actor_dates_evaluation.py)
├── ExternalLinksEvaluation    (external_links_evaluation.py)
├── PublicationPlaceEvaluation (publication_place_evaluation.py)
├── PublisherEvaluation        (publisher_evaluation.py)
└── LanguageEvaluation         (language_evaluation.py)
```

The base class provides:
- CSV/ZIP reading logic (`_iter_csv_readers`)
- Row-level iteration with progress bar
- Output writing for all three report types

Child classes only need to implement `evaluate_value(value)` which returns:
- `warnings: List[str]` — non-critical issues
- `errors: Dict[str, str]` — critical issues with suggested substitution value

---

## Files

| File | Field(s) | Status |
|------|----------|--------|
| [`evaluation_base.py`](evaluation_base.py) | — | ✅ Complete |
| [`actor_name_evaluation.py`](actor_name_evaluation.py) | `actor_name`, `actor_first_name`, `actor_last_name` | ✅ Complete |
| [`actor_dates_evaluation.py`](actor_dates_evaluation.py) | `actor_birth`, `actor_death`, `actor_start`, `actor_end` | 🔄 Skeleton — awaiting normaliser schema |
| [`external_links_evaluation.py`](external_links_evaluation.py) | `actor_link_close`, `actor_link_exact` | 🔄 Skeleton |
| [`publication_place_evaluation.py`](publication_place_evaluation.py) | `publication_place` | 🔄 Skeleton |
| [`publisher_evaluation.py`](publisher_evaluation.py) | `publisher_1` / `publisher_harmonised` | 🔄 Skeleton |
| [`language_evaluation.py`](language_evaluation.py) | `language` / `language_harmonised` | 🔄 Skeleton |
| [`run_evaluation.py`](run_evaluation.py) | All | ✅ Dispatcher — routes column name to evaluator |
| [`names_with_multiple_ids.py`](names_with_multiple_ids.py) | `actor_name` | ✅ Existing utility |

> **Legend:** ✅ Complete · 🔄 Skeleton (implement once corresponding normaliser is ready) · 📋 Planned

---

## Running an Evaluation

```bash
# From the project root, using the module dispatcher:
python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    <path_to_harmonised_csv_or_zip> \
    --column <column_name> \
    [--output_dir <output_directory>]

# Examples:
python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    data/actor_data.zip --column actor_name

python -m 04_harmonisation_and_evaluation.02_evaluation.run_evaluation \
    04_harmonisation_and_evaluation/01_harmonisation/language/01_heuristic_rules/language_harmonised.csv \
    --column language_harmonised \
    --output_dir 04_harmonisation_and_evaluation/02_evaluation/output_reports/
```

---

## Output Reports

All output CSVs are written to `output_reports/` by default.

| File pattern | Content |
|---|---|
| `<field>_summary.csv` | Case label · case type (warning/error) · count · percentage |
| `<field>_warnings.csv` | Original value · warning labels · total occurrences |
| `<field>_errors.csv` | Original value · error labels · suggested substitution · occurrences |

---

## Extending with a New Evaluator

1. Create `<field>_evaluation.py` in this folder.
2. Subclass `Evaluation` and implement `evaluate_value()`.
3. Register the new evaluator and its target column names in `run_evaluation.py`.
4. Export it from `__init__.py`.
