# run_evaluation.py
import argparse
import os

from person_name_evaluation import PersonNameEvaluation


VALID_PERSON_COLUMNS = {
    "actor_name",
    "actor_first_name",
    "actor_last_name",
}


def main():
    parser = argparse.ArgumentParser(description="Run field evaluation on CSV/ZIP file.")
    parser.add_argument("input_file", help="Percorso al CSV o ZIP da valutare")
    parser.add_argument(
        "--column",
        "-c",
        required=True,
        help="Nome della colonna del CSV su cui eseguire la valutazione",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Cartella di output (opzionale). Se non indicata usa output_reports/",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Percorso al file JSON di configurazione (opzionale)",
    )

    args = parser.parse_args()

    column = args.column

    # dispatcher semplice: in futuro puoi estenderlo con altri evaluator
    if column in VALID_PERSON_COLUMNS:
        evaluator = PersonNameEvaluation(
            csv_filepath=args.input_file,
            csv_field_name=column,
            config_path=args.config,
        )
    else:
        raise ValueError(
            f"Nessun evaluator configurato per la colonna '{column}'. "
            f"Per ora sono supportate: {', '.join(sorted(VALID_PERSON_COLUMNS))}"
        )

    evaluator.run(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
