"""
02_evaluation package

Provides field-specific evaluators that inherit from the Evaluation base class.
Each evaluator reads the harmonised output of the corresponding normaliser
(01_harmonisation/<field>/) and produces:
  - A summary CSV with aggregate statistics per correction category.
  - A warnings CSV with original→harmonised mappings for warning cases.
  - An errors CSV with original→harmonised mappings and suggested substitutions.

Available evaluators:
    PersonNameEvaluation      → actor_name, actor_first_name, actor_last_name
    ActorDatesEvaluation      → actor_birth, actor_death, actor_start, actor_end
    ExternalLinksEvaluation   → actor_link_close, actor_link_exact
    PublicationPlaceEvaluation → publication_place
    PublisherEvaluation       → publisher_1 / publisher_harmonised
    LanguageEvaluation        → language / language_harmonised
"""

from .evaluation_base import Evaluation, CaseConfig
from .actor_name_evaluation import PersonNameEvaluation
from .actor_dates_evaluation import ActorDatesEvaluation
from .external_links_evaluation import ExternalLinksEvaluation
from .publication_place_evaluation import PublicationPlaceEvaluation
from .publisher_evaluation import PublisherEvaluation
from .language_evaluation import LanguageEvaluation

__all__ = [
    "Evaluation",
    "CaseConfig",
    "PersonNameEvaluation",
    "ActorDatesEvaluation",
    "ExternalLinksEvaluation",
    "PublicationPlaceEvaluation",
    "PublisherEvaluation",
    "LanguageEvaluation",
]
