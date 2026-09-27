from datetime import date
from pathlib import Path

import pytest

from wa.store import (connect, delete_chat, get_context, get_message, get_messages, get_messages_by_id, import_chat,
                      list_chats)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    conn = connect(":memory:")
    yield conn
    conn.close()


def test_connect_creates_folder_and_enables_foreign_keys(tmp_path):
    conn = connect(tmp_path / "sub" / "wa.db")
    assert (tmp_path / "sub" / "wa.db").exists()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_import_and_list_main_fixtures(db):
    ids = [import_chat(db, FIXTURES / "android_it.txt", name="Marco"),
           import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto"),
           import_chat(db, FIXTURES / "english_us.txt")]
    assert len(set(ids)) == 3
    chats = {c["name"]: dict(c) for c in list_chats(db)}
    assert chats == {
        "Calcetto": {"id": ids[1], "name": "Calcetto", "message_count": 16,
                     "first_ts": "2026-09-01T18:00:00", "last_ts": "2026-09-03T22:47:15"},
        "Marco": {"id": ids[0], "name": "Marco", "message_count": 150,
                  "first_ts": "2026-09-01T09:12:00", "last_ts": "2026-09-26T23:58:00"},
        "english_us": {"id": ids[2], "name": "english_us", "message_count": 10,
                       "first_ts": "2025-12-05T09:02:00", "last_ts": "2025-12-25T15:05:00"},
    }
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 176


def test_stored_fields(db):
    chat_id = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    msgs = get_messages(db, [chat_id])
    assert msgs[0]["sender"] is None and msgs[0]["is_system"] == 1
    media = [m for m in msgs if m["has_media"]]
    assert [m["text"] for m in media] == ["immagine omessa", "sticker omesso"]
    assert all(m["chat_name"] == "Calcetto" for m in msgs)
    assert db.execute("SELECT source_file FROM chats").fetchone()[0] == "iphone_it.zip"


def test_reimport_replaces(db):
    import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    import_chat(db, FIXTURES / "android_it.txt", name="Marco")
    new_id = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    chats = list_chats(db)
    assert [c["name"] for c in chats] == ["Bob", "Marco"]
    assert db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (new_id,)).fetchone()[0] == 10
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 160


def test_failed_import_keeps_old_chat(db, tmp_path):
    import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    bad = tmp_path / "bad.txt"
    bad.write_text("not a chat", encoding="utf-8")
    with pytest.raises(ValueError):
        import_chat(db, bad, name="Bob")
    assert list_chats(db)[0]["message_count"] == 10
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 10


def test_default_name_from_filename(db, tmp_path):
    f = tmp_path / "WhatsApp Chat with Bob.txt"
    f.write_bytes((FIXTURES / "english_us.txt").read_bytes())
    import_chat(db, f)
    assert list_chats(db)[0]["name"] == "Bob"


def test_get_messages_chronological_across_chats(db):
    a = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    b = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    msgs = get_messages(db, [b, a])
    assert len(msgs) == 26
    assert [m["ts"] for m in msgs] == sorted(m["ts"] for m in msgs)
    assert msgs[0]["chat_name"] == "Bob" and msgs[-1]["chat_name"] == "Calcetto"
    assert get_messages(db, []) == []


def test_date_filters(db):
    chat_id = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    # date_to includes the whole last day (15:04 and 15:05 on 25 December).
    msgs = get_messages(db, [chat_id], date(2025, 12, 20), date(2025, 12, 25))
    assert [m["ts"] for m in msgs] == [
        "2025-12-20T19:45:00", "2025-12-20T19:46:00", "2025-12-21T00:15:00",
        "2025-12-21T12:30:00", "2025-12-25T15:04:00", "2025-12-25T15:05:00",
    ]
    # Single day, as strings; 00:15 on the 21st is outside the 20th.
    msgs = get_messages(db, [chat_id], "2025-12-20", "2025-12-20")
    assert [m["ts"] for m in msgs] == ["2025-12-20T19:45:00", "2025-12-20T19:46:00"]
    assert len(get_messages(db, [chat_id], date_from=date(2025, 12, 21))) == 4
    assert len(get_messages(db, [chat_id], date_to=date(2025, 12, 5))) == 4
    assert get_messages(db, [chat_id], date(2026, 1, 1), date(2026, 1, 31)) == []


def test_get_message(db):
    chat_id = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    first = get_messages(db, [chat_id])[1]
    m = get_message(db, first["id"])
    assert (m["chat_name"], m["sender"], m["ts"]) == ("Bob", "Alice", "2025-12-05T09:03:00")
    assert get_message(db, 999_999) is None


def test_context_middle_start_end(db):
    import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    other = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    ids = [m["id"] for m in get_messages(db, [other])]

    ctx = get_context(db, ids[5])
    assert [m["id"] for m in ctx] == ids[3:8]
    assert all(m["chat_name"] == "Calcetto" for m in ctx)

    assert [m["id"] for m in get_context(db, ids[0])] == ids[:3]       # start of chat
    assert [m["id"] for m in get_context(db, ids[1])] == ids[:4]
    assert [m["id"] for m in get_context(db, ids[-1])] == ids[-3:]     # end of chat
    assert [m["id"] for m in get_context(db, ids[-1], before=4, after=0)] == ids[-5:]
    assert get_context(db, 999_999) == []


def test_context_same_timestamp(db):
    # iPhone fixture: the first two messages share 2026-09-01T18:00:00.
    chat_id = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    ids = [m["id"] for m in get_messages(db, [chat_id])]
    assert [m["id"] for m in get_context(db, ids[1], before=1, after=1)] == ids[:3]


def test_get_messages_by_id(db):
    marco = import_chat(db, FIXTURES / "android_it.txt", name="Marco")
    calcetto = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    first_marco = get_messages(db, [marco])[0]["id"]
    first_calcetto = get_messages(db, [calcetto])[0]["id"]
    rows = get_messages_by_id(db, [first_calcetto, 99999, first_marco])
    assert [(r["id"], r["chat_name"]) for r in rows] == [(first_marco, "Marco"), (first_calcetto, "Calcetto")]
    assert get_messages_by_id(db, []) == []


def test_delete_chat(db):
    marco = import_chat(db, FIXTURES / "android_it.txt", name="Marco")
    import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    assert delete_chat(db, marco) == "android_it.txt"
    assert [c["name"] for c in list_chats(db)] == ["Calcetto"]
    assert db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (marco,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 16
    assert delete_chat(db, marco) is None
