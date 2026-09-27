"""Streamlit UI: import WhatsApp exports, select chats and dates, ask Claude, open the cited messages.

Run from the project folder: `streamlit run app.py` (or double-click start.bat).
"""

import re
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from wa.citations import extract_citations
from wa.context import build_transcript, estimate_tokens, usage_level
from wa.engines import ENGINES
from wa.store import connect, get_context, get_messages, import_chat, list_chats

DATA_DIR = Path("data")
TRUNCATED_AT = 39_000          # an export holds at most about 40,000 messages
engine = ENGINES["subscription"]

st.set_page_config(page_title="WhatsApp Ask", page_icon="💬", layout="wide")
db = connect(DATA_DIR / "wa.db")   # a new connection per run: sqlite3 must not be shared across threads
state = st.session_state
state.setdefault("imported", {})   # upload file_id -> (ok, message): each upload is imported once
state.setdefault("history", [])
state.setdefault("session", None)


def escape(text: str) -> str:
    """Show chat text literally, not as Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:])", r"\\\1", text)


def day(ts: str) -> date:
    return datetime.fromisoformat(ts).date()


def show_message(m, cited: bool):
    when = datetime.fromisoformat(m["ts"]).strftime("%d/%m/%Y %H:%M")
    who = "(system)" if m["is_system"] else f"**{escape(m['sender'])}**"
    line = f"`#{m['id']}` {when} · {who}  \n{escape(m['text']).replace(chr(10), '  ' + chr(10))}"
    (st.info if cited else st.caption)(line)


def show_answer(entry):
    if "error" in entry:
        st.error(entry["error"])
        return
    st.markdown(entry["text"])
    if entry["cited"]:
        with st.expander(f"Cited messages ({len(entry['cited'])})"):
            for i, message_id in enumerate(entry["cited"]):
                context = get_context(db, message_id)
                if i:
                    st.divider()
                st.markdown(f"**{escape(context[0]['chat_name'])}**")
                for m in context:
                    show_message(m, m["id"] == message_id)


def new_conversation():
    state.history = []
    state.session = None


# --- Sidebar: import -------------------------------------------------------------------------

st.sidebar.title("💬 WhatsApp Ask")
uploads = st.sidebar.file_uploader("Import WhatsApp exports (.txt or .zip)", type=["txt", "zip"],
                                   accept_multiple_files=True)
for f in uploads or []:
    if f.file_id not in state.imported:
        path = DATA_DIR / Path(f.name).name
        path.write_bytes(f.getvalue())
        try:
            chat_id = import_chat(db, path)
        except ValueError as e:
            state.imported[f.file_id] = (False, str(e))
        else:
            name, count = db.execute("SELECT name, message_count FROM chats WHERE id = ?",
                                     (chat_id,)).fetchone()
            state.imported[f.file_id] = (True, f"Imported “{name}”: {count:,} messages.")
    ok, message = state.imported[f.file_id]
    (st.sidebar.success if ok else st.sidebar.error)(message)

# --- Sidebar: selection ----------------------------------------------------------------------

chats = {c["id"]: c for c in list_chats(db)}
for c in chats.values():
    if c["message_count"] >= TRUNCATED_AT:
        st.sidebar.warning(f"“{c['name']}” has {c['message_count']:,} messages, so the export may be "
                           f"truncated: it starts on {day(c['first_ts']):%d/%m/%Y}. Older messages are missing.")


def chat_label(chat_id):
    c = chats[chat_id]
    return (f"{c['name']} · {c['message_count']:,} messages · "
            f"{day(c['first_ts']):%d/%m/%y}–{day(c['last_ts']):%d/%m/%y}")


selected = st.sidebar.multiselect("Chats", list(chats), format_func=chat_label,
                                  placeholder="Choose one or more chats", key="chats")
date_from = date_to = None
if selected:
    first = min(day(chats[i]["first_ts"]) for i in selected)
    last = max(day(chats[i]["last_ts"]) for i in selected)
    left, right = st.sidebar.columns(2)
    date_from = left.date_input("From", first, min_value=first, max_value=last, format="DD/MM/YYYY")
    date_to = right.date_input("To", last, min_value=first, max_value=last, format="DD/MM/YYYY")

model = st.sidebar.selectbox("Model", engine.MODELS,
                             help="sonnet: best answers. haiku: faster, fine for small chats and simple questions.")

messages = get_messages(db, selected, date_from, date_to)
transcript = build_transcript(db, selected, date_from, date_to)
tokens = estimate_tokens(transcript)
budget = engine.TOKEN_BUDGET[model]
blocked = not messages or tokens > budget
if selected:
    st.sidebar.markdown(f"**{len(messages):,}** messages selected  \n"
                        f"~**{tokens:,}** estimated tokens  \n"
                        f"Usage: **{usage_level(tokens)}**",
                        help="How much each question weighs on your plan's usage limits "
                             "(low under 30,000 tokens, medium up to 100,000, high above).")
    if not messages:
        st.sidebar.warning("No messages in this date range.")
    elif tokens > budget:
        st.sidebar.error(f"This selection is about {tokens:,} tokens, over the {budget:,} limit for {model}. "
                         "Select fewer chats or a shorter date range.")
st.sidebar.caption(f"Engine: {engine.NAME}")

# --- Main area: conversation -----------------------------------------------------------------

selection = (engine.NAME, model, tuple(sorted(selected)), date_from, date_to)
if state.get("selection") != selection:   # other chats, dates or model: start over
    state.selection = selection
    new_conversation()

top_left, top_right = st.columns([4, 1])
top_left.subheader("Ask about your chats")
if top_right.button("New conversation", disabled=not state.history):
    new_conversation()

if not chats:
    st.info("Import a WhatsApp export in the sidebar to start. On the phone: open the chat › ⋮ or the "
            "chat name › More › Export chat › Without media, then save the file and upload it here.")
elif not selected:
    st.info("Choose one or more chats in the sidebar.")

for entry in state.history:
    with st.chat_message(entry["role"]):
        if entry["role"] == "user":
            st.markdown(entry["text"])
        else:
            show_answer(entry)

question = st.chat_input("Ask a question about the selected chats", disabled=blocked)
if question:
    state.history.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Claude is reading the chats..."):
            try:
                result = engine.ask(transcript, question, session=state.session, model=model)
            except engine.EngineError as e:
                entry = {"role": "assistant", "error": str(e)}
            else:
                state.session = result["session"]
                entry = {"role": "assistant", "text": result["text"],
                         "cited": extract_citations(result["text"], [m["id"] for m in messages])}
        state.history.append(entry)
        show_answer(entry)
