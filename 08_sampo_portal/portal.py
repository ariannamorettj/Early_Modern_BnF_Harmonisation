#!/usr/bin/env python3
"""Module 08 — Sampo portal over the module 07 knowledge graph.

Commands
--------
setup   download the pinned Oxigraph server (checksum-verified), clone the
        pinned Sampo-UI framework, link this module's configs/ into it and
        install its npm dependencies.
load    rebuild the triplestore from a module 07 graph: the CHAD-AP triples
        go into their own named graph, derived.ru materialises the portal
        layer next to them, and the vocab/ label files are added.
serve   run the read-only SPARQL endpoint (http://localhost:7878/query).
dev     run endpoint + Sampo-UI server (3001) + client (8080) together.

The graph changes whenever modules 04-07 are re-run: `load` always starts
from an empty store, so re-running it is the whole update procedure.

Usage
-----
python 08_sampo_portal/portal.py setup
python 08_sampo_portal/portal.py load --profile sample
python 08_sampo_portal/portal.py dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parent
LOCK = json.loads((MODULE_DIR / "portal.lock.json").read_text(encoding="utf-8"))

TOOLS_DIR = MODULE_DIR / ".tools"
SAMPO_DIR = MODULE_DIR / ".sampo-ui"
STORE_ROOT = MODULE_DIR / ".data"
CONFIGS_DIR = MODULE_DIR / "configs"
TRIPLESTORE_DIR = MODULE_DIR / "triplestore"

GRAPH_BASE = "https://w3id.org/bnf/portal/graph/chad-ap"
GRAPH_VOCAB = "https://w3id.org/bnf/portal/graph/vocab"
ENDPOINT_BIND = "localhost:7878"
ENDPOINT_URL = f"http://{ENDPOINT_BIND}/query"

GRAPH_FILES = {
    "sample": PROJECT_DIR / "07_graph_materialisation" / "output" / "sample" / "knowledge-graph_merged.nt",
    "full": PROJECT_DIR / "07_graph_materialisation" / "output" / "full" / "knowledge-graph_merged.nt",
}

# Minimal patches applied to the pinned Sampo-UI clone so it runs outside
# Docker, on Windows too: (file, original, replacement).
SAMPO_PATCHES = [
    # The Express server serves configs from a hard-coded Docker path.
    ("server/src/index.js",
     "const configsPath = '/app/configs'",
     "const configsPath = process.env.SAMPO_CONFIGS_PATH || '/app/configs'"),
    # `import history from 'History'` means client/src/History.js, but on a
    # case-insensitive filesystem webpack finds node_modules/history first.
    ("client/webpack.client.common.js",
     "    extensions: ['.js', '.jsx'],\n    modules: [",
     "    extensions: ['.js', '.jsx'],\n"
     "    alias: { History$: path.resolve(__dirname, 'src/History.js') },\n"
     "    modules: ["),
]


def log(msg: str) -> None:
    print(f"[portal] {msg}", flush=True)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    log(" ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def npm() -> str:
    exe = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not exe:
        sys.exit("npm not found on PATH: install Node.js "
                 f"{LOCK['node']['major']} (see 08_sampo_portal/README.md)")
    return exe


# ── Oxigraph ────────────────────────────────────────────────────────────────

def oxigraph_asset() -> dict:
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = "x86_64" if machine in {"amd64", "x86_64"} else machine
    key = f"{system}-{arch}"
    try:
        return LOCK["oxigraph"]["assets"][key]
    except KeyError:
        sys.exit(f"No pinned Oxigraph binary for {key}; add one to portal.lock.json "
                 "from https://github.com/oxigraph/oxigraph/releases")


def oxigraph_bin() -> Path:
    return TOOLS_DIR / oxigraph_asset()["file"]


def setup_oxigraph() -> None:
    asset = oxigraph_asset()
    target = oxigraph_bin()
    if target.exists() and sha256(target) == asset["sha256"]:
        log(f"oxigraph present: {target.name}")
        return
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    url = (f"https://github.com/oxigraph/oxigraph/releases/download/"
           f"{LOCK['oxigraph']['version']}/{asset['file']}")
    log(f"downloading {url}")
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    digest = sha256(tmp)
    if digest != asset["sha256"]:
        tmp.unlink()
        sys.exit(f"checksum mismatch for {asset['file']}: {digest}")
    tmp.replace(target)
    if os.name != "nt":
        target.chmod(0o755)
    log("oxigraph checksum verified")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── Sampo-UI ────────────────────────────────────────────────────────────────

def unlink_dir_link(link: Path) -> bool:
    """Remove a directory symlink/junction without touching its target."""
    if link.is_symlink() or is_junction(link):
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
        return True
    return False


def link_dir(link: Path, target: Path) -> None:
    """Directory link that needs no admin rights (junction on Windows)."""
    if not unlink_dir_link(link) and link.exists():
        shutil.rmtree(link)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        link.symlink_to(target, target_is_directory=True)


def is_junction(path: Path) -> bool:
    try:
        return bool(os.readlink(path))
    except OSError:
        return False


def setup_sampo(skip_npm: bool) -> None:
    lock = LOCK["sampo_ui"]
    if not (SAMPO_DIR / ".git").exists():
        run(["git", "clone", "--quiet", lock["repository"], str(SAMPO_DIR)])
    # Drop the configs link before checkout: a forced checkout would otherwise
    # write the framework's example configs through it into ours.
    unlink_dir_link(SAMPO_DIR / "configs")
    run(["git", "-C", str(SAMPO_DIR), "fetch", "--quiet", "origin"])
    run(["git", "-C", str(SAMPO_DIR), "checkout", "--quiet", "--force", lock["commit"]])

    for rel, original, replacement in SAMPO_PATCHES:
        path = SAMPO_DIR / rel
        text = path.read_text(encoding="utf-8")
        if original in text:
            path.write_text(text.replace(original, replacement, 1), encoding="utf-8")
            log(f"patched {rel}")
        elif replacement not in text:
            sys.exit(f"Sampo-UI {rel} changed upstream; update SAMPO_PATCHES in portal.py")

    # The server imports perspective configs from <sampo-ui>/configs.
    link_dir(SAMPO_DIR / "configs", CONFIGS_DIR)
    log(f"linked {SAMPO_DIR / 'configs'} -> {CONFIGS_DIR}")

    if not skip_npm:
        # `npm install`, as in Sampo-UI's own Dockerfiles: the pinned server
        # package-lock.json is out of sync with package.json, so `npm ci` fails.
        for part in ("server", "client"):
            run([npm(), "install", "--no-audit", "--no-fund"], cwd=SAMPO_DIR / part)


def cmd_setup(args) -> None:
    setup_oxigraph()
    setup_sampo(args.skip_npm)
    log("setup done")


# ── Triplestore ─────────────────────────────────────────────────────────────

def store_dir(profile: str) -> Path:
    return STORE_ROOT / f"store-{profile}"


def cmd_load(args) -> None:
    ox = oxigraph_bin()
    if not ox.exists():
        sys.exit("Oxigraph missing: run `portal.py setup` first")
    graph = Path(args.graph) if args.graph else GRAPH_FILES[args.profile]
    if not graph.exists():
        sys.exit(f"graph not found: {graph} (run module 07 for profile '{args.profile}')")

    store = store_dir(args.profile)
    fresh = store.with_name(store.name + ".new")
    shutil.rmtree(fresh, ignore_errors=True)
    STORE_ROOT.mkdir(parents=True, exist_ok=True)  # oxigraph creates the store dir, not its parent

    t0 = time.time()
    run([str(ox), "load", "--location", str(fresh), "--file", str(graph), "--graph", GRAPH_BASE])
    for vocab in sorted((TRIPLESTORE_DIR / "vocab").glob("*.*t*")):
        run([str(ox), "load", "--location", str(fresh), "--file", str(vocab), "--graph", GRAPH_VOCAB])
    run([str(ox), "update", "--location", str(fresh), "--update-file", str(TRIPLESTORE_DIR / "derived.ru")])
    run([str(ox), "optimize", "--location", str(fresh)])

    # Swap only once the new store is complete, so a failed load never
    # leaves the portal without data.
    shutil.rmtree(store, ignore_errors=True)
    fresh.replace(store)
    (STORE_ROOT / "active_profile").write_text(args.profile, encoding="utf-8")
    log(f"store ready: {store} ({time.time() - t0:.0f}s, from {graph.name})")


def active_profile(requested: str | None) -> str:
    if requested:
        return requested
    marker = STORE_ROOT / "active_profile"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else "sample"


def endpoint_cmd(profile: str) -> list[str]:
    store = store_dir(profile)
    if not store.exists():
        sys.exit(f"no store for profile '{profile}': run `portal.py load --profile {profile}`")
    return [str(oxigraph_bin()), "serve-read-only", "--location", str(store),
            "--bind", ENDPOINT_BIND, "--union-default-graph", "--cors"]


def cmd_serve(args) -> None:
    run(endpoint_cmd(active_profile(args.profile)))


def cmd_dev(args) -> None:
    profile = active_profile(args.profile)
    if not (SAMPO_DIR / "server" / "node_modules").exists():
        sys.exit("Sampo-UI not installed: run `portal.py setup` first")
    env = dict(os.environ,
               SPARQL_ENDPOINT=ENDPOINT_URL,
               SAMPO_CONFIGS_PATH=str(CONFIGS_DIR),
               API_URL="http://localhost:3001/api/v1")
    procs = [
        ("sparql", subprocess.Popen(endpoint_cmd(profile))),
        ("server", subprocess.Popen([npm(), "run", "dev"], cwd=SAMPO_DIR / "server", env=env)),
        ("client", subprocess.Popen([npm(), "run", "dev"], cwd=SAMPO_DIR / "client", env=env)),
    ]
    log(f"profile '{profile}': SPARQL {ENDPOINT_URL} | API http://localhost:3001 | "
        "portal http://localhost:8080  (Ctrl+C stops all)")
    try:
        while all(p.poll() is None for _, p in procs):
            time.sleep(1)
        for name, p in procs:
            if p.poll() is not None:
                log(f"{name} exited with code {p.returncode}")
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in procs:
            stop_tree(p)


def stop_tree(proc: subprocess.Popen) -> None:
    """Stop a process and its children (npm spawns node underneath)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="download Oxigraph, clone and install Sampo-UI")
    p.add_argument("--skip-npm", action="store_true", help="skip `npm ci` (clone, patch and link only)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("load", help="rebuild the triplestore from a module 07 graph")
    p.add_argument("--profile", choices=sorted(GRAPH_FILES), default="sample")
    p.add_argument("--graph", help="explicit .nt file instead of the profile's merged graph")
    p.set_defaults(func=cmd_load)

    for name, func, help_text in [("serve", cmd_serve, "run the SPARQL endpoint only"),
                                  ("dev", cmd_dev, "run endpoint + Sampo-UI server + client")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--profile", choices=sorted(GRAPH_FILES), default=None,
                       help="store to serve (default: the last one loaded)")
        p.set_defaults(func=func)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
