#!/usr/bin/env python3
"""
external_links_normaliser.py  —  Module 04, external_links heuristic rules.

Scope of this implementation
-----------------------------
Normalises actor_link_close and actor_link_exact (external authority links
on BnF actor records).

IMPORTANT — this supersedes the free-text anomaly categories speculated in
this module's original placeholder docstring and in the module README: a
full scan of the real raw dataset (01_data_retrieval/02_actors/actors_data/
actor_data.csv, 551,622 rows) found a much simpler and more regular picture
than what was speculated:

  - EVERY non-empty value is wrapped in RDF angle brackets, e.g.
    "<http://viaf.org/viaf/23356192/>" — 0/551,622 exceptions. Stripping
    this wrapper is the single most important normalisation step, and it
    was not mentioned anywhere in the original plan.
  - There are NO multi-value cells (no ';' or '|' separators) anywhere in
    either field. This is expected, not a gap: the module README already
    documents that a single actor may appear on multiple raw rows because
    skos:exactMatch/closeMatch return one SPARQL binding per value — i.e.
    multiplicity already lives at the ROW level, not within a cell. The
    originally planned "multi-value splitter" step is therefore
    unnecessary and was not implemented.
  - Only 23 distinct domains occur in total (VIAF, Wikidata, ISNI, LC
    Name Authority, DNB/GND, IdRef, BNE, Wikipedia, DBpedia, IMSLP,
    MusicBrainz, Biblissima, FranceArchives, Persee, GeoNames, INSEE,
    Archives Nationales, POP-Culture, FAO-AIMS, PURL, ORCID — see
    AUTHORITY_TABLE below). Of those, only fr.wikipedia.org and imslp.org
    show BOTH http and https in the actual data — direct evidence both
    schemes resolve for those two hosts, so only those two get an
    evidence-backed https upgrade. Every other domain (viaf.org,
    wikidata.org, isni.org, id.loc.gov, d-nb.info, www.idref.fr,
    datos.bne.es, etc.) is observed with exactly ONE scheme only in this
    dataset — upgrading those to https without direct evidence would be
    guessing, not harmonising, so they are left as-is. Same principle
    dates_normaliser.py already established for BCE offsets: don't invent
    something the source doesn't already demonstrate.
  - A real malformed pattern exists: "<://43102>" (empty scheme AND empty
    host, just a bare number after "://") — several thousand occurrences.
    This is flagged as its own 'malformed' category rather than silently
    passed through or crashing the URI parser.
  - www.idref.fr always carries the "www." prefix; no bare "idref.fr" form
    is present in the data, so there is no www-prefix inconsistency to fix
    for it currently (contrary to the original plan's speculation).

Only ONE rule is implemented: strip the RDF wrapper, parse the URI,
classify against the known-authority table, and evidence-backed scheme
upgrade for the two hosts that demonstrably support both schemes. No LLM
step is implemented or planned — see 04_harmonisation_and_evaluation/
README.md section 3.3 ("No LLM approach planned"): a link is either a
structurally resolvable URI against a known authority or it isn't; there is
no ambiguous natural-language judgement call for an LLM to add here, unlike
actor_dates' non_parseable residual.

Input
-----
Raw actor dataset (CSV, or ZIP containing one or more CSVs) with columns:
    actor, actor_link_close, actor_link_exact
e.g. 01_data_retrieval/02_actors/actors_data/actor_data.csv (module 1's raw
acquisition output).

Unlike actor_dates (where the same value repeats identically across an
actor's raw rows and is deduplicated to one canonical value per actor),
actor_link_close/actor_link_exact are inherently one row per DISTINCT value
(see the row-multiplicity note above) — so this script collects each
actor's full set of distinct values per field, instead of "first value
seen".

Output (external_links_harmonised.csv)
----------------------------------------
One row per (actor_uri, field, distinct raw value) actually present in the
source — there is no "missing" placeholder row the way actor_dates emits
one per field per actor, because an actor simply has zero rows for a field
it has no links for; that already matches the source's own row-per-value
model:

    actor_uri | field | link_original | link_harmonised | authority | correction_type | confidence

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by dates_normaliser.py: one checkpoint every
MONITOR_CHECKPOINT_EVERY (1,000) actors and at the last one, plus a final
checkpoint on completion. Reports land in
00_monitor/report/external_links_normaliser_<timestamp>_py.txt. Disable
with --no-monitor.

Usage
-----
python external_links_normaliser.py \\
    --input  01_data_retrieval/02_actors/actors_data/actor_data.csv \\
    --output 04_harmonisation_and_evaluation/01_harmonisation/external_links/01_heuristic_rules/output

# disable the monitor report
python external_links_normaliser.py --no-monitor
"""

import os, csv, sys, zipfile, argparse, importlib.util
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) used below, raising
# UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)

INPUT_DEFAULT = "01_data_retrieval/02_actors/actors_data/actor_data.csv"
OUTPUT_DIR_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/external_links/01_heuristic_rules/output"
)
OUTPUT_FILENAME_DEFAULT = "external_links_harmonised.csv"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per record cost ~55 ms each (mostly the nvidia-smi GPU read),
# about two hours over 124,695 actors; checkpoint every N records plus the
# last one instead, like 06_mapping/05_map_estc_actors.py.
MONITOR_CHECKPOINT_EVERY = 1_000

LINK_FIELDS = ["actor_link_close", "actor_link_exact"]

OUTPUT_FIELDS = [
    "actor_uri", "field", "link_original", "link_harmonised",
    "authority", "correction_type", "confidence",
]

# ── Known authority domains ──────────────────────────────────────────────
#
# Every domain below was found in the real raw dataset (see module
# docstring) — this is not a guessed or aspirational list. domain (lower-
# case netloc) -> human-readable authority name.
AUTHORITY_TABLE = {
    "viaf.org": "VIAF",
    "wikidata.org": "Wikidata",
    "isni.org": "ISNI",
    "id.loc.gov": "LC Name Authority",
    "d-nb.info": "DNB (GND)",
    "www.idref.fr": "IdRef",
    "datos.bne.es": "BNE",
    "fr.wikipedia.org": "Wikipedia (fr)",
    "data.biblissima.fr": "Biblissima",
    "fr.dbpedia.org": "DBpedia (fr)",
    "imslp.org": "IMSLP",
    "francearchives.gouv.fr": "FranceArchives",
    "musicbrainz.org": "MusicBrainz",
    "www.persee.fr": "Persee",
    "data.persee.fr": "Persee (data)",
    "sws.geonames.org": "GeoNames",
    "www.insee.fr": "INSEE",
    "www.siv.archives-nationales.culture.gouv.fr": "Archives Nationales",
    "www.pop.culture.gouv.fr": "POP (Culture)",
    "aims.fao.org": "FAO AIMS",
    "purl.org": "PURL",
    "orcid.org": "ORCID",
}

# Domains directly observed with BOTH http and https in the raw dataset —
# see module docstring. Only these get an evidence-backed scheme upgrade.
SCHEME_UPGRADE_DOMAINS = {"fr.wikipedia.org", "imslp.org"}


def strip_wrapping(raw_value: str) -> str:
    """Remove the RDF '<...>' wrapper the source always uses. Defensive
    fallback (return unchanged) for the hypothetical case of an unwrapped
    value, even though none were observed in the real dataset."""
    if raw_value.startswith("<") and raw_value.endswith(">"):
        return raw_value[1:-1]
    return raw_value


def normalise_link(raw_value: str) -> dict:
    """
    Normalise a single external-link value (already normalise()'d, i.e. NA
    markers already reduced to "").

    Categories:
        missing              - no value at all
        malformed             - RDF-unwrapped value has no scheme and/or no
                                host, e.g. "<://43102>" (real pattern found
                                in the raw dataset, ~thousands of rows)
        scheme_upgraded_https - domain is one of the two hosts directly
                                observed with both http and https in the
                                raw data (SCHEME_UPGRADE_DOMAINS); upgraded
                                to https
        passthrough           - well-formed URI, known authority domain,
                                single scheme already observed for it in
                                the data -> left unchanged
        unknown_authority     - well-formed URI, but domain not in
                                AUTHORITY_TABLE (medium confidence: still a
                                usable link, just not one of the 23 known
                                authorities)

    Returns: { 'harmonised': str, 'authority': str, 'correction_type': str, 'confidence': str }
    """
    if not raw_value:
        return {"harmonised": "", "authority": "", "correction_type": "missing", "confidence": "low"}

    inner = strip_wrapping(raw_value)
    parsed = urlparse(inner)

    if not parsed.scheme or not parsed.netloc:
        # e.g. "://43102" — a real, structurally unresolvable pattern in
        # the source, not a value to guess a fix for.
        return {"harmonised": "", "authority": "", "correction_type": "malformed", "confidence": "low"}

    domain = parsed.netloc.lower()
    authority = AUTHORITY_TABLE.get(domain, "")

    if domain in SCHEME_UPGRADE_DOMAINS and parsed.scheme == "http":
        harmonised = urlunparse(parsed._replace(scheme="https", netloc=domain))
        return {
            "harmonised": harmonised, "authority": authority,
            "correction_type": "scheme_upgraded_https", "confidence": "high",
        }

    harmonised = urlunparse(parsed._replace(netloc=domain))
    if authority:
        return {
            "harmonised": harmonised, "authority": authority,
            "correction_type": "passthrough", "confidence": "high",
        }
    return {
        "harmonised": harmonised, "authority": "",
        "correction_type": "unknown_authority", "confidence": "medium",
    }


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring dates_normaliser.py."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_external_links_normaliser", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, actor_uri):
    if monitor_module is None:
        return monitor_state
    if index % MONITOR_CHECKPOINT_EVERY and index != total:
        return monitor_state
    context = f"Processed actor {actor_uri} (index {index}/{total})"
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def iter_actor_rows(path: str):
    """Yield row dicts from a plain CSV, or from every CSV inside a ZIP."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name, "r") as f:
                    lines = (line.decode("utf-8", errors="replace") for line in f)
                    yield from csv.DictReader(lines)
    else:
        with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
            yield from csv.DictReader(f)


def collect_actor_links(input_path: str) -> dict[str, dict[str, set]]:
    """
    Collect each actor's full DISTINCT set of raw values per link field.
    Unlike collect_unique_actor_dates() in dates_normaliser.py (dedupe to
    first non-empty value, since a date repeats identically across an
    actor's raw rows), every row here already carries its own distinct
    link value (see module docstring), so all of them must be kept.
    """
    actors: dict[str, dict[str, set]] = {}
    for row in iter_actor_rows(input_path):
        actor_uri = normalise(row.get("actor", ""))
        if not actor_uri:
            continue
        entry = actors.setdefault(actor_uri, {field: set() for field in LINK_FIELDS})
        for field in LINK_FIELDS:
            val = normalise(row.get(field, ""))
            if val:
                entry[field].add(val)
    return actors


def run(input_path: str, output_dir: str,
       output_filename: str = OUTPUT_FILENAME_DEFAULT,
       use_monitor: bool = False,
       monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> str:
    """
    Load the input CSV/ZIP, apply normalise_link() to each actor's distinct
    link values, and write the output mapping CSV. Returns the output file
    path.
    """
    actors = collect_actor_links(input_path)
    total = len(actors)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    stats = {"passthrough": 0, "scheme_upgraded_https": 0,
             "unknown_authority": 0, "malformed": 0, "missing": 0}
    rows_written = 0

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during external_links_normaliser.py execution",
            print_start_message=True,
        )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, (actor_uri, fields) in enumerate(sorted(actors.items())):
            for field in LINK_FIELDS:
                for value in sorted(fields[field]):
                    result = normalise_link(value)
                    stats[result["correction_type"]] += 1
                    writer.writerow({
                        "actor_uri": actor_uri,
                        "field": field,
                        "link_original": value,
                        "link_harmonised": result["harmonised"],
                        "authority": result["authority"],
                        "correction_type": result["correction_type"],
                        "confidence": result["confidence"],
                    })
                    rows_written += 1
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i + 1, total, actor_uri)

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed external_links harmonisation run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Wrote {rows_written:,} link values across {total:,} actors -> {output_path}")
    for correction_type, count in stats.items():
        print(f"  {correction_type:<22}: {count:,}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="external_links heuristic normaliser "
                    "(RDF-wrapper stripping + known-authority classification; "
                    "see module docstring). No LLM step (see README).")
    parser.add_argument("--input", default=INPUT_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Output directory")
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()

    run(args.input, args.output, args.output_filename,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
