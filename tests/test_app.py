"""The Streamlit UI, run with AppTest in a temporary folder and a fake engine (never calls Claude)."""

from datetime import date
from pathlib import Path

import dotenv
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from wa import export, store
from wa.engines import api, subscription
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
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)   # never load the user's real .env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st.cache_data.clear()
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
    monkeypatch.setattr(subscription, "TOKEN_BUDGET", {"sonnet": 1_000, "haiku": 100_000, "opus": 1_000})
    app.run()
    select(app, chats["Marco"])
    assert "over the 1,000 limit for sonnet. Choose haiku, or select fewer chats" in app.sidebar.error[0].value
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


class FakeStream:
    def __init__(self, text, error=None):
        self.text, self.error, self.result = text, error, None

    def __iter__(self):
        yield self.text[:3]
        if self.error:
            raise self.error
        yield self.text[3:]
        cached = 5_000 if self.text.startswith("B") else 0
        self.result = {"text": self.text, "session": ["history"], "cost_usd": 0.0152,
                       "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": cached,
                                 "cache_creation_input_tokens": 5_000 - cached}}


def fake_api(monkeypatch, *streams, tokens=100_000):
    calls = {"ask": [], "count": []}

    def ask_stream(transcript, question, session=None, model=None):
        calls["ask"].append({"question": question, "session": session, "model": model})
        return streams[len(calls["ask"]) - 1]

    def count_tokens(transcript, model):
        calls["count"].append(model)
        if isinstance(tokens, Exception):
            raise tokens
        return tokens

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(api, "ask_stream", ask_stream)
    monkeypatch.setattr(api, "count_tokens", count_tokens)
    monkeypatch.setattr(api, "ask", lambda *a, **kw: pytest.fail("the app must stream"))
    return calls


def test_api_engine_hidden_without_key_and_guide_shown(app, chats):
    app.run()
    assert app.sidebar.radio[0].options == ["Claude subscription (claude -p)"]
    assert "put your API key in `.env`" in sidebar_text(app)
    assert app.expander[0].label == "How to use it: what you can do, engine and model"
    assert "Haiku" in app.expander[0].markdown[0].value and "Opus" in app.expander[0].markdown[0].value
    assert app.sidebar.selectbox[0].options[0] == "sonnet · good for most questions"


def test_api_engine_counts_costs_streams(app, chats, monkeypatch):
    calls = fake_api(monkeypatch, FakeStream("A: 670 euro [#27]."), FakeStream("B: dal 5 [#29]."))
    app.run()
    select(app, chats["Marco"])
    assert "Usage: **low**" in sidebar_text(app)                     # subscription is still the default
    app.sidebar.radio[0].set_value("api").run()
    assert not app.exception
    assert app.sidebar.selectbox[0].value == "claude-sonnet-5"
    text = sidebar_text(app)
    assert "**100,000** tokens" in text and "estimated" not in text
    assert "Cost: about **\\$0.26** for the first question, **\\$0.03** for each follow-up" in text

    app.run()                                                       # a rerun does not count again (cached)
    assert calls["count"] == ["claude-sonnet-5"]

    ask(app, "Quanto?")
    assert not app.exception
    assert calls["ask"][0] == {"question": "Quanto?", "session": None, "model": "claude-sonnet-5"}
    answer = app.chat_message[1]
    assert [m.value for m in answer.markdown].count("A: 670 euro [#27].") == 1   # streamed once, not repeated
    assert answer.caption[0].value == "Cost of this question: \\$0.0152"
    assert answer.expander[0].label == "Cited messages (1)"

    ask(app, "E da quando?")
    assert calls["ask"][1]["session"] == ["history"]
    assert "(5,000 tokens read from the cache)" in app.chat_message[3].caption[0].value
    app.run()                                                       # history re-rendered from the session state
    assert [m.value for m in app.chat_message[1].markdown][0] == "A: 670 euro [#27]."

    app.sidebar.radio[0].set_value("subscription").run()            # other engine: new conversation
    assert len(app.chat_message) == 0
    assert app.sidebar.selectbox[0].value == "sonnet"


def test_api_errors(app, chats, monkeypatch):
    fake_api(monkeypatch, FakeStream("Half an answer", error=api.EngineError("The API rate limit is reached.")),
             tokens=api.EngineError("Could not reach the Anthropic API."))
    app.run()
    select(app, chats["Marco"])
    app.sidebar.radio[0].set_value("api").run()
    assert "Could not count the tokens exactly, showing an estimate." in app.sidebar.warning[0].value
    assert "estimated tokens" in sidebar_text(app)
    ask(app, "q")
    assert not app.exception
    assert "rate limit" in app.chat_message[1].error[0].value


def test_api_over_budget_suggests_a_model(app, chats, monkeypatch):
    fake_api(monkeypatch, tokens=500_000)
    app.run()
    select(app, chats["Marco"])
    app.sidebar.radio[0].set_value("api").run()
    app.sidebar.selectbox[0].set_value("claude-haiku-4-5").run()
    error = app.sidebar.error[0].value
    assert "over the 150,000 limit for claude-haiku-4-5. Choose claude-sonnet-5 or claude-opus-5-5, or select" in error
    assert app.chat_input[0].proto.disabled


def spy_csv(monkeypatch):
    """IDs of the messages in each CSV the app builds (the downloads' content is tested in test_export.py)."""
    seen, real = [], export.to_csv
    monkeypatch.setattr(export, "to_csv", lambda rows: seen.append([r["id"] for r in rows]) or real(rows))
    return seen


def test_download_cited_messages_and_conversation(app, chats, monkeypatch):
    seen = spy_csv(monkeypatch)
    fake(monkeypatch, "670 euro [#28][#27], see also [#99999].", "No idea.")
    app.run()
    select(app, chats["Marco"])
    assert not app.get("download_button")
    ask(app, "Quanto è l'affitto?")
    assert not app.exception
    assert "Download the 2 cited messages" in app.chat_message[1].caption[0].value
    assert seen[-1] == [27, 28]                        # from the database, chronological
    buttons = app.get("download_button")
    assert [b.proto.label for b in buttons] == ["CSV (Excel)", "TXT", "Markdown", "Download this conversation"]
    assert [b.proto.url.rsplit(".", 1)[1] for b in buttons] == ["csv", "txt", "md", "md"]
    assert all(b.proto.ignore_rerun for b in buttons)   # downloading does not rerun the app
    ask(app, "E il gas?")                              # no citations: no downloads under this answer
    assert len(app.get("download_button")) == 4


def test_word_search(app, chats, monkeypatch):
    seen = spy_csv(monkeypatch)
    app.run()
    assert not app.text_input                          # nothing selected, no search
    select(app, chats["Marco"], chats["Calcetto"])
    app.text_input(key="search").set_value(" AFFITTO ").run()
    search = next(e for e in app.expander if e.label.startswith("Find messages by word"))
    assert search.markdown[0].value.startswith("**5** messages contain “AFFITTO”")
    assert search.markdown[1].value == "**Marco**"
    assert len(search.caption) == 5
    assert len(seen[-1]) == 5
    assert len(app.get("download_button")) == 3

    app.text_input(key="search").set_value("a").run()  # in most messages: only the first 100 are shown
    search = next(e for e in app.expander if e.label.startswith("Find messages by word"))
    assert "Showing the first 100: download them all." in search.markdown[0].value
    assert len(search.caption) == 100 and len(seen[-1]) > 100
    assert [m.value for m in search.markdown[1:]] == ["**Calcetto**", "**Marco**"]

    app.text_input(key="search").set_value("zzzz").run()
    search = next(e for e in app.expander if e.label.startswith("Find messages by word"))
    assert search.markdown[0].value.startswith("**0** messages contain")
    assert not app.get("download_button")


def test_remove_chat(app, chats):
    Path("data/android_it.txt").write_text("the copy saved on upload", encoding="utf-8")
    app.run()
    select(app, chats["Marco"], chats["Calcetto"])
    assert app.sidebar.button(key="remove").proto.disabled
    app.sidebar.selectbox(key="doomed").set_value(chats["Marco"]).run()
    app.sidebar.button(key="remove").click().run()
    assert not app.exception
    assert "Removed “Marco”." in sidebar_text(app)
    assert not Path("data/android_it.txt").exists()
    assert app.sidebar.multiselect[0].options == ["Calcetto · 16 messages · 01/09/26–03/09/26"]
    assert app.sidebar.multiselect[0].value == [chats["Calcetto"]]   # the other chat stays selected
    assert app.sidebar.selectbox(key="doomed").value is None
    app.run()
    assert "Removed" not in sidebar_text(app)
