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

Known-domain list verified against the real raw dataset (see
01_harmonisation/external_links/01_heuristic_rules/external_links_normaliser.py's
AUTHORITY_TABLE and module docstring): 23 distinct domains found across
551,622 rows, 0 exceptions to the RDF '<...>' wrapper convention. This
evaluator is meant to run against the normaliser's link_harmonised output
(wrapper already stripped), not the raw wrapped values.
"""

from typing import Optional, Tuple, List, Dict
import re
from urllib.parse import urlparse

from .evaluation_base import Evaluation


# Known external authority domains — kept in sync with
# external_links_normaliser.py's AUTHORITY_TABLE (all 23 domains actually
# observed in the raw dataset; see that module's docstring).
KNOWN_AUTHORITY_DOMAINS = {
    "viaf.org",
    "wikidata.org",
    "isni.org",
    "id.loc.gov",
    "d-nb.info",
    "www.idref.fr",
    "datos.bne.es",
    "fr.wikipedia.org",
    "data.biblissima.fr",
    "fr.dbpedia.org",
    "imslp.org",
    "francearchives.gouv.fr",
    "musicbrainz.org",
    "www.persee.fr",
    "data.persee.fr",
    "sws.geonames.org",
    "www.insee.fr",
    "www.siv.archives-nationales.culture.gouv.fr",
    "www.pop.culture.gouv.fr",
    "aims.fao.org",
    "purl.org",
    "orcid.org",
}

# Authorities directly observed with BOTH http and https in the raw dataset
# (see external_links_normaliser.py's SCHEME_UPGRADE_DOMAINS) — every other
# known authority above is observed with exactly one scheme only, so it is
# NOT flagged here as "should be https" without that evidence.
HTTPS_ONLY_AUTHORITIES = {
    "fr.wikipedia.org",
    "imslp.org",
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
        self, value: Optional[str], row: Optional[Dict[str, str]] = None
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
