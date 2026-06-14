# run_evaluation.py
"""
Dispatcher script for running field-specific evaluators.

Usage:
    python -m 02_evaluation.run_evaluation <input_file> --column <col> [--output_dir <dir>]

Supported columns and their evaluators:
    actor_name, actor_first_name, actor_last_name  →  ActorNameEvaluation (PersonNameEvaluation)
    actor_birth, actor_death, actor_start, actor_end → ActorDatesEvaluation
    actor_link_close, actor_link_exact              →  ExternalLinksEvaluation
    publication_place                               →  PublicationPlaceEvaluation
    publisher_harmonised                            →  PublisherEvaluation
    language_harmonised                             →  LanguageEvaluation
"""
import argparse
import os

from .actor_name_evaluation import PersonNameEvaluation
from .actor_dates_evaluation import ActorDatesEvaluation
from .external_links_evaluation import ExternalLinksEvaluation
from .publication_place_evaluation import PublicationPlaceEvaluation
from .publisher_evaluation import PublisherEvaluation
from .language_evaluation import LanguageEvaluation


PERSON_NAME_COLUMNS = {"actor_name", "actor_first_name", "actor_last_name"}
DATE_COLUMNS = {"actor_birth", "actor_death", "actor_start", "actor_end", "date_harmonised"}
LINK_COLUMNS = {"actor_link_close", "actor_link_exact", "link_harmonised"}
PLACE_COLUMNS = {"publication_place", "place_original"}
PUBLISHER_COLUMNS = {"publisher_1", "publisher_harmonised"}
LANGUAGE_COLUMNS = {"language", "language_harmonised"}


def main():
    parser = argparse.ArgumentParser(
        description="Run field evaluation on CSV/ZIP file."
    )
    parser.add_argument("input_file", help="Path to the CSV or ZIP to evaluate")
    parser.add_argument(
        "--column", "-c", required=True,
        help="Name of the column to evaluate",
    )
    parser.add_argument(
        "--output_dir", default=None,
        help="Output directory (default: output_reports/)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to JSON config file (optional)",
    )

    args = parser.parse_args()
    column = args.column

    if column in PERSON_NAME_COLUMNS:
        evaluator = PersonNameEvaluation(
            csv_filepath=args.input_file,
            csv_field_name=column,
            config_path=args.config,
        )
    elif column in DATE_COLUMNS:
        evaluator = ActorDatesEvaluation(
            csv_filepath=args.input_file,
            field_name=column,
            config_path=args.config,
        )
    elif column in LINK_COLUMNS:
        evaluator = ExternalLinksEvaluation(
            csv_filepath=args.input_file,
            field_name=column,
            config_path=args.config,
        )
    elif column in PLACE_COLUMNS:
        evaluator = PublicationPlaceEvaluation(
            csv_filepath=args.input_file,
            field_name=column,
            config_path=args.config,
        )
    elif column in PUBLISHER_COLUMNS:
        evaluator = PublisherEvaluation(
            csv_filepath=args.input_file,
            field_name=column,
            config_path=args.config,
        )
    elif column in LANGUAGE_COLUMNS:
        evaluator = LanguageEvaluation(
            csv_filepath=args.input_file,
            field_name=column,
            config_path=args.config,
        )
    else:
        supported = sorted(
            PERSON_NAME_COLUMNS | DATE_COLUMNS | LINK_COLUMNS |
            PLACE_COLUMNS | PUBLISHER_COLUMNS | LANGUAGE_COLUMNS
        )
        raise ValueError(
            f"No evaluator configured for column '{column}'.\n"
            f"Supported columns: {', '.join(supported)}"
        )

    evaluator.run(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
