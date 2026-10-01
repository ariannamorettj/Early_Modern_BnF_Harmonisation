"""Detect text-integrity problems in the pipeline's CSV cells.

Shared by 02_sampling/05_text_issue_sample.py (sample the rows that have a
problem) and 03_analysis/06_text_integrity_check.py (count them per column).

Issue types
-----------
invalid_utf8           the line's bytes are not valid UTF-8 (detected per
                       line, before the CSV is parsed).
replacement_char       U+FFFD: a decoder already replaced bytes it could not
                       read, so the original characters are lost.
double_encoded         UTF-8 read as Latin-1/cp1252 and written back
                       ("Ã©" for "é", "â€™" for "’"): recoverable by
                       re-encoding, if it is not a legitimate spelling.
control_char           C0/C1 control characters other than tab/newline.
serialised_rdf_literal a whole cell holding an RDF literal as text, e.g.
                       "France"@fr: the value was copied from a SPARQL
                       result without being unwrapped.

The detectors only look at text. Deciding whether a hit is an error (a
Portuguese "Ã" is legitimate) is left to the analysis reports and to
whoever reads the sampled rows.
"""

from __future__ import annotations

import csv
import re
import sys
from typing import Iterator

ISSUE_TYPES = (
    "invalid_utf8",
    "replacement_char",
    "double_encoded",
    "control_char",
    "serialised_rdf_literal",
)

# A UTF-8 continuation byte (0x80-0xBF) decoded as Latin-1 is U+0080-U+00BF;
# decoded as cp1252, bytes 0x80-0x9F become these punctuation letters instead.
_CP1252_HIGH = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
_CONTINUATION = f"[\u0080-¿{_CP1252_HIGH}]"
# "Ã"/"Â" (lead bytes of é, è, à, ...) followed by a continuation character,
# or "â€" (lead of ’ “ ” – …).
_DOUBLE_ENCODED = re.compile(f"[ÃÂ]{_CONTINUATION}|â€{_CONTINUATION}")
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]")
_RDF_LITERAL = re.compile(r'^"(.*)"(@[A-Za-z]{2,3}(-[A-Za-z0-9]+)*|\^\^<[^>]+>)$', re.S)


def detect_issues(value: str) -> list[str]:
    """Return the issue types found in one decoded cell value."""
    if not value:
        return []
    issues = []
    if "�" in value:
        issues.append("replacement_char")
    if _DOUBLE_ENCODED.search(value):
        issues.append("double_encoded")
    if _CONTROL.search(value):
        issues.append("control_char")
    if _RDF_LITERAL.match(value.strip()):
        issues.append("serialised_rdf_literal")
    return issues


def unwrap_rdf_literal(value: str) -> str:
    """'"France"@fr' -> 'France'; any other value is returned unchanged."""
    m = _RDF_LITERAL.match(value.strip())
    return m.group(1) if m else value


def iter_csv_rows(path: str) -> Iterator[tuple[int, dict[str, str] | None, bool]]:
    """Yield (line_number, row, line_is_valid_utf8) for a CSV file, streaming.

    Lines are decoded one at a time so that a single bad line is reported
    instead of aborting the read; an undecodable line is decoded with
    errors="replace" only to keep the CSV structure, and flagged.
    Quoted fields spanning several lines are handled by the csv module.
    """
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    invalid_lines: set[int] = set()

    def decoded_lines():
        with open(path, "rb") as fh:
            for n, raw in enumerate(fh, start=1):
                try:
                    yield raw.decode("utf-8")
                except UnicodeDecodeError:
                    invalid_lines.add(n)
                    yield raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(decoded_lines())
    for row in reader:
        line_no = reader.line_num
        yield line_no, row, line_no not in invalid_lines


def row_issues(row: dict[str, str], valid_utf8: bool) -> dict[str, list[str]]:
    """{column: [issue types]} for one row; 'invalid_utf8' goes on every column."""
    found: dict[str, list[str]] = {}
    for col, value in row.items():
        if col is None:
            continue
        issues = detect_issues(value or "")
        if not valid_utf8:
            issues = ["invalid_utf8"] + [i for i in issues if i != "replacement_char"]
        if issues:
            found[col] = issues
    return found


__all__ = ["ISSUE_TYPES", "detect_issues", "unwrap_rdf_literal", "iter_csv_rows", "row_issues"]
