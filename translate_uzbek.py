"""
Translate the `english` field to Uzbek and store in `uzbek`.

Only updates rows where `uzbek` still equals `english` (import placeholder).
"""

from __future__ import annotations

import argparse
import sys
import time

from deep_translator import GoogleTranslator

from database import get_connection, init_db

BATCH_SIZE = 10
PROGRESS_EVERY = 100
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2


def _needs_translation(english: str | None, uzbek: str | None) -> bool:
    if not english or not english.strip():
        return False
    if uzbek is None:
        return True
    return uzbek.strip() == english.strip()


def _translate_text(translator: GoogleTranslator, text: str) -> str:
    """Translate pipe-separated glosses one segment at a time."""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) == 1:
        return translator.translate(parts[0])

    translated: list[str] = []
    for part in parts:
        if not part:
            continue
        translated.append(translator.translate(part))
    return " | ".join(translated)


def _translate_with_retry(translator: GoogleTranslator, text: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _translate_text(translator, text)
        except Exception as exc:  # noqa: BLE001 — network/API errors vary
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC * attempt)
    raise RuntimeError(f"Translation failed after {MAX_RETRIES} tries") from last_error


def fetch_pending(conn, limit: int | None) -> list[dict]:
    sql = """
        SELECT id, english, uzbek
        FROM words
        WHERE english IS NOT NULL
          AND TRIM(english) != ''
          AND (uzbek IS NULL OR TRIM(uzbek) = TRIM(english))
        ORDER BY id
    """
    if limit is not None:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def run(limit: int | None) -> int:
    init_db()
    translator = GoogleTranslator(source="en", target="uz")

    with get_connection() as conn:
        pending = fetch_pending(conn, limit)
        total = len(pending)
        if total == 0:
            print("No words to translate (all uzbek fields differ from english).")
            return 0

        print(f"Translating {total} word(s) in batches of {BATCH_SIZE}…")

        translated_count = 0
        error_count = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch = pending[batch_start : batch_start + BATCH_SIZE]

            for row in batch:
                word_id = row["id"]
                english = (row["english"] or "").strip()
                uzbek = row["uzbek"]

                if not _needs_translation(english, uzbek):
                    continue

                try:
                    uzbek_text = _translate_with_retry(translator, english)
                except RuntimeError as exc:
                    error_count += 1
                    print(f"  skip id={word_id}: {exc}", file=sys.stderr)
                    continue

                conn.execute(
                    "UPDATE words SET uzbek = ? WHERE id = ?",
                    (uzbek_text, word_id),
                )
                translated_count += 1

                if translated_count % PROGRESS_EVERY == 0:
                    print(f"  … {translated_count} / {total} translated")

            conn.commit()
            time.sleep(0.3)

        print(f"Done. Translated: {translated_count}, errors: {error_count}")

    return 0 if error_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate english → uzbek for words in the SQLite database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of words to translate (default: all pending)",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 1
    return run(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
