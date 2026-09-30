#!/usr/bin/env python3
"""
actors_deduplication.py  —  Module 04, actor_name heuristic rules.

Scope of this implementation
-----------------------------
Identifies BnF actor URIs that likely refer to the SAME real-world person but
were acquired as distinct records (distinct `actor` URIs) — the kind of
duplication that inflates any downstream count based on actor identity
(e.g. the ESTC/BnF author-level overlap requested for module 06). This is a
different problem from actors_id_matching.py / actors_name_matching.py
(pre-existing scripts, kept for reference, that only report value variation
*within* the legacy `data/unified_agents/` per-role files) and from
gen_subset_optm.py's `--dedup-field` (which collapses exact-value duplicates
on a single field, not identity duplicates across differing URIs).

Algorithm
---------
1. Group actor rows by normalised `actor_name` (case-folded, whitespace/
   punctuation collapsed — see normalise_name()). Only groups with more than
   one distinct actor URI are candidates; a unique name is never a duplicate
   of anything and is skipped entirely (not written to output).
2. Within each name-group, every pair of actors is compared for corroborating
   evidence:
     - shared_external_link: actor_link_exact / actor_link_close (each
       ";"-split into individual URIs) share at least one value. Two
       different BnF records pointing at the same external authority record
       are almost certainly the same person.
     - matching_dates: actor_birth AND actor_death are both non-empty and
       identical strings on both records.
   A pair with at least one of these is unioned into the same cluster
   (union-find). A name-group larger than --max-pairwise-group-size is NOT
   compared pairwise (O(n^2) safeguard for very common names) and is instead
   reported whole as "group_too_large_to_compare".
3. Clusters of size 1 within a name-group (same name, no corroborating
   evidence) are NOT merged — they are flagged as "ambiguous_name_only" for
   manual review, never auto-resolved. This mirrors the module's general
   deterministic-first, no-silent-guessing stance (see 03_map_estc_ecco.py's
   ambiguous_translation handling for the same principle applied to a
   different field).
4. For each real cluster (size > 1), the canonical record is the one with
   the most non-empty CORE_FIELDS values (richest record wins), tie-broken
   by the lexicographically smallest actor URI for determinism.

What this script does NOT do (intentionally, out of scope for this pass)
--------------------------------------------------------------------------
- No fuzzy name matching (e.g. "J. Racine" vs "Jean Racine") — grouping is
  by exact normalised name only. Catching near-miss name variants is later,
  LLM-assisted work, consistent with this module's heuristic-first / LLM-
  as-last-resort design (see 04_harmonisation_and_evaluation/README.md).
- No accent-folding in normalise_name() (kept consistent with the existing
  normalize_actor_name() in actors_name_matching.py).
- The resulting mapping is NOT yet wired into assemble_actors_ready.py or
  gen_subset_optm.py — it is a standalone diagnostic/resolution step for now,
  same status actor_name and actor_dates had before their overlay wiring.

Input
-----
The actors-ready dataset (module 4's assemble_actors_ready.py output), one
row per actor URI, e.g.
04_harmonisation_and_evaluation/output/bnf_actors_ready.csv — or any subset
of it with the same columns (e.g. a year-filtered subset from module 05).

Output
------
actor_dedup_mapping.csv — one row per actor URI that shares its normalised
name with at least one other actor URI:
    actor_uri | cluster_id | canonical_actor_uri | is_canonical |
    match_type | confidence | normalised_name

    match_type is one of:
        shared_external_link       (confidence: high)
        matching_dates              (confidence: high)
        shared_external_link+matching_dates  (confidence: high)
        ambiguous_name_only         (confidence: low, NOT merged)
        group_too_large_to_compare  (confidence: low, NOT merged)

actor_dedup_report.json — human-review summary:
    { "merged_clusters": {cluster_id: {...}},
      "ambiguous_groups": {normalised_name: [actor_uri, ...]},
      "oversized_groups": {normalised_name: actor_count},
      "stats": {...} }

Monitoring
----------
By default, resource-usage checkpoints are written via the shared
00_monitor/monitor.py "embedded state-based monitoring" API — the same
mechanism used by module 1's query_agents.R / query_editions.R and by
name_normaliser.py / 06_mapping's scripts: one checkpoint every
MONITOR_CHECKPOINT_EVERY (1,000) processed name-groups and at the last
one, plus a final checkpoint on completion. Reports land in
00_monitor/report/actors_deduplication_<timestamp>_py.txt. Disable with
--no-monitor.

Usage
-----
python actors_deduplication.py \\
    --input 04_harmonisation_and_evaluation/output/bnf_actors_ready.csv \\
    --output-dir 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output \\
    --report-dir 04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/report

# disable the monitor report
python actors_deduplication.py --no-monitor
"""

import os, csv, sys, json, re, argparse, importlib.util
from pathlib import Path

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

INPUT_DEFAULT = "04_harmonisation_and_evaluation/output/bnf_actors_ready.csv"
OUTPUT_DIR_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/output"
)
OUTPUT_FILENAME_DEFAULT = "actor_dedup_mapping.csv"
REPORT_DIR_DEFAULT = (
    "04_harmonisation_and_evaluation/01_harmonisation/actor_name/01_heuristic_rules/report"
)
REPORT_FILENAME_DEFAULT = "actor_dedup_report.json"
MONITOR_SCRIPT_DEFAULT = "00_monitor/monitor.py"
# One checkpoint per record cost ~55 ms each (mostly the nvidia-smi GPU read),
# about two hours over 124,695 actors; checkpoint every N records plus the
# last one instead, like 06_mapping/05_map_estc_actors.py.
MONITOR_CHECKPOINT_EVERY = 1_000
MAX_PAIRWISE_GROUP_SIZE_DEFAULT = 200

CORE_FIELDS = [
    "actor_name", "actor_first_name", "actor_last_name",
    "actor_birth", "actor_death", "actor_start", "actor_end",
    "actor_country", "actor_language", "actor_gender", "actor_profession",
    "actor_link_exact", "actor_link_close",
]

OUTPUT_FIELDS = [
    "actor_uri", "cluster_id", "canonical_actor_uri", "is_canonical",
    "match_type", "confidence", "normalised_name",
]

_name_norm_re = re.compile(r"[\s.,]+", re.UNICODE)


# ── Monitor integration (embedded state-based monitoring, module 06_monitor) ──

def load_monitor_module(monitor_script: str = MONITOR_SCRIPT_DEFAULT):
    """Load 00_monitor/monitor.py as a module, mirroring load_monitor_env() in
    query_agents.R / query_editions.R (module 1) and name_normaliser.py."""
    project_root = Path(__file__).resolve().parents[4]
    resolved = (project_root / monitor_script).resolve()
    spec = importlib.util.spec_from_file_location("monitor_actors_deduplication", resolved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _monitor_checkpoint(monitor_module, monitor_state, index, total, name, group_size):
    if monitor_module is None:
        return monitor_state
    if index % MONITOR_CHECKPOINT_EVERY and index != total:
        return monitor_state
    context = (f"Processed name-group {index}/{total} "
              f"('{name}', {group_size} actors)")
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
    """Case-fold and collapse whitespace/dots/commas to a single space, so
    minor formatting differences don't split an otherwise-identical name
    into separate groups. No accent-folding or fuzzy matching (see module
    docstring) — this is deliberately conservative."""
    s = normalise(name)
    if not s:
        return ""
    return _name_norm_re.sub(" ", s).strip().upper()


def split_links(value: str) -> set[str]:
    return {v.strip() for v in normalise(value).split(";") if v.strip()}


# The actor-identifier column differs between the two ready-dataset schemas
# this script can be pointed at: "actor" (module 4's assemble_actors_ready.py
# output) and "BnF_ID" (module 5's gen_subset_optm.py optimised-subset
# output). Both are accepted so the script works unmodified against either.
ACTOR_ID_COLUMNS = ["actor", "BnF_ID"]


def get_actor_id(row: dict) -> str:
    for col in ACTOR_ID_COLUMNS:
        val = normalise(row.get(col, ""))
        if val:
            return val
    return ""


def load_actors(input_path: str) -> list[dict]:
    rows = []
    with open(input_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for row in csv.DictReader(f):
            aid = get_actor_id(row)
            if not aid:
                continue
            if not normalise(row.get("actor", "")):
                row["actor"] = aid
            rows.append(row)
    return rows


def build_name_groups(actors: list[dict]) -> dict[str, list[dict]]:
    """Group actors by normalised name; groups of size 1 (a unique name) are
    dropped — they cannot be a duplicate of anything."""
    groups: dict[str, list[dict]] = {}
    for row in actors:
        name = normalise_name(row.get("actor_name", ""))
        if not name:
            continue
        groups.setdefault(name, []).append(row)
    return {name: rows for name, rows in groups.items() if len(rows) > 1}


def compute_evidence(a: dict, b: dict) -> set[str]:
    """Return the set of corroborating-evidence reasons linking two actor
    rows that already share a normalised name."""
    reasons: set[str] = set()

    links_a = split_links(a.get("actor_link_exact", "")) | split_links(a.get("actor_link_close", ""))
    links_b = split_links(b.get("actor_link_exact", "")) | split_links(b.get("actor_link_close", ""))
    if links_a & links_b:
        reasons.add("shared_external_link")

    birth_a, death_a = normalise(a.get("actor_birth", "")), normalise(a.get("actor_death", ""))
    birth_b, death_b = normalise(b.get("actor_birth", "")), normalise(b.get("actor_death", ""))
    if birth_a and death_a and birth_a == birth_b and death_a == death_b:
        reasons.add("matching_dates")

    return reasons


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[ri] = rj


def _richness(row: dict) -> int:
    return sum(1 for f in CORE_FIELDS if normalise(row.get(f, "")))


def _pick_canonical(members: list[dict]) -> str:
    return sorted(
        members,
        key=lambda r: (-_richness(r), normalise(r.get("actor", ""))),
    )[0].get("actor", "")


def dedup_group(name: str, rows: list[dict], max_pairwise_group_size: int) -> dict:
    """
    Resolve one name-group into clusters.

    Returns a dict:
        { "clusters": [ {members, match_type, confidence}, ... ],
          "ambiguous": [actor_uri, ...],       # size-1 clusters, evidence-less
          "oversized": bool }
    """
    n = len(rows)
    if n > max_pairwise_group_size:
        return {
            "clusters": [],
            "ambiguous": [normalise(r.get("actor", "")) for r in rows],
            "oversized": True,
        }

    uf = _UnionFind(n)
    pair_reasons: dict[tuple[int, int], set[str]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            reasons = compute_evidence(rows[i], rows[j])
            if reasons:
                uf.union(i, j)
                pair_reasons[(i, j)] = reasons

    groups_by_root: dict[int, list[int]] = {}
    for i in range(n):
        groups_by_root.setdefault(uf.find(i), []).append(i)

    clusters = []
    ambiguous = []
    for indices in groups_by_root.values():
        if len(indices) == 1:
            ambiguous.append(normalise(rows[indices[0]].get("actor", "")))
            continue

        reasons: set[str] = set()
        idx_set = set(indices)
        for (i, j), r in pair_reasons.items():
            if i in idx_set and j in idx_set:
                reasons |= r

        members = [rows[i] for i in indices]
        clusters.append({
            "members": members,
            "match_type": "+".join(sorted(reasons)) if reasons else "ambiguous_name_only",
            "confidence": "high" if reasons else "low",
        })

    return {"clusters": clusters, "ambiguous": ambiguous, "oversized": False}


def format_human_report(stats: dict, total_actors: int, max_pairwise_group_size: int) -> str:
    """Plain-text, template-filled summary of one run — no LLM involved,
    just the same `stats` dict already computed by run() rendered as
    readable sentences. Written alongside the machine-readable JSON report
    on every run so a human can check the outcome without parsing JSON."""
    pct_merged = (stats["actors_merged"] / total_actors * 100) if total_actors else 0.0
    pct_ambiguous = (stats["actors_ambiguous"] / total_actors * 100) if total_actors else 0.0
    pct_oversized = (stats["actors_in_oversized_groups"] / total_actors * 100) if total_actors else 0.0

    lines = [
        "ACTOR DEDUPLICATION REPORT",
        "=" * 70,
        "",
        f"Total actors read from input                : {total_actors:,}",
        f"Name-groups with a name shared by >1 actor  : {stats['name_groups_with_collisions']:,}",
        f"Clusters merged (confident duplicates)      : {stats['clusters_merged']:,}",
        f"Actors merged into those clusters           : {stats['actors_merged']:,} ({pct_merged:.2f}%)",
        f"Actors left ambiguous (not merged)          : {stats['actors_ambiguous']:,} ({pct_ambiguous:.2f}%)",
        f"Actors in oversized groups (>{max_pairwise_group_size}, not compared) : "
        f"{stats['actors_in_oversized_groups']:,} ({pct_oversized:.2f}%)",
        "",
        "Summary",
        "-" * 70,
        (
            f"Out of {total_actors:,} actors, {stats['actors_merged']:,} ({pct_merged:.2f}%) were "
            f"confidently merged into {stats['clusters_merged']:,} duplicate cluster(s), each "
            "backed by a shared external link or matching birth/death dates. A further "
            f"{stats['actors_ambiguous']:,} ({pct_ambiguous:.2f}%) actors share a name with at "
            "least one other actor but could not be confirmed as the same person, and were left "
            "unmerged for manual review rather than guessed at."
        ),
        "",
    ]
    return "\n".join(lines)


def run(input_path: str, output_dir: str,
       output_filename: str = OUTPUT_FILENAME_DEFAULT,
       report_dir: str = REPORT_DIR_DEFAULT,
       report_filename: str = REPORT_FILENAME_DEFAULT,
       max_pairwise_group_size: int = MAX_PAIRWISE_GROUP_SIZE_DEFAULT,
       use_monitor: bool = False,
       monitor_script: str = MONITOR_SCRIPT_DEFAULT) -> tuple[str, str]:
    """
    Load the actors-ready dataset, resolve duplicate-name groups into
    clusters, and write the mapping CSV + review JSON report. Returns
    (output_path, report_path).
    """
    actors = load_actors(input_path)
    groups = build_name_groups(actors)
    total_groups = len(groups)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    monitor_module = None
    monitor_state = None
    if use_monitor:
        monitor_module = load_monitor_module(monitor_script)
        monitor_state = monitor_module.start_monitor_state(
            sampling_mode="checkpoint-based updates during actors_deduplication.py execution",
            print_start_message=True,
        )

    merged_clusters = {}
    ambiguous_groups = {}
    oversized_groups = {}
    rows_out = []
    stats = {
        "name_groups_with_collisions": total_groups,
        "clusters_merged": 0,
        "actors_merged": 0,
        "actors_ambiguous": 0,
        "actors_in_oversized_groups": 0,
    }

    for i, (name, rows) in enumerate(sorted(groups.items()), start=1):
        result = dedup_group(name, rows, max_pairwise_group_size)

        if result["oversized"]:
            oversized_groups[name] = len(rows)
            stats["actors_in_oversized_groups"] += len(rows)
            for uri in result["ambiguous"]:
                rows_out.append({
                    "actor_uri": uri, "cluster_id": "", "canonical_actor_uri": uri,
                    "is_canonical": "True", "match_type": "group_too_large_to_compare",
                    "confidence": "low", "normalised_name": name,
                })
        else:
            for cluster in result["clusters"]:
                cluster_id = f"{name}::{len(merged_clusters)}"
                canonical = _pick_canonical(cluster["members"])
                member_uris = [normalise(r.get("actor", "")) for r in cluster["members"]]
                merged_clusters[cluster_id] = {
                    "normalised_name": name,
                    "canonical_actor_uri": canonical,
                    "members": member_uris,
                    "match_type": cluster["match_type"],
                    "confidence": cluster["confidence"],
                }
                stats["clusters_merged"] += 1
                stats["actors_merged"] += len(member_uris)
                for uri in member_uris:
                    rows_out.append({
                        "actor_uri": uri, "cluster_id": cluster_id,
                        "canonical_actor_uri": canonical,
                        "is_canonical": str(uri == canonical),
                        "match_type": cluster["match_type"],
                        "confidence": cluster["confidence"],
                        "normalised_name": name,
                    })

            if result["ambiguous"]:
                ambiguous_groups[name] = result["ambiguous"]
                stats["actors_ambiguous"] += len(result["ambiguous"])
                for uri in result["ambiguous"]:
                    rows_out.append({
                        "actor_uri": uri, "cluster_id": "", "canonical_actor_uri": uri,
                        "is_canonical": "True", "match_type": "ambiguous_name_only",
                        "confidence": "low", "normalised_name": name,
                    })

        monitor_state = _monitor_checkpoint(
            monitor_module, monitor_state, i, total_groups, name, len(rows))

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows_out, key=lambda r: r["actor_uri"]))

    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "merged_clusters": merged_clusters,
            "ambiguous_groups": ambiguous_groups,
            "oversized_groups": oversized_groups,
            "stats": stats,
        }, f, ensure_ascii=False, indent=2)

    report_txt_path = os.path.splitext(report_path)[0] + ".txt"
    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(format_human_report(stats, len(actors), max_pairwise_group_size))

    if use_monitor:
        monitor_state = monitor_module.update_monitor_state(
            state=monitor_state,
            context="Completed actors_deduplication run",
            print_console=True,
        )
        monitor_state = monitor_module.stop_monitor_state(
            state=monitor_state, print_stop_message=True,
        )

    print(f"\n✓ Name-groups with collisions : {total_groups:,}")
    print(f"  Clusters merged              : {stats['clusters_merged']:,} "
         f"({stats['actors_merged']:,} actors)")
    print(f"  Ambiguous (not merged)       : {stats['actors_ambiguous']:,} actors")
    print(f"  In oversized groups (>{max_pairwise_group_size}) : "
         f"{stats['actors_in_oversized_groups']:,} actors")
    print(f"✓ Wrote mapping -> {output_path}")
    print(f"✓ Wrote report  -> {report_path}")
    print(f"✓ Wrote human-readable report -> {report_txt_path}")
    return output_path, report_path


def main():
    parser = argparse.ArgumentParser(
        description="actor_name heuristic deduplication "
                    "(same-name identity resolution across distinct BnF URIs)")
    parser.add_argument("--input", default=INPUT_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--output-filename", default=OUTPUT_FILENAME_DEFAULT)
    parser.add_argument("--report-dir", default=REPORT_DIR_DEFAULT)
    parser.add_argument("--report-filename", default=REPORT_FILENAME_DEFAULT)
    parser.add_argument("--max-pairwise-group-size", type=int,
                        default=MAX_PAIRWISE_GROUP_SIZE_DEFAULT,
                        help="Name-groups larger than this are reported as "
                             "'group_too_large_to_compare' instead of being "
                             "compared pairwise (O(n^2) safeguard).")
    parser.add_argument("--monitor-script", default=MONITOR_SCRIPT_DEFAULT)
    parser.add_argument("--no-monitor", action="store_true",
                        help="Disable the 00_monitor/monitor.py resource-usage report.")
    args = parser.parse_args()
    run(args.input, args.output_dir, args.output_filename,
        args.report_dir, args.report_filename, args.max_pairwise_group_size,
        use_monitor=not args.no_monitor, monitor_script=args.monitor_script)


if __name__ == "__main__":
    main()
