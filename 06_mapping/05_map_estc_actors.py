#!/usr/bin/env python3
"""
05_map_estc_actors.py  —  Module 06, Step 5
BnF actors → ESTC actor-authority matching (author-level overlap).

Background
----------
Unlike 03_map_estc_ecco.py (edition-level: matches BnF *editions* against
ESTC bibliographic records and detects translations), this script matches
BnF *actors* directly against the ESTC actor-authority table produced by the
COMHIS `estcr` R package (https://github.com/COMHIS/estcr):

    estc_actors.csv       — one row per ESTC actor (this script's input)
    estc_core.csv          — ESTC edition/record data (not needed here)
    estc_actor_links.csv   — actor<->edition crosswalk (not needed here)

This is the requested "author-level overlap" product: it can be produced
before the full edition/translation pipeline, since it only needs the two
actor tables, not editions.

Algorithm
---------
Pass 1 — VIAF ID bridge (lossless):
    Both BnF actors (actor_link_exact / actor_link_close, ";"-split) and
    ESTC actors (viaf_link, or actor_id when actor_id_type == "viaf") can
    carry a VIAF URI. A shared numeric VIAF ID is treated as certain
    identity — match_type = "viaf_id", confidence = 1.0. In addition to
    whatever VIAF IDs are already in the raw BnF data, 01_map_viaf.py's
    output (viaf_mapping.csv) supplies further IDs it resolved via
    name-based SRU search — see "VIAF-mapping enrichment" below.

Pass 2 — Name-token + date fallback (for actors with no VIAF match):
    Name comparison is ORDER-INVARIANT by design: BnF actor_name is
    typically "Given Family" while ESTC name_unified is typically the
    library-authority "Family, Given" — comparing raw strings would treat
    identical names as different. Both sides are instead reduced to a
    normalised TOKEN SET (name_tokens()), preferring structured
    first/last-name fields when available on both datasets, falling back to
    the free-text actor_name / name_unified field otherwise. Two records
    with the same token set are blocked together.

    Within a token-set block, birth/death years (extracted from BnF's EDTF-
    ish date fields and ESTC's year_birth/year_death) are compared with a
    ±`--year-window` (default 2) tolerance, exactly as in 02_map_wikidata.py:
    - both sides have a comparable year and it falls outside the window →
      that candidate is discarded (conflicting lifespan: same name, almost
      certainly a different person);
    - at least one comparable year pair, all within window → accepted;
    - no comparable year pair at all (dates missing on one or both sides)
      → neither accepted nor discarded — "no evidence either way".

    Resolution per BnF actor, mirroring this module's established
    ambiguous_* handling (see 03_map_estc_ecco.py's ambiguous_translation
    and actors_deduplication.py's ambiguous_name_only — never silently
    guess when evidence doesn't clearly point to one candidate):
        exactly one accepted candidate   -> match_type = "name_and_dates"
        more than one accepted candidate -> match_type = "ambiguous_name_and_dates"
        zero accepted, some "no evidence" candidates remain
                                          -> match_type = "ambiguous_name_only"
        zero accepted, none remain (every same-name candidate had
        conflicting dates), or no name-token block at all
                                          -> match_type = "unmatched"

ESTC actor rows with is_organization == TRUE are excluded from the
candidate pool (this script matches persons; corporate/organisational
authors are out of scope here).

VIAF-mapping enrichment (pre-processing)
-----------------------------------------
01_map_viaf.py can resolve a VIAF ID for a BnF actor via name-based SRU
search even when the raw BnF record carries none in actor_link_exact/close.
Its output (viaf_mapping.csv) is fed in as an additional per-BnF_ID VIAF-ID
source for Pass 1 — the same additional-ID-source role viaf_mapping.csv
already plays for 02_map_wikidata.py. Enabled by default from the CLI
(--viaf-mapping, defaulting to that script's real output path); off by
default when run_mapping(...) is called programmatically. A missing
mapping file is not an error: matching simply relies only on the VIAF IDs
already present in the BnF data.

Deduplication (post-processing)
--------------------------------
Each BnF actor row is matched independently, so a BnF actor duplicated
under two or more distinct URIs (see actors_deduplication.py) would
otherwise appear as separate, possibly conflicting rows in the output.
collapse_by_canonical() folds duplicates identified by that script's
actor_dedup_mapping.csv onto a single row per canonical actor, keeping
whichever duplicate found the highest-confidence match (ranked by
MATCH_TYPE_PRIORITY). Enabled by default from the CLI (--dedup-mapping,
defaulting to that script's real output path); off by default when
run_mapping(...) is called programmatically, matching this module's
monitoring convention (see below) — pass a path explicitly to enable it.
A missing mapping file is not an error: collapsing is silently skipped.

Input
-----
- BnF actors dataset: any CSV with the module-4 ready-dataset schema
  (id column "actor") or the module-5 optimised-subset schema (id column
  "BnF_ID") — both accepted, same dual-schema handling as
  actors_deduplication.py. Point --bnf-actors at a year-filtered subset
  (e.g. 05_subset_optimisation/output/bnf_actors_optimised.csv) to scope
  the run to a period of interest.
- ESTC actors table: data/estc/estc_actors.csv (COMHIS estcr export). This
  script places no assumption on how complete that table is — pointing
  --estc-actors at a sample vs. the full COMHIS export changes nothing
  about how it runs, only how many candidates it can find.

Output
------
The ESTC tables are licensed COMHIS data that may not be published, so the
files in 06_mapping/output/ (tracked in git) carry only what the match
itself needs, for actors with a match or an ambiguous candidate (one row per
DISTINCT actor once duplicates are collapsed; no "unmatched" rows):
    PUBLIC_FIELDS = BnF_ID, estc_actor_id, estc_actor_name, bnf_birth_year,
    bnf_death_year, estc_birth_year, estc_death_year, match_type, confidence
(the four years are the dates the name + dates pass compares).

- 06_mapping/output/estc_actor_mapping.csv — confident and ambiguous rows.
- 06_mapping/output/estc_actor_mapping_confident.csv — CONFIDENT_MATCH_TYPES
  only (viaf_id, name_and_dates): safe to use directly.
- 06_mapping/output/estc_actor_mapping_review.csv — REVIEW_MATCH_TYPES only
  (ambiguous_name_only, ambiguous_name_and_dates): needs a human to confirm
  or reject before use. An ambiguous_name_only row names no ESTC candidate.

The full mapping (every distinct actor including "unmatched", with all
OUTPUT_FIELDS: also bnf_actor_name, estc_viaf_link and notes listing the
alternative candidates) goes to --full-output, by default
data/estc/derived/estc_actor_mapping_full.csv, next to the ESTC tables and
git-ignored like them.

06_mapping/report/estc_actor_mapping_report.json: total_bnf_actor_records
(pre-dedup), distinct_actors_after_dedup, duplicates_collapsed, and
per-match_type counts (over the distinct/deduplicated actors).
estc_actor_mapping_report.txt: the same numbers as plain-language sentences
(template-filled, not LLM-generated).

Monitoring
----------
Same "embedded state-based monitoring" mechanism as module 1 and the rest
of 06_mapping (see 00_monitor/README.md): a checkpoint every
MONITOR_CHECKPOINT_EVERY (1,000) processed BnF actor records plus a final
checkpoint, on by default from the CLI (--no-monitor to disable), off by
default when run_mapping(...) is called programmatically.

Usage
-----
python 06_mapping/05_map_estc_actors.py \\
    --bnf-actors "05_subset_optimisation/output/bnf_actors_optimised.csv" \\
    --estc-actors data/estc/estc_actors.csv
"""

import os, csv, sys, json, re, argparse, importlib.util
from pathlib import Path
from typing import Optional

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

BNF_ACTORS_DEFAULT = "05_subset_optimisation/output/bnf_actors_optimised.csv"
ESTC_ACTORS_DEFAULT = "data/estc/estc_actors.csv"
OUTPUT_DEFAULT = "06_mapping/output/estc_actor_mapping.csv"
REPORT_DEFAULT = "06_mapping/report/estc_actor_mapping_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
YEAR_WINDOW_DEFAULT = 2
MONITOR_CHECKPOINT_EVERY = 1000

# 01_map_viaf.py's output: additional BnF_ID -> viaf_id source for Pass 1,
# beyond whatever VIAF IDs are already present in the raw BnF data.
VIAF_MAPPING_DEFAULT = "06_mapping/output/viaf_mapping.csv"

# Module 4's actors_deduplication.py output: actor_uri -> canonical_actor_uri
# for BnF actors identified as duplicates of each other. Applied by default
# so the overlap deliverable counts distinct real people, not raw BnF rows;
# silently skipped (a no-op) if the file doesn't exist yet.
DEDUP_MAPPING_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/"
    "01_heuristic_rules/output/actor_dedup_mapping.csv"
)

# Lower rank = higher confidence; used by collapse_by_canonical() to pick the
# single best match per canonical actor out of several duplicate BnF rows.
MATCH_TYPE_PRIORITY = {
    "viaf_id": 0,
    "name_and_dates": 1,
    "ambiguous_name_and_dates": 2,
    "ambiguous_name_only": 3,
    "unmatched": 4,
}

# match_type buckets for the confidence-tier split written alongside the
# full mapping (see split_by_confidence()): a "confident" file safe to use
# directly, and a "review" file of same-name candidates that need a human
# to confirm or reject before use. "unmatched" rows appear in neither split
# file (nothing to deliver or review) but remain in the full mapping CSV.
CONFIDENT_MATCH_TYPES = {"viaf_id", "name_and_dates"}
REVIEW_MATCH_TYPES = {"ambiguous_name_only", "ambiguous_name_and_dates"}

# Dual schema support: module 4's assemble_actors_ready.py ("actor") vs
# module 5's gen_subset_optm.py ("BnF_ID") — see actors_deduplication.py.
ACTOR_ID_COLUMNS = ["actor", "BnF_ID"]

OUTPUT_FIELDS = [
    "BnF_ID", "estc_actor_id", "match_type", "confidence",
    "bnf_actor_name", "estc_actor_name", "estc_viaf_link",
    "bnf_birth_year", "bnf_death_year", "estc_birth_year", "estc_death_year",
    "notes",
]
# Columns of the published files in 06_mapping/output/ (see "Output").
PUBLIC_FIELDS = [
    "BnF_ID", "estc_actor_id", "estc_actor_name",
    "bnf_birth_year", "bnf_death_year", "estc_birth_year", "estc_death_year",
    "match_type", "confidence",
]
FULL_OUTPUT_DEFAULT = "data/estc/derived/estc_actor_mapping_full.csv"

_name_norm_re = re.compile(r"[\s.,]+", re.UNICODE)


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    project_root = Path(__file__).resolve().parents[1]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_map_estc_actors", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, bnf_id, match_type):
    if monitor_module is None:
        return monitor_state
    context = f"Processed actor {bnf_id} (index {index}/{total}) - match_type={match_type}"
    return monitor_module.update_monitor_state(
        state=monitor_state, context=context, print_console=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() in {"NA", "N/A", "NULL", "NONE", ""} else s


def normalise_name(name: str) -> str:
    s = normalise(name)
    return _name_norm_re.sub(" ", s).strip().upper() if s else ""


def name_tokens(name: str) -> frozenset:
    n = normalise_name(name)
    return frozenset(n.split()) if n else frozenset()


def extract_year(s) -> Optional[int]:
    m = re.search(r"(\d{4})", normalise(s))
    return int(m.group(1)) if m else None


def extract_viaf_id(value: str) -> Optional[str]:
    m = re.search(r"viaf\.org/viaf/(\d+)", normalise(value))
    return m.group(1) if m else None


def get_actor_id(row: dict) -> str:
    for col in ACTOR_ID_COLUMNS:
        val = normalise(row.get(col, ""))
        if val:
            return val
    return ""


def bnf_viaf_ids(row: dict) -> set:
    ids = set()
    for col in ("actor_link_exact", "actor_link_close"):
        for v in normalise(row.get(col, "")).split(";"):
            vid = extract_viaf_id(v)
            if vid:
                ids.add(vid)
    return ids


def bnf_name_key(row: dict) -> frozenset:
    first, last = normalise(row.get("actor_first_name", "")), normalise(row.get("actor_last_name", ""))
    if first or last:
        tokens = name_tokens(f"{first} {last}")
        if tokens:
            return tokens
    return name_tokens(row.get("actor_name", ""))


def estc_name_key(row: dict) -> frozenset:
    first, last = normalise(row.get("name_first", "")), normalise(row.get("name_last", ""))
    if first or last:
        tokens = name_tokens(f"{first} {last}")
        if tokens:
            return tokens
    return name_tokens(row.get("name_unified", ""))


def estc_viaf_id(row: dict) -> Optional[str]:
    vid = extract_viaf_id(row.get("viaf_link", ""))
    if vid:
        return vid
    if normalise(row.get("actor_id_type", "")).lower() == "viaf":
        # actor_id for a VIAF-sourced ESTC actor is "viaf_<digits>", not a
        # viaf.org URL, so it needs its own pattern rather than
        # extract_viaf_id() (which matches viaf.org/viaf/<digits> URIs).
        m = re.match(r"viaf_(\d+)$", normalise(row.get("actor_id", "")))
        return m.group(1) if m else None
    return None


def dates_compatible(bnf_birth, bnf_death, estc_birth, estc_death, window: int) -> Optional[bool]:
    """
    True  -> at least one comparable year pair, all within `window`.
    False -> at least one comparable year pair falls outside `window`
             (conflicting lifespan; candidate should be discarded).
    None  -> no comparable year pair at all (no evidence either way).
    """
    pairs = [(bnf_birth, estc_birth), (bnf_death, estc_death)]
    comparable = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not comparable:
        return None
    return all(abs(a - b) <= window for a, b in comparable)


def load_bnf_actors(path: str) -> list:
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        rows = []
        for row in csv.DictReader(f):
            aid = get_actor_id(row)
            if not aid:
                continue
            if not normalise(row.get("actor", "")):
                row["actor"] = aid
            rows.append(row)
        return rows


def load_estc_actors(path: str) -> list:
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        rows = [row for row in csv.DictReader(f) if normalise(row.get("actor_id", ""))]
    return [row for row in rows if normalise(row.get("is_organization", "")).upper() != "TRUE"]


def load_viaf_mapping(path: str) -> dict:
    """BnF_ID -> viaf_id, from 01_map_viaf.py's output. 01_map_viaf.py can
    resolve a VIAF ID via name-based SRU search even when the raw BnF
    record has none in actor_link_exact/close, so this supplies additional
    VIAF IDs to match_actor()'s Pass 1 beyond what the BnF data alone
    carries — the same additional-ID-source role this file already plays
    for 02_map_wikidata.py. Missing file is not an error (that step may not
    have been run yet) — returns {} and no supplementary IDs are used."""
    if not path or not os.path.exists(path):
        print(f"  [info] No VIAF mapping found at {path!r}; "
             "matching will rely only on VIAF IDs already in the BnF data.")
        return {}
    mapping = {}
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            bnf_id = normalise(row.get("BnF_ID", ""))
            vid = normalise(row.get("viaf_id", ""))
            if bnf_id and vid:
                mapping[bnf_id] = vid
    return mapping


def load_dedup_mapping(path: str) -> dict:
    """actor_uri -> canonical_actor_uri, from actors_deduplication.py's
    output. Missing file is not an error (that step may not have been run
    yet) — returns {} and collapse_by_canonical() becomes a no-op."""
    if not path or not os.path.exists(path):
        print(f"  [info] No dedup mapping found at {path!r}; "
             "duplicate BnF actors (if any) will not be collapsed.")
        return {}
    mapping = {}
    with open(path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            uri = normalise(row.get("actor_uri", ""))
            canon = normalise(row.get("canonical_actor_uri", ""))
            if uri and canon:
                mapping[uri] = canon
    return mapping


def collapse_by_canonical(results: list, dedup_mapping: dict) -> list:
    """Collapse per-BnF-actor match results onto canonical actor identities
    using a dedup mapping (see actors_deduplication.py): several BnF URIs
    identified as the same real person are reduced to a single output row,
    keeping the single highest-confidence match found among them (ranked by
    MATCH_TYPE_PRIORITY, then by numeric confidence) rather than an
    arbitrary one. Actors absent from the mapping are unaffected (they map
    to themselves). A no-op when `dedup_mapping` is empty."""
    if not dedup_mapping:
        return results

    best: dict = {}
    for r in results:
        canon = dedup_mapping.get(r["BnF_ID"], r["BnF_ID"])
        current = best.get(canon)
        if current is None or (
            (MATCH_TYPE_PRIORITY.get(r["match_type"], 99),
             -r["confidence"]) <
            (MATCH_TYPE_PRIORITY.get(current["match_type"], 99),
             -current["confidence"])
        ):
            merged = dict(r)
            merged["BnF_ID"] = canon
            if canon != r["BnF_ID"]:
                extra = f"canonical form of duplicate {r['BnF_ID']}"
                merged["notes"] = f"{merged['notes']}; {extra}" if merged["notes"] else extra
            best[canon] = merged

    return sorted(best.values(), key=lambda r: r["BnF_ID"])


def split_by_confidence(results: list) -> tuple:
    """Split match results into (confident, review) lists by match_type —
    CONFIDENT_MATCH_TYPES (viaf_id, name_and_dates) vs REVIEW_MATCH_TYPES
    (the two ambiguous_* types). "unmatched" rows appear in neither: there
    is nothing to deliver or to review for an actor with no candidate at
    all. Order is preserved from `results`."""
    confident = [r for r in results if r["match_type"] in CONFIDENT_MATCH_TYPES]
    review = [r for r in results if r["match_type"] in REVIEW_MATCH_TYPES]
    return confident, review


def _with_suffix(path: str, suffix: str) -> str:
    root, ext = os.path.splitext(path)
    return f"{root}{suffix}{ext}"


def build_estc_indexes(estc_actors: list):
    viaf_index: dict = {}
    name_index: dict = {}
    for i, row in enumerate(estc_actors):
        vid = estc_viaf_id(row)
        if vid:
            viaf_index.setdefault(vid, []).append(i)
        key = estc_name_key(row)
        if key:
            name_index.setdefault(key, []).append(i)
    return viaf_index, name_index


def _build_result(bnf_id, bnf_name, bnf_birth, bnf_death, estc_row,
                  match_type, confidence, notes) -> dict:
    return {
        "BnF_ID": bnf_id,
        "estc_actor_id": normalise(estc_row.get("actor_id", "")) if estc_row else "",
        "match_type": match_type,
        "confidence": confidence,
        "bnf_actor_name": bnf_name,
        "estc_actor_name": normalise(estc_row.get("name_unified", "")) if estc_row else "",
        "estc_viaf_link": normalise(estc_row.get("viaf_link", "")) if estc_row else "",
        "bnf_birth_year": bnf_birth if bnf_birth is not None else "",
        "bnf_death_year": bnf_death if bnf_death is not None else "",
        "estc_birth_year": extract_year(estc_row.get("year_birth", "")) if estc_row else "",
        "estc_death_year": extract_year(estc_row.get("year_death", "")) if estc_row else "",
        "notes": notes,
    }


def match_actor(bnf_row: dict, viaf_index: dict, name_index: dict,
                estc_actors: list, year_window: int, viaf_mapping: dict = None) -> dict:
    bnf_id = normalise(bnf_row.get("actor", ""))
    bnf_name = normalise(bnf_row.get("actor_name", ""))
    bnf_birth = extract_year(bnf_row.get("actor_birth", ""))
    bnf_death = extract_year(bnf_row.get("actor_death", ""))

    candidate_viaf_ids = bnf_viaf_ids(bnf_row)
    if viaf_mapping:
        # 01_map_viaf.py can find a VIAF ID by name-based SRU search even
        # when the raw BnF record carries none in actor_link_exact/close —
        # the same additional-ID-source role viaf_mapping.csv already
        # plays for 02_map_wikidata.py.
        supplementary = normalise(viaf_mapping.get(bnf_id, ""))
        if supplementary:
            candidate_viaf_ids = candidate_viaf_ids | {supplementary}

    for vid in sorted(candidate_viaf_ids):
        if vid in viaf_index:
            idxs = viaf_index[vid]
            estc_row = estc_actors[idxs[0]]
            notes = "" if len(idxs) == 1 else (
                f"{len(idxs)} ESTC actor rows share VIAF {vid}; first taken")
            return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death,
                                 estc_row, "viaf_id", 1.0, notes)

    key = bnf_name_key(bnf_row)
    if not key or key not in name_index:
        return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death, None, "unmatched", 0.0, "")

    accepted = []
    any_no_evidence = False
    for idx in name_index[key]:
        estc_row = estc_actors[idx]
        estc_birth = extract_year(estc_row.get("year_birth", ""))
        estc_death = extract_year(estc_row.get("year_death", ""))
        compat = dates_compatible(bnf_birth, bnf_death, estc_birth, estc_death, year_window)
        if compat is True:
            accepted.append(estc_row)
        elif compat is None:
            any_no_evidence = True

    if len(accepted) == 1:
        return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death,
                             accepted[0], "name_and_dates", 0.9, "")
    if len(accepted) > 1:
        ids = ", ".join(sorted(normalise(r.get("actor_id", "")) for r in accepted))
        return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death, accepted[0],
                             "ambiguous_name_and_dates", 0.5,
                             f"{len(accepted)} ESTC actors match name+dates: {ids}")
    if any_no_evidence:
        return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death, None,
                             "ambiguous_name_only", 0.3, "")
    return _build_result(bnf_id, bnf_name, bnf_birth, bnf_death, None, "unmatched", 0.0, "")


def format_human_report(stats: dict, total: int, raw_total: int = None,
                        duplicates_collapsed: int = 0) -> str:
    """Plain-text, template-filled summary of one run — no LLM involved,
    just the same `stats` counts already computed by run_mapping() rendered
    as readable sentences. Written alongside the machine-readable JSON
    report on every run so a human can check the outcome without parsing
    JSON.

    `total` is the number of distinct actors the match-type breakdown is
    computed over (post actor-deduplication collapsing, if applied).
    `raw_total` (defaults to `total` when not given, i.e. no collapsing
    happened) is the number of BnF actor records originally read;
    `duplicates_collapsed` is how many of those were merged away."""
    if raw_total is None:
        raw_total = total

    lines = [
        "ESTC ACTOR-AUTHORITY MATCHING REPORT",
        "=" * 70,
        "",
        f"Total BnF actor records read      : {raw_total:,}",
    ]
    if duplicates_collapsed:
        lines.append(f"Duplicate records collapsed        : {duplicates_collapsed:,} "
                     "(via actor deduplication)")
    lines += [
        f"Distinct actors in this overlap    : {total:,}",
        "",
        "Match type breakdown:",
    ]
    for match_type, count in sorted(stats.items(), key=lambda x: -x[1]):
        pct = (count / total * 100) if total else 0.0
        lines.append(f"  {match_type:<28} {count:>8,}   ({pct:5.2f}%)")

    confident = sum(n for mt, n in stats.items() if mt in CONFIDENT_MATCH_TYPES)
    ambiguous = sum(n for mt, n in stats.items() if mt.startswith("ambiguous"))
    unmatched = stats.get("unmatched", 0)
    pct_confident = (confident / total * 100) if total else 0.0
    pct_ambiguous = (ambiguous / total * 100) if total else 0.0
    pct_unmatched = (unmatched / total * 100) if total else 0.0

    lines += [
        "",
        "Summary",
        "-" * 70,
        (
            f"Of the {total:,} distinct BnF actors in this overlap, {confident:,} "
            f"({pct_confident:.2f}%) were "
            "matched to an ESTC actor record with high confidence (a shared VIAF identifier, "
            "or a matching name together with matching birth/death dates). A further "
            f"{ambiguous:,} ({pct_ambiguous:.2f}%) actors share a name with an ESTC actor but "
            "could not be confirmed via dates and are flagged as ambiguous rather than matched. "
            f"The remaining {unmatched:,} ({pct_unmatched:.2f}%) actors had no candidate in the "
            "ESTC actor-authority table."
        ),
        "",
    ]
    return "\n".join(lines)


def run_mapping(bnf_path: str, estc_actors_path: str, output_path: str, report_path: str,
                year_window: int = YEAR_WINDOW_DEFAULT,
                dedup_mapping_path: str = None,
                viaf_mapping_path: str = None,
                use_monitor: bool = False, monitor_script: str = MONITOR_SCRIPT_DEFAULT,
                full_output_path: str = None) -> tuple:
    """
    full_output_path: where to write the full mapping (all actors, all
    OUTPUT_FIELDS); None writes none. The published output_path and its
    _confident / _review splits carry PUBLIC_FIELDS for matched and
    ambiguous actors only.
    dedup_mapping_path: path to actors_deduplication.py's actor_dedup_mapping.csv.
    viaf_mapping_path: path to 01_map_viaf.py's viaf_mapping.csv, supplying
    additional VIAF IDs for Pass 1 beyond what the raw BnF data carries.
    Both default to None (disabled) when called programmatically — matching
    this module's existing convention (e.g. monitoring also defaults off
    programmatically) — but the CLI defaults them to DEDUP_MAPPING_DEFAULT /
    VIAF_MAPPING_DEFAULT so a normal run uses both automatically.
    """
    bnf_actors = load_bnf_actors(bnf_path)
    estc_actors = load_estc_actors(estc_actors_path)
    viaf_index, name_index = build_estc_indexes(estc_actors)
    dedup_mapping = load_dedup_mapping(dedup_mapping_path) if dedup_mapping_path else {}
    viaf_mapping = load_viaf_mapping(viaf_mapping_path) if viaf_mapping_path else {}
    raw_total = len(bnf_actors)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during 05_map_estc_actors.py execution",
            print_start_message=True,
        )

    results = []
    for i, bnf_row in enumerate(bnf_actors, start=1):
        result = match_actor(bnf_row, viaf_index, name_index, estc_actors, year_window,
                             viaf_mapping=viaf_mapping)
        results.append(result)
        if i % MONITOR_CHECKPOINT_EVERY == 0 or i == raw_total:
            monitor_state = _monitor_checkpoint(
                monitor_module, monitor_state, i, raw_total, result["BnF_ID"], result["match_type"])

    results = collapse_by_canonical(results, dedup_mapping)
    total = len(results)
    duplicates_collapsed = raw_total - total

    stats: dict = {}
    for r in results:
        stats[r["match_type"]] = stats.get(r["match_type"], 0) + 1

    if full_output_path:
        os.makedirs(os.path.dirname(full_output_path) or ".", exist_ok=True)
        with open(full_output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(results)

    confident_rows, review_rows = split_by_confidence(results)
    matched_rows = [r for r in results if r["match_type"] != "unmatched"]
    output_confident_path = _with_suffix(output_path, "_confident")
    output_review_path = _with_suffix(output_path, "_review")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    for path, rows in ((output_path, matched_rows), (output_confident_path, confident_rows),
                       (output_review_path, review_rows)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PUBLIC_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_bnf_actor_records": raw_total,
            "distinct_actors_after_dedup": total,
            "duplicates_collapsed": duplicates_collapsed,
            "by_match_type": stats,
        }, f, ensure_ascii=False, indent=2)

    report_txt_path = os.path.splitext(report_path)[0] + ".txt"
    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(format_human_report(stats, total, raw_total, duplicates_collapsed))

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state, context="Completed ESTC actor mapping run", print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ BnF actor records read : {raw_total:,}")
    if duplicates_collapsed:
        print(f"  Collapsed to {total:,} distinct actors "
             f"({duplicates_collapsed:,} duplicates merged via actor deduplication)")
    for mt, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {mt:<28} {n:,}")
    if full_output_path:
        print(f"✓ Wrote full mapping      -> {full_output_path} (not published)")
    print(f"✓ Wrote matched subset    -> {output_path} ({len(matched_rows):,} rows)")
    print(f"✓ Wrote confident subset  -> {output_confident_path} ({len(confident_rows):,} rows)")
    print(f"✓ Wrote review subset     -> {output_review_path} ({len(review_rows):,} rows)")
    print(f"✓ Wrote report            -> {report_path}")
    print(f"✓ Wrote human-readable report -> {report_txt_path}")
    return output_path, report_path


def main():
    parser = argparse.ArgumentParser(
        description="BnF actors -> ESTC actor-authority matching (author-level overlap)")
    parser.add_argument("--bnf-actors", default=BNF_ACTORS_DEFAULT)
    parser.add_argument("--estc-actors", default=ESTC_ACTORS_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DEFAULT,
                        help="Published matched subset (PUBLIC_FIELDS); also writes "
                             "its _confident and _review splits.")
    parser.add_argument("--full-output", default=FULL_OUTPUT_DEFAULT,
                        help="Full mapping with every actor and column, kept out of git "
                             "next to the ESTC tables. Pass '' to skip.")
    parser.add_argument("--report", default=REPORT_DEFAULT)
    parser.add_argument("--year-window", type=int, default=YEAR_WINDOW_DEFAULT,
                        help="±years tolerance when comparing birth/death years.")
    parser.add_argument("--dedup-mapping", default=DEDUP_MAPPING_DEFAULT,
                        help="actors_deduplication.py output; collapses duplicate BnF "
                             "actors onto one row each. Pass '' to disable.")
    parser.add_argument("--viaf-mapping", default=VIAF_MAPPING_DEFAULT,
                        help="01_map_viaf.py output; supplies additional VIAF IDs for "
                             "Pass 1 beyond what the raw BnF data carries. Pass '' to disable.")
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run_mapping(args.bnf_actors, args.estc_actors, args.output, args.report,
               year_window=args.year_window, dedup_mapping_path=args.dedup_mapping or None,
               viaf_mapping_path=args.viaf_mapping or None,
               use_monitor=not args.no_monitor, monitor_script=args.monitor_script,
               full_output_path=args.full_output or None)


if __name__ == "__main__":
    main()
