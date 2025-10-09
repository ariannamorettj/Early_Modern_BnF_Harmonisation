#!/usr/bin/env python3
"""
fetch_bnf_ark_titles.py

Legge `final_dataset_analysis/reports/record_type_counts.json`,
filtra le chiavi che iniziano con http(s)://data.bnf.fr/ark:/12148/,
scarica l'HTML e ne estrae il titolo.

Estrazione titolo (in ordine):
  1) h1[itemprop="name"]
  2) div.page_title h1
  3) #presentation h1
  4) h1#page-title
  5) h1.page-title
  6) meta[property="og:title"]
  7) meta[name="DC.title"] o meta[name="dc.title"]
  8) <title>

Output:
  - stampa "<url>: <titolo>" su terminale
  - salva JSON {url: titolo} in `final_dataset_analysis/reports/bnf_ark_titles.json`

Dipendenze:
  pip install requests beautifulsoup4 tqdm
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

COUNTS_PATH = Path("final_dataset_analysis/reports/record_type_counts.json")
OUT_PATH = Path("final_dataset_analysis/reports/bnf_ark_titles.json")

ARK_PREFIX_HTTP = "http://data.bnf.fr/ark:/12148/"
ARK_PREFIX_HTTPS = "https://data.bnf.fr/ark:/12148/"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en,fr;q=0.9",
    "User-Agent": "bnf-title-scraper/1.0 (+mailto:you@example.org)"
}

def normalize_fetch_url(url: str) -> str:
    """Return an HTTPS URL without fragment for fetching HTML."""
    base = url.split("#", 1)[0].strip()
    if base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base

def extract_title(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) H1-based selectors (server-rendered su molte pagine)
    for selector in [
        'h1[itemprop="name"]',
        'div.page_title h1',
        '#presentation h1',
        'h1#page-title',
        'h1.page-title',
        'h1',
    ]:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            return re.sub(r"\s+", " ", el.get_text(strip=True))

    # 2) OpenGraph
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return re.sub(r"\s+", " ", og["content"].strip())

    # 3) DC.title
    dc = soup.find("meta", attrs={"name": "DC.title"}) or soup.find("meta", attrs={"name": "dc.title"})
    if dc and dc.get("content"):
        return re.sub(r"\s+", " ", dc["content"].strip())

    # 4) Tag <title>
    if soup.title and soup.title.string:
        return re.sub(r"\s+", " ", soup.title.string.strip())

    return None

def get_html(url: str, retries: int = 2, delay: float = 0.2) -> Optional[str]:
    """GET with small retry/backoff; return response text or None."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
            else:
                print(f"[WARN] Request failed for {url}: {e}")
    return None

def main() -> int:
    if not COUNTS_PATH.exists():
        print(f"[ERR] Missing input JSON: {COUNTS_PATH}")
        return 1

    data = json.loads(COUNTS_PATH.read_text(encoding="utf-8"))

    # Prendi solo chiavi data.bnf.fr/ark:/12148/
    ark_keys = [k for k in data.keys() if k.startswith(ARK_PREFIX_HTTP) or k.startswith(ARK_PREFIX_HTTPS)]
    if not ark_keys:
        print("[INFO] No data.bnf.fr ARK keys found in the input JSON.")
        return 0

    results: Dict[str, str] = {}

    for url in tqdm(ark_keys, desc="Fetching titles", unit="url"):
        fetch_url = normalize_fetch_url(url)
        html = get_html(fetch_url)
        if html is None:
            continue

        title = extract_title(html)
        if not title:
            print(f"[WARN] Title not found for {url}")
            continue

        results[url] = title
        print(f"{url}: {title}")

        # Micro-pausa gentile
        time.sleep(0.05)

    # Salva JSON
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {OUT_PATH} with {len(results)} titles.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
