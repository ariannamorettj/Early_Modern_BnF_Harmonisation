"""Crash-safe, resumable CSV output for the long-running mapping scripts.

01_map_viaf.py, 02_map_wikidata.py and 03_map_estc_ecco.py query external
services for tens of thousands of entities (a full VIAF or Wikidata run takes
a day). They used to keep every result in memory and write the CSV at the
end, so a crash or a power cut lost the whole run.

ResumableCsvWriter instead appends each result as soon as it is computed:

- rows are flushed to the OS immediately and fsync'ed to disk every
  `sync_every` rows, so a power cut loses at most that many results;
- on start it reads the existing file, returns the keys already written,
  and truncates a last line left half-written by a crash;
- the caller skips those keys, so re-running the same command resumes at
  the first entity not yet processed. `restart=True` starts from scratch.

The output file itself is the checkpoint: there is no separate state file
that could drift out of sync with it.
"""

from __future__ import annotations

import csv
import os
import sys

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10 ** 9)


class ResumableCsvWriter:
    def __init__(self, path: str, fieldnames: list[str], key_field: str,
                 restart: bool = False, sync_every: int = 50):
        self.path = path
        self.fieldnames = fieldnames
        self.key_field = key_field
        self.sync_every = sync_every
        self._pending = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if restart and os.path.exists(path):
            os.remove(path)
        self.done_keys = self._recover()
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=fieldnames, extrasaction="ignore")
        if new_file:
            self._writer.writeheader()
            self._sync()

    def _recover(self) -> set[str]:
        """Keys already written; drop a trailing partial line if any."""
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return set()
        with open(self.path, "rb+") as fh:
            data = fh.read()
            if not data.endswith(b"\n"):
                cut = data.rfind(b"\n") + 1
                fh.truncate(cut)
                print(f"  [resume] dropped a partially written last line in {self.path}")
        keys: set[str] = set()
        with open(self.path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames and list(reader.fieldnames) != list(self.fieldnames):
                raise ValueError(
                    f"{self.path} has columns {reader.fieldnames}, expected {self.fieldnames}: "
                    f"it was written by another version of the script. "
                    f"Move it away or re-run with --restart.")
            for row in reader:
                key = row.get(self.key_field, "")
                if key:
                    keys.add(key)
        if keys:
            print(f"  [resume] {len(keys):,} entities already in {self.path}: skipping them")
        return keys

    def write(self, row: dict) -> None:
        self._writer.writerow(row)
        self._fh.flush()
        self.done_keys.add(row.get(self.key_field, ""))
        self._pending += 1
        if self._pending >= self.sync_every:
            self._sync()

    def _sync(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._pending = 0

    def close(self) -> None:
        if not self._fh.closed:
            self._sync()
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def read_rows(path: str) -> list[dict]:
    """All rows of a finished (or partial) output file, for the final report."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
