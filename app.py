"""Chinese–Uzbek dictionary web app."""

from flask import Flask, abort, render_template, request

from database import get_connection, init_db, seed_sample_if_empty
from pinyin_utils import convert_pinyin
from admin import admin_bp
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lugat_secret_key_2024")
csrf = CSRFProtect(app)
app.register_blueprint(admin_bp)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "30 per minute"],
    storage_uri="memory://"
)

init_db()
seed_sample_if_empty()


def _glosses(text: str | None) -> list[str]:
    """Split CC-CEDICT-style 'a | b | c' gloss lists."""
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _gloss_sql_patterns(query: str) -> tuple[str, str, str, str]:
    """LIKE patterns that match one pipe-separated gloss segment."""
    q = query.strip()
    return (
        q,
        f"{q} |%",
        f"%| {q}",
        f"%| {q} |%",
    )


def _glosses_match(query: str, text: str | None) -> bool:
    """True if query matches any gloss in a pipe-separated field."""
    q = query.strip()
    if not q:
        return False
    q_fold = q.casefold()
    for gloss in _glosses(text):
        gf = gloss.casefold()
        if gf == q_fold or q_fold in gf:
            return True
    return False


def _chinese_matches(query: str, row: dict) -> bool:
    """Chinese / pinyin search (unchanged behaviour)."""
    q = query.strip()
    chinese = row.get("chinese") or ""
    pinyin = (row.get("pinyin") or "").casefold()
    if q in chinese:
        return True
    return q.casefold() in pinyin


def _row_matches(query: str, row: dict) -> bool:
    q = query.strip()
    if not q:
        return False
    if _chinese_matches(q, row):
        return True
    if _glosses_match(q, row.get("english")):
        return True
    if _glosses_match(q, row.get("uzbek")):
        return True
    return False


def _match_tier(query: str, row: dict) -> int:
    """
    Lower tier = better match (shown first).
    0 exact, 1 prefix, 2 substring in gloss / chinese / pinyin.
    """
    q = query.strip()
    q_fold = q.casefold()

    chinese = row.get("chinese") or ""
    pinyin = (row.get("pinyin") or "").casefold()

    if chinese == q or pinyin == q_fold:
        return 0

    for gloss in _glosses(row.get("english")) + _glosses(row.get("uzbek")):
        if gloss.casefold() == q_fold:
            return 0

    if chinese.startswith(q) or pinyin.startswith(q_fold):
        return 1

    for gloss in _glosses(row.get("english")) + _glosses(row.get("uzbek")):
        if gloss.casefold().startswith(q_fold):
            return 1

    if q in chinese or q_fold in pinyin:
        return 2

    for gloss in _glosses(row.get("english")) + _glosses(row.get("uzbek")):
        if q_fold in gloss.casefold():
            return 2

    return 3


def _fetch_candidates(conn, q: str, cap: int) -> list[dict]:
    """SQL pre-filter; final matching uses per-gloss logic in Python."""
    gloss = _gloss_sql_patterns(q)
    broad = f"%{q}%"
    rows = conn.execute(
        """
        SELECT id, uzbek, english, chinese, pinyin,
               example_chinese, example_uzbek
        FROM words
        WHERE chinese LIKE ?
           OR pinyin LIKE ? COLLATE NOCASE
           OR english = ? COLLATE NOCASE
           OR english LIKE ? COLLATE NOCASE
           OR english LIKE ? COLLATE NOCASE
           OR english LIKE ? COLLATE NOCASE
           OR english LIKE ? COLLATE NOCASE
           OR uzbek = ? COLLATE NOCASE
           OR uzbek LIKE ? COLLATE NOCASE
           OR uzbek LIKE ? COLLATE NOCASE
           OR uzbek LIKE ? COLLATE NOCASE
           OR uzbek LIKE ? COLLATE NOCASE
        LIMIT ?
        """,
        (
            broad,
            broad,
            *gloss,
            broad,
            *gloss,
            broad,
            cap,
        ),
    ).fetchall()
    return [dict(r) for r in rows]


def _display_row(row: dict) -> dict:
    """Format a word row for templates (tone-marked pinyin)."""
    out = dict(row)
    if out.get("pinyin"):
        out["pinyin"] = convert_pinyin(out["pinyin"])
    return out


def search_words(query: str, limit: int = 50):
    q = query.strip()
    if not q:
        return []

    with get_connection() as conn:
        # Exact gloss hits first (no row cap) so "computer" always finds 电脑.
        gloss = _gloss_sql_patterns(q)
        exact_rows = conn.execute(
            """
            SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek
            FROM words
            WHERE chinese = ?
               OR english = ? COLLATE NOCASE
               OR english LIKE ? COLLATE NOCASE
               OR english LIKE ? COLLATE NOCASE
               OR english LIKE ? COLLATE NOCASE
               OR uzbek = ? COLLATE NOCASE
               OR uzbek LIKE ? COLLATE NOCASE
               OR uzbek LIKE ? COLLATE NOCASE
               OR uzbek LIKE ? COLLATE NOCASE
            """,
            (q, *gloss, *gloss),
        ).fetchall()

        seen: set[int] = set()
        results: list[dict] = []

        for row in sorted(
            (dict(r) for r in exact_rows if _row_matches(q, dict(r))),
            key=lambda r: (_match_tier(q, r), r.get("chinese") or ""),
        ):
            rid = row["id"]
            if rid in seen:
                continue
            seen.add(rid)
            results.append(row)
            if len(results) >= limit:
                return [_display_row(r) for r in results[:limit]]

        need = limit - len(results)
        if need > 0:
            partial = _fetch_candidates(conn, q, max(need * 40, 2000))
            partial = [r for r in partial if r["id"] not in seen and _row_matches(q, r)]
            partial.sort(
                key=lambda r: (_match_tier(q, r), r.get("chinese") or ""),
            )
            for row in partial:
                seen.add(row["id"])
                results.append(row)
                if len(results) >= limit:
                    break

    return [_display_row(r) for r in results[:limit]]


def get_word(word_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek
            FROM words WHERE id = ?
            """,
            (word_id,),
        ).fetchone()
    if not row:
        return None
    return _display_row(dict(row))


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    results = search_words(q) if q else []
    return render_template("index.html", q=q, results=results)


@app.route("/word/<int:word_id>")
def word_detail(word_id: int):
    word = get_word(word_id)
    if not word:
        abort(404)
    return render_template("word.html", word=word)


if __name__ == "__main__":
    app.run(debug=True)
