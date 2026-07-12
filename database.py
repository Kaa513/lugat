"""SQLite setup for the Chinese–Uzbek dictionary."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "dictionary.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uzbek TEXT NOT NULL,
                english TEXT,
                chinese TEXT NOT NULL,
                pinyin TEXT,
                example_chinese TEXT,
                example_uzbek TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_words_chinese ON words (chinese)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_words_uzbek ON words (uzbek)
            """
        )


def seed_sample_if_empty() -> None:
    """Insert a few rows so the app is demo-ready on first run."""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM words").fetchone()["c"]
        if count > 0:
            return
        samples = [
            (
                "salom",
                "hello",
                "你好",
                "nǐ hǎo",
                "你好，很高兴认识你。",
                "Salom, tanishganimdan xursandman.",
            ),
            (
                "rahmat",
                "thank you",
                "谢谢",
                "xiè xie",
                "谢谢你的帮助。",
                "Yordaming uchun rahmat.",
            ),
            (
                "kitob",
                "book",
                "书",
                "shū",
                "这是一本好书。",
                "Bu yaxshi kitob.",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO words (
                uzbek, english, chinese, pinyin,
                example_chinese, example_uzbek
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            samples,
        )

def init_flashcards_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flashcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                word_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (word_id) REFERENCES words(id),
                UNIQUE(session_id, word_id)
            )
            """
        )

def init_collections_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (collection_id) REFERENCES collections(id),
                FOREIGN KEY (word_id) REFERENCES words(id),
                UNIQUE(collection_id, word_id)
            )
            """
        )

def init_search_history_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                query TEXT NOT NULL,
                searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )