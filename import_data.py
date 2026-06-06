"""
Download CC-CEDICT and import entries into the local SQLite `words` table.

Uzbek is temporarily set equal to the English gloss text.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
import urllib.error
import urllib.request
from typing import Iterator

from database import get_connection, init_db

CEDICT_URL = (
    "https://www.mdbg.net/chinese/export/cedict/"
    "cedict_1_0_ts_utf-8_mdbg.txt.gz"
)

# Traditional simplified [pinyin] /glosses.../
LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/\s*$")


def split_definitions(blob: str) -> str:
    """Split CC-CEDICT gloss segment on unescaped `/` and join for storage."""
    parts: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(blob):
        ch = blob[i]
        if ch == "/" and (i == 0 or blob[i - 1] != "\\"):
            piece = "".join(cur).replace("\\/", "/").strip()
            if piece:
                parts.append(piece)
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    tail = "".join(cur).replace("\\/", "/").strip()
    if tail:
        parts.append(tail)
    return " | ".join(parts)


def iter_cedict_lines(url: str) -> Iterator[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "lugat-dictionary-import/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        with gzip.GzipFile(fileobj=resp) as gz:
            for raw in gz:
                yield raw.decode("utf-8", errors="replace").rstrip("\r\n")


def load_existing_keys(conn) -> set[tuple[str, str]]:
    rows = conn.execute("SELECT chinese, pinyin FROM words").fetchall()
    return {(r["chinese"], (r["pinyin"] or "").strip()) for r in rows}


def import_cedict(
    url: str,
    limit: int,
    conn,
    existing: set[tuple[str, str]],
) -> tuple[int, int, int]:
    """
    Returns (inserted, skipped_existing, skipped_unparseable).
    Stops after `inserted` reaches `limit`.
    """
    inserted = 0
    skipped_existing = 0
    skipped_unparseable = 0

    batch: list[tuple[str, str, str, str, None, None]] = []

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        conn.executemany(
            """
            INSERT INTO words (
                uzbek, english, chinese, pinyin,
                example_chinese, example_uzbek
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        conn.commit()
        batch = []

    for line in iter_cedict_lines(url):
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            skipped_unparseable += 1
            continue

        _traditional, simplified, pinyin, gloss_blob = m.groups()
        pinyin = pinyin.strip()
        english = split_definitions(gloss_blob)
        if not english:
            skipped_unparseable += 1
            continue

        key = (simplified, pinyin)
        if key in existing:
            skipped_existing += 1
            continue

        uzbek = english
        batch.append((uzbek, english, simplified, pinyin, None, None))
        existing.add(key)
        inserted += 1

        if len(batch) >= 200:
            flush()

        if inserted >= limit:
            break

    flush()
    return inserted, skipped_existing, skipped_unparseable


def main() -> int:
    parser = argparse.ArgumentParser(description="Import CC-CEDICT into SQLite.")
    parser.add_argument(
        "--url",
        default=CEDICT_URL,
        help="Gzipped CC-CEDICT .txt.gz URL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Stop after this many new rows inserted (default: 5000)",
    )
    args = parser.parse_args()

    init_db()
    conn = get_connection()
    try:
        existing = load_existing_keys(conn)
        print(f"Loaded {len(existing)} existing (chinese, pinyin) keys from database.")
        print(f"Downloading and parsing: {args.url}")
        inserted, skip_dup, skip_bad = import_cedict(
            args.url, args.limit, conn, existing
        )
        print(
            f"Done. Inserted: {inserted}, "
            f"skipped (already in DB): {skip_dup}, "
            f"skipped (unparseable): {skip_bad}"
        )
    except urllib.error.URLError as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"I/O error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
