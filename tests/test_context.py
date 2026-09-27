from pathlib import Path

import pytest

from wa.context import build_transcript, estimate_tokens, format_message, usage_level
from wa.store import connect, get_messages, import_chat

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    conn = connect(":memory:")
    yield conn
    conn.close()


def msg(**kw):
    return {"id": 1234, "ts": "2026-09-26T14:32:00", "sender": "Marco", "text": "ciao",
            "is_system": 0, "has_media": 0, **kw}


def test_format_message():
    assert format_message(msg()) == "[#1234] 26/09/26 14:32 Marco: ciao"
    assert format_message(msg(id=1235, ts="2026-09-26T14:33:45", sender=None,
                              text="Marco ha aggiunto Giulia", is_system=1)) == (
        "[#1235] 26/09/26 14:33 (system) Marco ha aggiunto Giulia")
    assert format_message(msg(text="<Media omessi>", has_media=1)) == (
        "[#1234] 26/09/26 14:32 Marco: <Media omessi>")
    assert format_message(msg(text="Lista:\n- latte\n- pane")) == (
        "[#1234] 26/09/26 14:32 Marco: Lista:\n- latte\n- pane")


def test_format_message_from_db_row(db):
    chat_id = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    rows = get_messages(db, [chat_id])
    assert format_message(rows[0]).startswith(f"[#{rows[0]['id']}] 01/09/26 18:00 (system) I messaggi")
    assert format_message(rows[3]) == f"[#{rows[3]['id']}] 01/09/26 18:01 Luca Verdi: " + rows[3]["text"]


def test_transcript_two_chats(db):
    bob = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    calcetto = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    t = build_transcript(db, [bob, calcetto])
    lines = t.split("\n")
    assert lines[:4] == ['<documents>', '  <document index="1">', "    <source>Bob</source>",
                         "    <document_content>"]
    assert lines[-3:] == ["    </document_content>", "  </document>", "</documents>"]
    assert t.count("<document index=") == 2
    assert '  <document index="2">\n    <source>Calcetto</source>\n    <document_content>\n' in t

    # Every message appears once, inside its own chat's block.
    bob_block, calcetto_block = t.split('<document index="2">')
    for m in get_messages(db, [bob]):
        assert bob_block.count(f"[#{m['id']}] ") == 1
    for m in get_messages(db, [calcetto]):
        assert calcetto_block.count(f"[#{m['id']}] ") == 1

    # Multi-line message: continuation lines have no [#.
    multi = next(m for m in get_messages(db, [calcetto]) if "\n" in m["text"])
    continuation = multi["text"].split("\n")[1]
    assert f"\n{continuation}\n" in t and not continuation.startswith("[#")


def test_transcript_date_filter(db):
    bob = import_chat(db, FIXTURES / "english_us.txt", name="Bob")
    calcetto = import_chat(db, FIXTURES / "iphone_it.zip", name="Calcetto")
    t = build_transcript(db, [bob, calcetto], "2025-12-20", "2025-12-21")
    assert t.count("[#") == 4
    assert "<source>Calcetto</source>" not in t        # no messages in range: no block
    assert '<document index="1">\n    <source>Bob</source>' in t
    assert "20/12/25 19:45 Bob: On my way" in t and "05/12/25" not in t
    assert build_transcript(db, [bob], "2030-01-01", "2030-12-31") == ""
    assert build_transcript(db, []) == ""


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("x" * 3001) == 1000


def test_usage_level():
    assert usage_level(0) == "low"
    assert usage_level(29_999) == "low"
    assert usage_level(30_000) == "medium"
    assert usage_level(100_000) == "medium"
    assert usage_level(100_001) == "high"


def test_selection_summary(db):
    chat_id = import_chat(db, FIXTURES / "android_it.txt", name="Marco")
    count = len(get_messages(db, [chat_id]))
    tokens = estimate_tokens(build_transcript(db, [chat_id]))
    assert count == 150
    assert tokens > 2_000          # the large fixture used by the live tests
    assert usage_level(tokens) == "low"
