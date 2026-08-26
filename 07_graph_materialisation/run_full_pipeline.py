#!/usr/bin/env python3
"""
run_full_pipeline.py
====================
Orchestrates the full BnF RDF knowledge graph pipeline:
  1. Materialise actors graph (morph-kgc)       – includes authority links
  2. Validate actors graph
  3. Materialise bibliographic graph (morph-kgc) – includes ESTC seeAlso
  4. Validate bibliographic graph
  5. Materialise roles graph (morph-kgc)         – edition–actor role edges
  6. Validate roles graph
  7. Merge actors + bibliographic + roles → merged graph
  8. Validate merged graph
  9. Write summary report (triples + file sizes)

Inputs (resolved by the preprocess step in scripts/bnf_graph_pipeline.py):
  Primary   : 06_mapping/output/bnf_actors_enriched.csv
              06_mapping/output/bnf_editions_enriched.csv
  Fallback  : 05_subset_optimisation/output/bnf_actors_optimised.csv
              05_subset_optimisation/output/bnf_actors_optimised_minimal.csv
  Legacy    : 01_data_retrieval raw ZIPs (when no upstream CSVs present)

Output filenames are timestamped so no existing file is ever overwritten.
All logs and reports are written to output/logs/.

Usage
-----
    /path/to/python3.12 run_full_pipeline.py [--profile full|sample]
        [--skip-actors] [--skip-bib] [--skip-roles]

Arguments
---------
    --profile      full (default) or sample
    --skip-actors  skip actors materialisation (reuse latest existing file)
    --skip-bib     skip bibliographic materialisation (reuse latest existing file)
    --skip-roles   skip roles materialisation (reuse latest existing file or omit)
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows consoles default stdout to a legacy codepage (e.g. cp1252) that
# cannot encode characters such as U+2713 (✓) or U+2192 (→) used below,
# raising UnicodeEncodeError. Reconfigure to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Tqdm (progress bar) – graceful fallback if not installed ──────────────────
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent          # 07_graph_materialisation/
OUTPUT_DIR   = SCRIPT_DIR / "output"
LOG_DIR      = OUTPUT_DIR / "logs"
RUNTIME_DIR  = OUTPUT_DIR / "runtime_configs"

PYTHON       = sys.executable                           # same interpreter that runs this script
MORPH_CMD    = [PYTHON, "-m", "morph_kgc"]
PIPELINE_CMD = [PYTHON, str(SCRIPT_DIR / "scripts" / "bnf_graph_pipeline.py")]

TIMESTAMP    = datetime.now().strftime("%Y%m%dT%H%M%S")

# ─────────────────────────────────────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"pipeline_{TIMESTAMP}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def hr(char="─", width=72):
    """Print a horizontal rule to log."""
    log.info(char * width)


def file_stats(path: Path) -> dict:
    """Return dict with triple count (lines) and byte size for a .nt file."""
    if not path.exists():
        return {"triples": 0, "bytes": 0, "mb": 0.0}
    size = path.stat().st_size
    # wc -l is fast even for huge files
    result = subprocess.run(["wc", "-l", str(path)], capture_output=True, text=True)
    lines = int(result.stdout.split()[0]) if result.returncode == 0 else 0
    return {"triples": lines, "bytes": size, "mb": round(size / 1_048_576, 2)}


def run(cmd: list, label: str, cwd: Path = SCRIPT_DIR) -> int:
    """Run a subprocess, stream output to log, return exit code."""
    log.info(f"▶ {label}")
    log.info(f"  CMD: {' '.join(str(c) for c in cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        log.info(f"  | {line.rstrip()}")
    proc.wait()
    elapsed = time.time() - t0
    status = "✓ done" if proc.returncode == 0 else f"✗ FAILED (exit {proc.returncode})"
    log.info(f"  {status} in {elapsed:.1f}s")
    return proc.returncode


def morph_ini(profile: str, target: str) -> Path:
    """Return path to the morph .ini file for a given profile and target."""
    return RUNTIME_DIR / f"morph_{profile}_{target}.ini"


def stamped_nt(profile: str, target: str) -> Path:
    """Return output path with timestamp so existing files are never overwritten."""
    return OUTPUT_DIR / profile / f"knowledge-graph_{target}_{TIMESTAMP}.nt"


def latest_nt(profile: str, target: str) -> Path | None:
    """Find the most recently modified .nt file matching the target pattern."""
    folder = OUTPUT_DIR / profile
    pattern = f"knowledge-graph_{target}_*.nt"
    matches = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def progress_bar(iterable, desc="", total=None):
    """Wrap iterable with tqdm if available, else return as-is."""
    if HAS_TQDM:
        return tqdm(iterable, desc=desc, total=total, unit="step",
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]")
    return iterable


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline steps
# ─────────────────────────────────────────────────────────────────────────────

def step_materialise(profile: str, target: str, skip: bool) -> Path:
    """
    Run morph-kgc for `target` (actors | bibliographic).
    Returns path to the final .nt file.
    """
    hr()
    if skip:
        existing = latest_nt(profile, target)
        if existing:
            log.info(f"[SKIP] {target} materialisation — reusing {existing.name}")
            return existing
        else:
            log.warning(f"[SKIP] requested but no existing {target} .nt found — running materialisation")

    ini = morph_ini(profile, target)
    if not ini.exists():
        log.error(f"Missing config: {ini}")
        sys.exit(1)

    out_dir = OUTPUT_DIR / profile
    out_dir.mkdir(parents=True, exist_ok=True)

    # morph-kgc writes to a tmp folder defined in the .ini; after it finishes
    # we rename the output to our timestamped filename.
    # We read the output_file setting from the ini to find where morph wrote it.
    tmp_path = _read_ini_output(ini, out_dir)

    log.info(f"[MATERIALISE] target={target}  profile={profile}  ini={ini.name}")
    t0 = time.time()
    rc = run(MORPH_CMD + [str(ini)], label=f"morph-kgc {target}")
    if rc != 0:
        log.error(f"morph-kgc failed for {target} (exit {rc})")
        sys.exit(rc)

    elapsed = time.time() - t0
    log.info(f"[MATERIALISE] morph-kgc finished in {elapsed:.0f}s")

    # Locate the produced file
    if tmp_path and tmp_path.exists():
        src = tmp_path
    else:
        # Fallback: look for any new .nt in the profile output dir
        src = _find_produced_nt(out_dir, before_ts=t0)

    if src is None or not src.exists():
        log.error(f"Cannot locate produced .nt file for {target}")
        sys.exit(1)

    dest = stamped_nt(profile, target)
    log.info(f"[MATERIALISE] moving {src.name} → {dest.name}")
    shutil.move(str(src), str(dest))

    stats = file_stats(dest)
    log.info(f"[MATERIALISE] {target}: {stats['triples']:,} triples  {stats['mb']} MB")
    return dest


def _read_ini_output(ini: Path, default_dir: Path) -> Path | None:
    """Parse output_file from a morph-kgc .ini to find where it writes."""
    try:
        content = ini.read_text()
        for line in content.splitlines():
            if line.strip().lower().startswith("output_file"):
                val = line.split("=", 1)[1].strip()
                p = Path(val)
                if not p.is_absolute():
                    p = SCRIPT_DIR / p
                return p
    except Exception:
        pass
    return None


def _find_produced_nt(folder: Path, before_ts: float) -> Path | None:
    """Find a .nt file in folder created after before_ts."""
    candidates = [
        p for p in folder.glob("*.nt")
        if p.stat().st_mtime > before_ts
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def step_validate(profile: str, target: str, nt_path: Path, sample_lines: int = 10000):
    """Run pipeline validate on a .nt file."""
    hr()
    log.info(f"[VALIDATE] target={target}  file={nt_path.name}")

    # The pipeline script expects the canonical filename; we pass it via env or
    # we can use the --file override if the script supports it.  If not, we
    # temporarily symlink the timestamped file to the canonical name.
    canonical = OUTPUT_DIR / profile / f"knowledge-graph_{target}.nt"
    _symlink_or_copy(nt_path, canonical)

    rc = run(
        PIPELINE_CMD + ["validate", "--profile", profile, "--target", target,
                        "--sample-lines", str(sample_lines)],
        label=f"validate {target}",
    )
    # Remove the temporary symlink / copy
    if canonical.is_symlink():
        canonical.unlink()

    if rc != 0:
        log.error(f"Validation failed for {target}")
        sys.exit(rc)
    log.info(f"[VALIDATE] {target} ✓")


def step_merge(profile: str, actors_nt: Path, bib_nt: Path,
               roles_nt: Path | None = None) -> Path:
    """Concatenate actors + bibliographic (+ optional roles) → merged timestamped file."""
    hr()
    parts = [actors_nt, bib_nt] + ([roles_nt] if roles_nt else [])
    names = " + ".join(p.name for p in parts)
    merged_dest = stamped_nt(profile, "merged")
    log.info(f"[MERGE] {names} → {merged_dest.name}")

    # Symlink each source to its canonical name so the pipeline merge command finds it
    canon_map = {
        actors_nt: OUTPUT_DIR / profile / "knowledge-graph_actors.nt",
        bib_nt:    OUTPUT_DIR / profile / "knowledge-graph_bibliographic.nt",
    }
    if roles_nt:
        canon_map[roles_nt] = OUTPUT_DIR / profile / "knowledge-graph_roles.nt"

    for src, canon in canon_map.items():
        _symlink_or_copy(src, canon)

    rc = run(
        PIPELINE_CMD + ["merge", "--profile", profile],
        label="merge",
    )

    # Clean up symlinks
    for canon in canon_map.values():
        if canon.is_symlink():
            canon.unlink()

    if rc != 0:
        log.error("Merge step failed")
        sys.exit(rc)

    # Move canonical merged output to timestamped destination
    canon_merged = OUTPUT_DIR / profile / "knowledge-graph_merged.nt"
    if canon_merged.exists() and not canon_merged.is_symlink():
        shutil.move(str(canon_merged), str(merged_dest))
        log.info(f"[MERGE] moved merged output → {merged_dest.name}")
    elif merged_dest.exists():
        pass
    else:
        log.error("Cannot locate merged .nt file after merge step")
        sys.exit(1)

    stats = file_stats(merged_dest)
    log.info(f"[MERGE] merged: {stats['triples']:,} triples  {stats['mb']} MB")
    return merged_dest


def _symlink_or_copy(src: Path, dest: Path):
    """Create a symlink dest → src; fall back to copy if symlinks not available."""
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(src.resolve())
    except (OSError, NotImplementedError):
        shutil.copy2(str(src), str(dest))


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def write_report(profile: str, actors_nt: Path, bib_nt: Path, merged_nt: Path,
                 roles_nt: Path | None = None):
    """Write a human-readable summary report alongside the log."""
    report_path = LOG_DIR / f"report_{TIMESTAMP}.txt"
    a = file_stats(actors_nt)
    b = file_stats(bib_nt)
    r = file_stats(roles_nt) if roles_nt else None
    m = file_stats(merged_nt)

    rows = [
        ("Actors (+ authorities)",  a),
        ("Bibliographic (+ ESTC)",  b),
    ]
    if r:
        rows.append(("Roles", r))
    rows.append(("Merged", m))

    sub_total_t = a["triples"] + b["triples"] + (r["triples"] if r else 0)
    sub_total_b = a["bytes"]   + b["bytes"]   + (r["bytes"]   if r else 0)
    sub_total_m = a["mb"]      + b["mb"]      + (r["mb"]      if r else 0.0)

    lines = [
        "=" * 72,
        "BnF Knowledge Graph Pipeline — Run Report",
        f"Timestamp : {TIMESTAMP}",
        f"Profile   : {profile}",
        "=" * 72,
        "",
        f"{'Graph':<36}  {'Triples':>12}  {'Bytes':>14}  {'MB':>8}",
        f"{'─'*36}  {'─'*12}  {'─'*14}  {'─'*8}",
    ]
    for label, s in rows:
        lines.append(
            f"{label:<36}  {s['triples']:>12,}  {s['bytes']:>14,}  {s['mb']:>8.2f}"
        )
    lines += [
        "",
        f"{'─'*36}  {'─'*12}  {'─'*14}  {'─'*8}",
        f"{'Component total':<36}  {sub_total_t:>12,}  {sub_total_b:>14,}  {sub_total_m:>8.2f}",
        "",
        "Output files",
        f"  Actors        : {actors_nt}",
        f"  Bibliographic : {bib_nt}",
    ]
    if roles_nt:
        lines.append(f"  Roles         : {roles_nt}")
    lines += [
        f"  Merged        : {merged_nt}",
        f"  Log           : {LOG_FILE}",
        "=" * 72,
    ]

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")

    hr("=")
    for ln in lines:
        log.info(ln)
    hr("=")
    log.info(f"Report saved to: {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BnF full pipeline orchestrator")
    parser.add_argument("--profile",      default="full", choices=["full", "sample"])
    parser.add_argument("--skip-actors",  action="store_true",
                        help="Skip actors materialisation and reuse the latest existing file")
    parser.add_argument("--skip-bib",     action="store_true",
                        help="Skip bibliographic materialisation and reuse the latest existing file")
    parser.add_argument("--skip-roles",   action="store_true",
                        help="Skip roles materialisation (omits role-edition edges from the merged graph)")
    parser.add_argument("--sample-lines", type=int, default=10000,
                        help="Number of lines to sample during validation (default: 10000)")
    args = parser.parse_args()

    profile = args.profile

    hr("═")
    log.info(f"BnF Knowledge Graph Pipeline  ·  profile={profile}  ·  {TIMESTAMP}")
    log.info(f"Log: {LOG_FILE}")
    hr("═")

    # Determine whether a roles ready file exists to decide if the roles step runs
    ready_dir = SCRIPT_DIR / ("input/ready_to_convert" if profile == "full"
                              else "input/sample_ready_to_convert")
    roles_ready = (ready_dir / "bnf_actors_ready_roles.csv").exists()
    run_roles = roles_ready and not args.skip_roles

    steps = [
        "Materialise actors",
        "Validate actors",
        "Materialise bibliographic",
        "Validate bibliographic",
    ]
    if run_roles:
        steps += ["Materialise roles", "Validate roles"]
    steps += ["Merge", "Validate merged", "Write report"]

    pbar = progress_bar(steps, desc="Pipeline", total=len(steps))

    results: dict = {}

    for step in pbar:
        if HAS_TQDM:
            pbar.set_description(f"Step: {step}")

        if step == "Materialise actors":
            results["actors"] = step_materialise(profile, "actors", skip=args.skip_actors)

        elif step == "Validate actors":
            step_validate(profile, "actors", results["actors"], args.sample_lines)

        elif step == "Materialise bibliographic":
            results["bib"] = step_materialise(profile, "bibliographic", skip=args.skip_bib)

        elif step == "Validate bibliographic":
            step_validate(profile, "bibliographic", results["bib"], args.sample_lines)

        elif step == "Materialise roles":
            results["roles"] = step_materialise(profile, "roles", skip=False)

        elif step == "Validate roles":
            step_validate(profile, "roles", results["roles"], args.sample_lines)

        elif step == "Merge":
            results["merged"] = step_merge(
                profile,
                results["actors"],
                results["bib"],
                roles_nt=results.get("roles"),
            )

        elif step == "Validate merged":
            step_validate(profile, "merged", results["merged"], args.sample_lines)

        elif step == "Write report":
            write_report(
                profile,
                results["actors"],
                results["bib"],
                results["merged"],
                roles_nt=results.get("roles"),
            )

    hr("═")
    log.info("Pipeline completed successfully ✓")
    hr("═")


if __name__ == "__main__":
    main()