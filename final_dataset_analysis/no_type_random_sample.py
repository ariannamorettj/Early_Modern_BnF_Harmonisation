#!/usr/bin/env python3
"""
no_type_random_sample.py

Estrae un campione di 100 entità senza record_type,
aggiunge la versione "catalogue" dell'URL e l'H1 trovato nella pagina.
Riprova automaticamente quando fallisce il fetch o l'H1 non è presente.

RUN:
    python final_dataset_analysis/no_type_random_sample.py
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set, Optional
import random
import time
import math

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

# --- Percorsi ---------------------------------------------------------------
CSV_DIR = Path("data/unified_dataset/unified_chunks")
OUT_CSV = Path("final_dataset_analysis/reports/no_type_random_sample.csv")

# --- Colonne attese ---------------------------------------------------------
COL_EDITION = "edition"
COL_RECORD_TYPE = "record_type"

# --- Parametri --------------------------------------------------------------
SAMPLE_SIZE = 100
SEED = 42

# HTTP / retry
HTTP_TIMEOUT = 20
# numero di giri *complessivi* per URL (inclusi i casi "h1 non trovato")
MAX_ATTEMPTS_PER_URL = 5
# ritardo base per backoff (raddoppia ad ogni tentativo) + jitter casuale
BACKOFF_BASE = 0.6  # secondi
PAUSE_BETWEEN_URLS = 0.25  # micro-pauses tra un URL e il successivo

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def read_csv_best_effort(path: Path) -> pd.DataFrame:
    """Lettura robusta del CSV (usa ',' come separatore; cambia a ';' se serve)."""
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    last_err: Optional[Exception] = None
    for enc in encodings:
        try:
            return pd.read_csv(
                str(path),
                sep=",",
                dtype=str,
                encoding=enc,
                keep_default_na=False
            )
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Impossibile leggere {path}: {last_err}")


def split_semi(value: str) -> List[str]:
    """Split su ';' con strip e rimozione dei vuoti."""
    if value is None:
        return []
    return [tok.strip() for tok in str(value).split(";") if tok and tok.strip()]


def to_catalogue_url(edition_url: str) -> str:
    """Converte data.bnf.fr -> catalogue.bnf.fr e rimuove #about."""
    if not edition_url:
        return edition_url
    u = edition_url.strip()
    if "#about" in u:
        u = u.split("#about", 1)[0]
    u = u.replace("https://data.bnf.fr/ark:/12148/", "https://catalogue.bnf.fr/ark:/12148/")
    u = u.replace("http://data.bnf.fr/ark:/12148/", "https://catalogue.bnf.fr/ark:/12148/")
    return u


def build_session() -> requests.Session:
    """Sessione requests con retry su errori transitori HTTP/connessione."""
    s = requests.Session()
    retry = Retry(
        total=3,                # retry a livello di trasporto
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,     # retry exponential backoff per 429/5xx
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8,it;q=0.7",
    })
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def extract_h1(html: str) -> str:
    """Prova vari selettori; ritorna stringa vuota se niente."""
    soup = BeautifulSoup(html, "html.parser")
    node = None
    for selector in (
        "div.titrenotices.img-bulles-aut h1",
        "div.titrenotices h1",
        "h1",
    ):
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node.get_text(strip=True)
    return ""


def fetch_h1_with_retries(url: str, session: Optional[requests.Session] = None) -> str:
    """Scarica la pagina e restituisce l'H1, con più tentativi anche se l'H1 è vuoto."""
    if not url or not url.startswith("http"):
        return "[NOT FOUND]"

    s = session or build_session()
    last_status = None

    for attempt in range(1, MAX_ATTEMPTS_PER_URL + 1):
        try:
            resp = s.get(url, timeout=HTTP_TIMEOUT)
            last_status = resp.status_code
            if resp.status_code == 200:
                title = extract_h1(resp.text)
                if title:
                    return title
                # H1 non trovato: aspetta e riprova
            # per 3xx/4xx/5xx: aspetta e riprova (se entro MAX_ATTEMPTS_PER_URL)
        except Exception:
            # errori di connessione/timeout: backoff e riprova
            pass

        # backoff esponenziale con jitter
        sleep_s = BACKOFF_BASE * (2 ** (attempt - 1))
        sleep_s += random.uniform(0, 0.25)
        time.sleep(sleep_s)

    # ultimi controlli: se non trovato, etichetta
    return "[NOT FOUND]" if (last_status is None or last_status >= 200) else f"[HTTP {last_status}]"


def main() -> int:
    random.seed(SEED)

    files = sorted(CSV_DIR.glob("*.csv"))
    if not files:
        print(f"[ERR] Nessun CSV trovato in {CSV_DIR}")
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["edition", "edition_catalogue", "title_h1"]).to_csv(
            OUT_CSV, index=False, encoding="utf-8"
        )
        return 1

    editions_without_type: Set[str] = set()

    # 1) Raccogli entità senza tipo
    for csv_path in tqdm(files, desc="Files", unit="file"):
        try:
            df = read_csv_best_effort(csv_path)
        except Exception as e:
            print(f"[WARN] Salto {csv_path}: {e}")
            continue

        colmap = {c.lower(): c for c in df.columns}
        col_edition = colmap.get(COL_EDITION.lower())
        col_rtype = colmap.get(COL_RECORD_TYPE.lower())
        if not col_edition:
            continue

        if not col_rtype:
            for ed_cell in df[col_edition].astype(str):
                for ed in split_semi(ed_cell):
                    if ed:
                        editions_without_type.add(ed)
            continue

        for ed_cell, rt_cell in zip(df[col_edition].astype(str), df[col_rtype].astype(str)):
            editions = [e for e in split_semi(ed_cell) if e]
            rtypes = [t for t in split_semi(rt_cell) if t]
            if editions and len(rtypes) == 0:
                editions_without_type.update(editions)

    total = len(editions_without_type)
    if total == 0:
        print("[OK] Nessuna entità senza tipo trovata.")
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["edition", "edition_catalogue", "title_h1"]).to_csv(
            OUT_CSV, index=False, encoding="utf-8"
        )
        return 0

    # 2) Campione
    k = min(SAMPLE_SIZE, total)
    sample = random.sample(sorted(editions_without_type), k)

    # 3) Fetch H1 con retry robusto
    session = build_session()
    out_rows = []
    for ed in tqdm(sample, desc="Fetching H1", unit="page"):
        ed_catalogue = to_catalogue_url(ed)
        title = fetch_h1_with_retries(ed_catalogue, session=session)
        out_rows.append(
            {"edition": ed, "edition_catalogue": ed_catalogue, "title_h1": title}
        )
        time.sleep(PAUSE_BETWEEN_URLS)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows, columns=["edition", "edition_catalogue", "title_h1"]).to_csv(
        OUT_CSV, index=False, encoding="utf-8"
    )

    # Statistiche utili a fine run
    missing = sum(1 for r in out_rows if r["title_h1"] in ("", "[NOT FOUND]") or r["title_h1"].startswith("[HTTP "))
    print(f"[OK] Trovate {total} entità senza tipo. Salvato campione di {k} in {OUT_CSV}")
    print(f"[INFO] H1 mancanti/errore nel campione: {missing}/{k}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
