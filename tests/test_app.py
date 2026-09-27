"""The Streamlit UI, run with AppTest in a temporary folder and a fake engine (never calls Claude)."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from wa import store
from wa.engines import subscription
from wa.engines.subscription import EngineError

PROJECT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


class FakeEngine:
    def __init__(self, answers):
        self.answers = list(answers)   # str -> answer text, Exception -> raised
        self.calls = []

    def __call__(self, transcript, question, session=None, model=None):
        self.calls.append({"transcript": transcript, "question": question, "session": session, "model": model})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"text": answer, "session": f"sess-{len(self.calls)}", "usage": None}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # the app uses data/ in the current folder
    return AppTest.from_file(str(PROJECT / "app.py"), default_timeout=30)


@pytest.fixture
def chats(tmp_path, app):
    db = store.connect("data/wa.db")
    ids = {"Marco": store.import_chat(db, FIXTURES / "android_it.txt", "Marco"),
           "Calcetto": store.import_chat(db, FIXTURES / "iphone_it.zip", "Calcetto")}
    db.close()
    return ids


def fake(monkeypatch, *answers):
    engine = FakeEngine(answers)
    monkeypatch.setattr(subscription, "ask", engine)
    return engine


def sidebar_text(at):
    return "\n".join(e.value for e in [*at.sidebar.markdown, *at.sidebar.caption, *at.sidebar.warning,
                                       *at.sidebar.error, *at.sidebar.success])


def select(at, *chat_ids):
    at.sidebar.multiselect[0].set_value(list(chat_ids)).run()


def ask(at, question):
    at.chat_input[0].set_value(question).run()


def test_empty_start(app):
    app.run()
    assert not app.exception
    assert "Import a WhatsApp export" in app.info[0].value
    assert app.chat_input[0].proto.disabled


def test_upload_imports_once_and_shows_errors(app, tmp_path, monkeypatch):
    calls = []
    real_import = store.import_chat
    monkeypatch.setattr(store, "import_chat", lambda db, path: calls.append(path) or real_import(db, path))
    app.run()
    app.sidebar.file_uploader[0].set_value([
        ("Chat WhatsApp con Marco.txt", (FIXTURES / "android_it.txt").read_bytes(), "text/plain"),
        ("WhatsApp Chat - Calcetto.zip", (FIXTURES / "iphone_it.zip").read_bytes(), "application/zip"),
        ("notes.txt", b"just some notes, not a chat", "text/plain"),
    ]).run()
    assert not app.exception
    assert [s.value for s in app.sidebar.success] == ["Imported “Marco”: 150 messages.",
                                                      "Imported “Calcetto”: 16 messages."]
    assert "No WhatsApp messages found in notes.txt" in app.sidebar.error[0].value
    assert (tmp_path / "data" / "Chat WhatsApp con Marco.txt").exists()
    assert (tmp_path / "data" / "wa.db").exists()
    assert len(calls) == 3

    app.run()                                    # reruns must not import again
    app.run()
    assert len(calls) == 3
    assert len(app.sidebar.success) == 2 and len(app.sidebar.error) == 1
    labels = app.sidebar.multiselect[0].options
    assert labels == ["Calcetto · 16 messages · 01/09/26–03/09/26",
                      "Marco · 150 messages · 01/09/26–26/09/26"]


def test_import_keeps_selection_unless_chat_replaced(app, chats, monkeypatch):
    fake(monkeypatch, "a [#27]")
    app.run()
    select(app, chats["Marco"])
    ask(app, "q1")
    app.sidebar.file_uploader[0].set_value(
        ("english.txt", (FIXTURES / "english_us.txt").read_bytes(), "text/plain")).run()
    assert app.sidebar.multiselect[0].value == [chats["Marco"]]
    assert len(app.chat_message) == 2
    # Re-importing a selected chat gives its messages new IDs: it is unselected and the conversation restarts.
    app.sidebar.file_uploader[0].set_value(
        ("Chat WhatsApp con Marco.txt", (FIXTURES / "android_it.txt").read_bytes(), "text/plain")).run()
    assert not app.exception
    assert app.sidebar.multiselect[0].value == []
    assert len(app.chat_message) == 0


def test_selection_indicator_and_dates(app, chats):
    app.run()
    assert "Choose one or more chats" in app.info[0].value
    assert app.chat_input[0].proto.disabled
    select(app, chats["Marco"])
    assert not app.exception
    text = sidebar_text(app)
    assert "**150** messages selected" in text and "Usage: **low**" in text
    assert not app.chat_input[0].proto.disabled
    frm, to = app.sidebar.date_input
    assert (frm.value, to.value) == (date(2026, 9, 1), date(2026, 9, 26))

    select(app, chats["Marco"], chats["Calcetto"])
    assert "**166** messages selected" in sidebar_text(app)

    app.sidebar.date_input[0].set_value(date(2026, 9, 4)).run()
    app.sidebar.date_input[1].set_value(date(2026, 9, 3)).run()
    assert "No messages in this date range." in sidebar_text(app)
    assert app.chat_input[0].proto.disabled


def test_over_budget_blocks_input(app, chats, monkeypatch):
    monkeypatch.setattr(subscription, "TOKEN_BUDGET", {"sonnet": 1_000, "haiku": 100_000})
    app.run()
    select(app, chats["Marco"])
    assert "over the 1,000 limit for sonnet" in app.sidebar.error[0].value
    assert app.chat_input[0].proto.disabled
    app.sidebar.selectbox[0].set_value("haiku").run()
    assert not app.sidebar.error
    assert not app.chat_input[0].proto.disabled


def test_ask_cite_follow_up_and_reset(app, chats, monkeypatch):
    engine = fake(monkeypatch, "670 euro [#27][#28], see also [#99999].", "By the 5th [#29].", "Other [#27].")
    app.run()
    select(app, chats["Marco"])
    ask(app, "Quanto è l'affitto?")
    assert not app.exception
    first = engine.calls[0]
    assert first["session"] is None and first["model"] == "sonnet"
    assert first["transcript"].startswith("<documents>") and "<source>Marco</source>" in first["transcript"]
    assert [m.value for m in app.chat_message[0].markdown] == ["Quanto è l'affitto?"]
    assert "670 euro" in app.chat_message[1].markdown[0].value

    cited = app.chat_message[1].expander[0]
    assert cited.label == "Cited messages (2)"       # [#99999] is not in the selection
    assert len(cited.info) == 2                       # the cited messages, highlighted
    assert any("#27" in i.value for i in cited.info) and any("#28" in i.value for i in cited.info)
    assert len(cited.caption) >= 4                    # neighbours: 2 before and 2 after each
    assert "Marco" in cited.markdown[0].value

    ask(app, "E da quando?")
    assert engine.calls[1]["session"] == "sess-1"
    assert len(app.chat_message) == 4

    app.sidebar.selectbox[0].set_value("haiku").run()  # other model: new conversation
    assert len(app.chat_message) == 0
    ask(app, "Ancora?")
    assert engine.calls[2]["session"] is None and engine.calls[2]["model"] == "haiku"


def test_changing_chats_or_dates_resets_conversation(app, chats, monkeypatch):
    engine = fake(monkeypatch, "a [#27]", "b", "c")
    app.run()
    select(app, chats["Marco"])
    ask(app, "q1")
    select(app, chats["Marco"], chats["Calcetto"])
    assert len(app.chat_message) == 0
    ask(app, "q2")
    app.sidebar.date_input[0].set_value(date(2026, 9, 2)).run()
    assert len(app.chat_message) == 0
    ask(app, "q3")
    assert [c["session"] for c in engine.calls] == [None, None, None]
    assert "2026-09-01" not in engine.calls[2]["transcript"] and "[#" in engine.calls[2]["transcript"]


def test_new_conversation_button(app, chats, monkeypatch):
    engine = fake(monkeypatch, "a", "b")
    app.run()
    select(app, chats["Marco"])
    assert app.button[0].proto.disabled
    ask(app, "q1")
    app.run()
    app.button[0].click().run()
    assert len(app.chat_message) == 0
    ask(app, "q2")
    assert engine.calls[1]["session"] is None


def test_engine_error_keeps_conversation(app, chats, monkeypatch):
    engine = fake(monkeypatch, "first [#27]", EngineError("Your plan's usage limit is reached. Try again after it resets."),
                  "third")
    app.run()
    select(app, chats["Marco"])
    ask(app, "q1")
    ask(app, "q2")
    assert not app.exception
    assert "usage limit is reached" in app.chat_message[3].error[0].value
    assert len(app.chat_message) == 4
    ask(app, "q3")
    assert engine.calls[2]["session"] == "sess-1"      # the failed question did not lose the session
    assert len(app.chat_message) == 6


def test_truncated_export_warning(app, tmp_path):
    lines = [f"{1 + i // 1440 % 28:02d}/0{1 + i // 40320}/25, {i // 60 % 24:02d}:{i % 60:02d} - Anna: msg {i}"
             for i in range(39_000)]
    big = tmp_path / "Chat WhatsApp con Gruppo.txt"
    big.write_text("\n".join(lines), encoding="utf-8")
    db = store.connect("data/wa.db")
    store.import_chat(db, big)
    db.close()
    app.run()
    assert not app.exception
    warning = app.sidebar.warning[0].value
    assert "“Gruppo” has 39,000 messages" in warning and "starts on 01/01/2025" in warning


def test_empty_message_and_opus(app, chats, monkeypatch):
    # Real exports contain lines like "14/09/26, 18:05 - Anna: " with no text at all.
    db = store.connect("data/wa.db")
    empty_id = db.execute("INSERT INTO messages (chat_id, ts, sender, text) VALUES (?, '2026-09-26T23:59:00', 'Anna', '')",
                          (chats["Marco"],)).lastrowid
    db.commit()
    db.close()
    engine = fake(monkeypatch, f"Vuoto [#{empty_id}]")
    app.run()
    select(app, chats["Marco"])
    app.sidebar.selectbox[0].set_value("opus").run()
    ask(app, "q")
    assert engine.calls[0]["model"] == "opus"
    cited = app.chat_message[1].expander[0]
    assert "(no text in the export)" in cited.info[0].value
