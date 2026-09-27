"""SQLite storage: chats and messages.

Open a new connection per Streamlit run: sqlite3 connections must not be shared across threads.
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from wa.parser import chat_name_from_filename, parse_export

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  source_file TEXT,
  imported_at TEXT,
  message_count INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  sender TEXT,
  text TEXT NOT NULL,
  is_system INTEGER NOT NULL DEFAULT 0,
  has_media INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts);
"""

MESSAGE_COLUMNS = ("m.id, m.chat_id, c.name AS chat_name, m.ts, m.sender, m.text, "
                   "m.is_system, m.has_media")


def connect(path="data/wa.db") -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")   # SQLite ignores ON DELETE CASCADE without it
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def import_chat(db, file_path, name=None) -> int:
    messages = parse_export(file_path)       # parse first: a bad file must not delete the old chat
    name = name or chat_name_from_filename(file_path)
    with db:                                 # one transaction
        db.execute("DELETE FROM chats WHERE name = ?", (name,))   # re-import replaces
        chat_id = db.execute(
            "INSERT INTO chats (name, source_file, imported_at, message_count) VALUES (?, ?, ?, ?)",
            (name, Path(file_path).name, datetime.now().isoformat(timespec="seconds"), len(messages)),
        ).lastrowid
        db.executemany(
            "INSERT INTO messages (chat_id, ts, sender, text, is_system, has_media) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(chat_id, m["ts"], m["sender"], m["text"], m["is_system"], m["has_media"])
             for m in messages],
        )
    return chat_id


def list_chats(db) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT c.id, c.name, c.message_count, MIN(m.ts) AS first_ts, MAX(m.ts) AS last_ts "
        "FROM chats c LEFT JOIN messages m ON m.chat_id = c.id "
        "GROUP BY c.id ORDER BY c.name"
    ).fetchall()


def get_messages(db, chat_ids, date_from=None, date_to=None) -> list[sqlite3.Row]:
    """date_from/date_to: datetime.date or 'YYYY-MM-DD'; both inclusive (whole days)."""
    chat_ids = list(chat_ids)
    if not chat_ids:
        return []
    sql = (f"SELECT {MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id "
           f"WHERE m.chat_id IN ({','.join('?' * len(chat_ids))})")
    params = chat_ids
    if date_from:
        sql += " AND m.ts >= ?"
        params.append(str(date_from))
    if date_to:
        sql += " AND m.ts < ?"
        params.append((date.fromisoformat(str(date_to)) + timedelta(days=1)).isoformat())
    return db.execute(sql + " ORDER BY m.ts, m.id", params).fetchall()


def get_message(db, message_id) -> sqlite3.Row | None:
    return db.execute(
        f"SELECT {MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id WHERE m.id = ?",
        (message_id,),
    ).fetchone()


def get_context(db, message_id, before=2, after=2) -> list[sqlite3.Row]:
    """The message plus its neighbours in the same chat, chronological. [] if the ID is unknown."""
    m = get_message(db, message_id)
    if m is None:
        return []
    base = f"SELECT {MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id WHERE m.chat_id = ? "
    prev = db.execute(base + "AND (m.ts, m.id) < (?, ?) ORDER BY m.ts DESC, m.id DESC LIMIT ?",
                      (m["chat_id"], m["ts"], m["id"], before)).fetchall()
    next_ = db.execute(base + "AND (m.ts, m.id) > (?, ?) ORDER BY m.ts, m.id LIMIT ?",
                       (m["chat_id"], m["ts"], m["id"], after)).fetchall()
    return prev[::-1] + [m] + next_


def get_messages_by_id(db, message_ids) -> list[sqlite3.Row]:
    """The messages with these IDs (unknown IDs are skipped), chronological."""
    ids = list(message_ids)
    if not ids:
        return []
    return db.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id "
                      f"WHERE m.id IN ({','.join('?' * len(ids))}) ORDER BY m.ts, m.id", ids).fetchall()


def delete_chat(db, chat_id) -> str | None:
    """Delete a chat and its messages. Returns the name of the export file it was imported from."""
    row = db.execute("SELECT source_file FROM chats WHERE id = ?", (chat_id,)).fetchone()
    with db:
        db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))   # messages go with it (ON DELETE CASCADE)
    return row["source_file"] if row else None
