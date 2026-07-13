"""Chinese–Uzbek dictionary web app."""

from flask import Flask, abort, render_template, request, make_response, redirect, url_for
import uuid

from database import get_connection, init_db, init_flashcards_db, init_collections_db, init_search_history_db, seed_sample_if_empty
from pinyin_utils import convert_pinyin
from admin import admin_bp
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
import os
import re

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
init_flashcards_db()
init_collections_db()
init_search_history_db()
seed_sample_if_empty()


def _glosses(text):
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]

def _gloss_head(gloss):
    """First word of a gloss, ignoring trailing clarifications like ' (erkak)'."""
    head = gloss.split("(")[0].split(",")[0].strip()
    return head.casefold()

def _gloss_sql_patterns(query):
    q = query.strip()
    return (q, f"{q} |%", f"%| {q}", f"%| {q} |%")


def _glosses_match(query, text):
    q = query.strip()
    if not q:
        return False
    q_fold = q.casefold()
    for gloss in _glosses(text):
        gf = gloss.casefold()
        if gf == q_fold or q_fold in gf:
            return True
    return False


def _chinese_matches(query, row):
    q = query.strip()
    chinese = row.get("chinese") or ""
    pinyin = (row.get("pinyin") or "").casefold()
    if q in chinese:
        return True
    return q.casefold() in pinyin


def _row_matches(query, row):
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


def _match_tier(query, row):
    q = query.strip()
    q_fold = q.casefold()
    chinese = row.get("chinese") or ""
    pinyin = (row.get("pinyin") or "").casefold()
    if chinese == q or pinyin == q_fold:
        return 0
    for gloss in _glosses(row.get("english")) + _glosses(row.get("uzbek")):
        if gloss.casefold() == q_fold or _gloss_head(gloss) == q_fold:
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


def _fetch_candidates(conn, q, cap):
    gloss = _gloss_sql_patterns(q)
    broad = f"%{q}%"
    rows = conn.execute(
        """
        SELECT id, uzbek, english, chinese, pinyin,
               example_chinese, example_uzbek, hsk_level
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
        (broad, broad, *gloss, broad, *gloss, broad, cap),
    ).fetchall()
    return [dict(r) for r in rows]


def _display_row(row):
    out = dict(row)
    if out.get("pinyin"):
        out["pinyin"] = convert_pinyin(out["pinyin"])
    return out


def _detect_language(query):
    q = query.strip()
    if any('\u4e00' <= ch <= '\u9fff' for ch in q):
        return 'chinese'
    tone_marks = 'āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ'
    if any(ch in tone_marks for ch in q.lower()):
        return 'pinyin'
    if re.search(r'[a-zA-Z][1-4]', q):
        return 'pinyin'
    return 'latin'


def search_words(query, limit=50):
    q = query.strip()
    if not q:
        return []

    lang = _detect_language(q)

    with get_connection() as conn:
        if lang == 'chinese':
            rows = conn.execute(
                """SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek, hsk_level
                   FROM words WHERE chinese LIKE ?
                   ORDER BY LENGTH(chinese) ASC LIMIT ?""",
                (f"%{q}%", limit)
            ).fetchall()
            return [_display_row(dict(r)) for r in rows]

        if lang == 'pinyin':
            rows = conn.execute(
                """SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek, hsk_level
                   FROM words WHERE pinyin LIKE ? COLLATE NOCASE
                   ORDER BY LENGTH(pinyin) ASC LIMIT ?""",
                (f"%{q}%", limit)
            ).fetchall()
            return [_display_row(dict(r)) for r in rows]

        broad = f"%{q}%"
        exact_rows = conn.execute(
            """SELECT id, uzbek, english, chinese, pinyin,
               example_chinese, example_uzbek, hsk_level
               FROM words
               WHERE uzbek LIKE ? COLLATE NOCASE
                  OR english LIKE ? COLLATE NOCASE""",
            (broad, broad),
        ).fetchall()

        seen = set()
        results = []

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
                break

        best_tier = min((_match_tier(q, r) for r in results), default=3)
        if len(results) < limit and best_tier > 1 and re.fullmatch(r"[a-zA-Z ]+", q):
            pinyin_rows = conn.execute(
                """SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek, hsk_level
                   FROM words WHERE pinyin LIKE ? COLLATE NOCASE
                   ORDER BY LENGTH(pinyin) ASC""",
                (f"%{q}%",)
            ).fetchall()
            for row in pinyin_rows:
                rid = row["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                results.append(dict(row))
                if len(results) >= limit:
                    break

    return [_display_row(r) for r in results[:limit]]


def get_word(word_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek, hsk_level
            FROM words WHERE id = ?""",
            (word_id,),
        ).fetchone()
    if not row:
        return None
    return _display_row(dict(row))


def is_in_flashcards(word_id):
    session_id = request.cookies.get("session_id", "")
    if not session_id:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM flashcards WHERE session_id = ? AND word_id = ?",
            (session_id, word_id),
        ).fetchone()
    return row is not None


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    results = search_words(q) if q else []

    session_id = request.cookies.get("session_id", "")
    if q:
        if not session_id:
            session_id = str(uuid.uuid4())
        with get_connection() as conn:
            last = conn.execute(
                "SELECT query FROM search_history WHERE session_id=? ORDER BY searched_at DESC LIMIT 1",
                (session_id,)
            ).fetchone()
            if last and last["query"].strip().casefold() == q.casefold():
                conn.execute(
                    "UPDATE search_history SET searched_at=CURRENT_TIMESTAMP WHERE session_id=? AND query=?",
                    (session_id, last["query"])
                )
            else:
                conn.execute(
                    "INSERT INTO search_history (session_id, query) VALUES (?, ?)",
                    (session_id, q)
                )
            conn.commit()

    recent_searches = []
    if session_id:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT query, MAX(searched_at) as last_time
                FROM search_history
                WHERE session_id = ?
                GROUP BY query
                ORDER BY last_time DESC
                LIMIT 10
                """,
                (session_id,)
            ).fetchall()
            recent_searches = [r["query"] for r in rows]

    resp = make_response(render_template("index.html", q=q, results=results, recent_searches=recent_searches))
    if session_id:
        resp.set_cookie("session_id", session_id, max_age=60*60*24*365)
    return resp


@app.route("/word/<int:word_id>")
def word_detail(word_id):
    word = get_word(word_id)
    if not word:
        abort(404)
    in_flashcards = is_in_flashcards(word_id)
    session_id = request.cookies.get("session_id", "")
    collections = []
    if session_id:
        with get_connection() as conn:
            cols = conn.execute(
                "SELECT id, name FROM collections WHERE session_id = ?",
                (session_id,)
            ).fetchall()
            collections = [dict(c) for c in cols]
    return render_template("word.html", word=word, in_flashcards=in_flashcards, collections=collections)

@app.route("/flashcards")
def flashcards():
    session_id = request.cookies.get("session_id", "")
    folder = request.args.get("folder", "")

    if not session_id:
        return render_template("flashcards.html",
            collections=[], hsk_counts={},
            active_folder="", active_name="", cards=[])

    with get_connection() as conn:
        # HSK counts
        hsk_rows = conn.execute(
            """SELECT w.hsk_level, COUNT(*) as cnt
               FROM flashcards f JOIN words w ON w.id = f.word_id
               WHERE f.session_id = ? AND w.hsk_level IS NOT NULL
               GROUP BY w.hsk_level""",
            (session_id,)
        ).fetchall()
        hsk_counts = {r["hsk_level"]: r["cnt"] for r in hsk_rows}

        # User collections
        cols = conn.execute(
            """SELECT c.id, c.name,
               (SELECT COUNT(*) FROM collection_words cw WHERE cw.collection_id = c.id) as word_count
               FROM collections c WHERE c.session_id = ?""",
            (session_id,)
        ).fetchall()
        collections = [dict(c) for c in cols]

        # Active folder cards
        cards = []
        active_name = ""
        if folder.startswith("hsk-"):
            level = int(folder.split("-")[1])
            active_name = f"HSK {level}"
            rows = conn.execute(
                """SELECT w.id, w.chinese, w.pinyin, w.uzbek, w.english,
                       w.example_chinese, w.example_uzbek, w.hsk_level
                   FROM flashcards f JOIN words w ON w.id = f.word_id
                   WHERE f.session_id = ? AND w.hsk_level = ?
                   ORDER BY f.added_at DESC""",
                (session_id, level)
            ).fetchall()
            cards = [_display_row(dict(r)) for r in rows]
        elif folder.startswith("c-"):
            col_id = int(folder.split("-")[1])
            col = conn.execute(
                "SELECT name FROM collections WHERE id=? AND session_id=?",
                (col_id, session_id)
            ).fetchone()
            if col:
                active_name = col["name"]
                rows = conn.execute(
                    """SELECT w.id, w.chinese, w.pinyin, w.uzbek, w.english,
                           w.example_chinese, w.example_uzbek, w.hsk_level
                       FROM collection_words cw JOIN words w ON w.id = cw.word_id
                       WHERE cw.collection_id = ?
                       ORDER BY cw.added_at DESC""",
                    (col_id,)
                ).fetchall()
                cards = [_display_row(dict(r)) for r in rows]

    resp = make_response(render_template("flashcards.html",
        collections=collections,
        hsk_counts=hsk_counts,
        active_folder=folder,
        active_name=active_name,
        cards=cards
    ))
    resp.set_cookie("session_id", session_id, max_age=60*60*24*365)
    return resp


@app.route("/flashcards/add/<int:word_id>", methods=["POST"])
def flashcard_add(word_id):
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
    collection_id = request.form.get("collection_id", "").strip()
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO flashcards (session_id, word_id) VALUES (?, ?)",
                (session_id, word_id),
            )
            conn.commit()
        except Exception:
            pass
        if collection_id:
            try:
                conn.execute(
                    "INSERT INTO collection_words (collection_id, word_id) VALUES (?, ?)",
                    (collection_id, word_id),
                )
                conn.commit()
            except Exception:
                pass
    resp = make_response(redirect(url_for("word_detail", word_id=word_id)))
    resp.set_cookie("session_id", session_id, max_age=60*60*24*365)
    return resp


@app.route("/flashcards/remove/<int:word_id>", methods=["POST"])
def flashcard_remove(word_id):
    session_id = request.cookies.get("session_id", "")
    if session_id:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM flashcards WHERE session_id = ? AND word_id = ?",
                (session_id, word_id),
            )
            conn.commit()
    return redirect(url_for("flashcards"))

@app.route("/flashcards/collections/create", methods=["POST"])
def collection_create():
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
    name = request.form.get("name", "").strip()
    if name:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO collections (session_id, name) VALUES (?, ?)",
                (session_id, name)
            )
            conn.commit()
    resp = make_response(redirect(url_for("flashcards")))
    resp.set_cookie("session_id", session_id, max_age=60*60*24*365)
    return resp


@app.route("/flashcards/collections/<int:collection_id>/rename", methods=["POST"])
def collection_rename(collection_id):
    session_id = request.cookies.get("session_id", "")
    name = request.form.get("name", "").strip()
    if name and session_id:
        with get_connection() as conn:
            conn.execute(
                "UPDATE collections SET name=? WHERE id=? AND session_id=?",
                (name, collection_id, session_id)
            )
            conn.commit()
    return redirect(url_for("flashcards"))


@app.route("/flashcards/collections/<int:collection_id>/delete", methods=["POST"])
def collection_delete(collection_id):
    session_id = request.cookies.get("session_id", "")
    if session_id:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM collections WHERE id=? AND session_id=?",
                (collection_id, session_id)
            )
            conn.commit()
    return redirect(url_for("flashcards"))

if __name__ == "__main__":
    app.run(debug=True)