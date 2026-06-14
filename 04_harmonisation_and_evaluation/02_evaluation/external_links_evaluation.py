"""
external_links_evaluation.py

Evaluator for the actor_link_close and actor_link_exact fields.

Produces a mapping between original raw values and the harmonised URIs
output by external_links_normaliser (01_harmonisation/external_links/).

Validation logic:
  - Verifies that harmonised values are well-formed URIs.
  - Checks that the URI domain matches a known authority (VIAF, Wikidata,
    ISNI, LC Name Authority, etc.).
  - Flags values that are not URIs (free-text, local IDs).
  - Flags http:// that should be https:// for known authorities.
  - Flags deprecated VIAF cluster URIs (if lookup table is available).

Output files (in output_reports/):
    external_links_summary.csv
    external_links_warnings.csv
    external_links_errors.csv

[TODO] This evaluator is a placeholder. The evaluate_value() method contains
       a skeleton implementation. Full validation requires the lookup table
       of known authority URI patterns to be finalised.
"""

from typing import Optional, Tuple, List, Dict
import re
from urllib.parse import urlparse

from .evaluation_base import Evaluation


# Known external authority domains (extend as needed)
KNOWN_AUTHORITY_DOMAINS = {
    "viaf.org",
    "www.wikidata.org",
    "id.loc.gov",
    "isni.org",
    "www.isni.org",
    "dbpedia.org",
    "data.bnf.fr",
    "d-nb.info",
    "catalogue.bnf.fr",
}

# Authorities that should use HTTPS
HTTPS_ONLY_AUTHORITIES = {
    "www.wikidata.org",
    "viaf.org",
    "isni.org",
    "www.isni.org",
}


class ExternalLinksEvaluation(Evaluation):
    """
    Evaluator for external link fields (actor_link_close, actor_link_exact).

    Reads the harmonised external links CSV and checks each value for:
      - URI well-formedness
      - Known authority compliance
      - Scheme (http vs https) correctness
    """

    URI_RE = re.compile(r"^https?://\S+$")

    def __init__(
        self,
        csv_filepath: str,
        field_name: str = "link_harmonised",
        config_path: Optional[str] = None,
    ):
        if config_path is None:
            config = {
                "field": field_name,
                "warning": [
                    "insecure_http_for_known_authority",
                    "unknown_authority_domain",
                    "www_prefix_variant",
                ],
                "error": [
                    "not_a_uri",
                    "missing_value",
                    "multi_value_not_split",
                ],
            }
        else:
            import json
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

        super().__init__(config, csv_filepath, field_name=field_name)

    def evaluate_value(
        self, value: Optional[str]
    ) -> Tuple[List[str], Dict[str, str]]:
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        if value is None or str(value).strip() == "":
            errors["missing_value"] = ""
            return warnings, errors

        stripped = str(value).strip()

        # Detect multi-value cells not yet split
        if ";" in stripped or "|" in stripped:
            errors["multi_value_not_split"] = ""
            return warnings, errors

        # Check URI well-formedness
        if not self.URI_RE.match(stripped):
            errors["not_a_uri"] = ""
            return warnings, errors

        parsed = urlparse(stripped)
        domain = parsed.netloc.lower()

        # Check authority domain
        if domain not in KNOWN_AUTHORITY_DOMAINS:
            warnings.append("unknown_authority_domain")

        # Check scheme for known authorities that require HTTPS
        if domain in HTTPS_ONLY_AUTHORITIES and parsed.scheme == "http":
            corrected = stripped.replace("http://", "https://", 1)
            warnings.append("insecure_http_for_known_authority")

        # Check www-prefix variants
        if domain.startswith("www.") and domain[4:] in KNOWN_AUTHORITY_DOMAINS:
            warnings.append("www_prefix_variant")

        return warnings, errors
