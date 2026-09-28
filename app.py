"""Streamlit UI: import WhatsApp exports, select chats and dates, ask Claude, open the cited messages.

Run from the project folder: `streamlit run app.py` (or double-click start.bat; Linux/macOS: ./start.sh).
"""

import os
import re
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from wa import search
from wa.citations import extract_citations
from wa.context import estimate_tokens, format_transcript, usage_level
from wa.engines import ENGINES
from wa.export import MIME, by_chat, conversation_to_md, file_stem, to_csv, to_md, to_txt
from wa.store import (connect, delete_chat, get_context, get_messages, get_messages_by_id, import_chat,
                      list_chats)

load_dotenv(Path(__file__).with_name(".env"))   # ANTHROPIC_API_KEY for the API engine; the subscription engine drops it
DATA_DIR = Path("data")
SEARCH_SHOWN = 100             # word search: messages shown on the page (the downloads have all of them)
READING = {"all": "All the selected messages", "search": "Only the messages about the question"}
MODEL_TIPS = {"sonnet": "good for most questions", "haiku": "fastest, for small chats and simple questions",
              "opus": "most capable, for hard questions, uses the most"}
GUIDE = """
**What you can do**
- **Ask** anything about the selected chats: facts, summaries, comparisons. Every answer cites the messages it is
  based on: open **Cited messages** under it to read them in context.
- **Find the messages about a topic**: ask, for example, "Find all the messages about the rent". Claude finds them
  even when they use other words. Under the answer, download the cited messages with date and time, full text:
  **CSV** (opens in Excel), **TXT** (like a WhatsApp export) or **Markdown**. In very long chats Claude may miss a
  few messages.
- **Find a word**: **Find messages by word** searches the selected chats for every message containing it. It is
  exact, instant and free (Claude is not used), and has the same downloads.
- **Save the conversation**: **Download this conversation** under the last answer saves the questions, the answers
  and the cited messages as a Markdown file.
- **Remove a chat** you no longer need: **Remove a chat** at the bottom of the sidebar.

**Very long chats**
- When the selection is too large for the model, **What Claude reads** switches to **Only the messages about the
  question**: Claude first chooses the words to search for, then reads only the messages that contain them, with
  the messages around them (up to about 100,000 tokens per question). Under the answer you see the words and how
  many messages Claude read. Follow-up questions search again and add what they find.
- It works well for questions about a topic, a person or an event ("When did we talk about the flat in Rome?").
  It cannot summarize a whole period: for that, narrow the dates until **All the selected messages** fits.
- You can choose it for smaller chats too: questions cost less, but Claude sees less.

**Engine**
- **Claude subscription**: your Claude Pro/Max plan, through Claude Code. No extra cost, but every question uses
  part of your plan's usage limits (the same as claude.ai, reset every 5 hours).
- **Claude API (paid)**: your Anthropic API key and credits. Every question costs money: the sidebar shows the
  estimated cost before you ask, and each answer shows what it really cost. Offered only when a key is in `.env`.

**Model**
- **Sonnet** (default): good answers for almost every question.
- **Haiku**: the fastest and cheapest. Fine for small selections and simple questions ("When is…", "Who said…").
  It cannot read very large selections.
- **Opus**: the most capable, for hard questions (summaries of long periods, comparisons, subtle details).
  On the API it costs twice as much as Sonnet; on the subscription it uses your limits faster.

**Save limits and money**
- The first question of a conversation sends **all** the selected messages. Select only the chats you need and
  narrow the dates.
- Follow-up questions in the same conversation weigh much less (on the API, about a tenth of the first question's
  input cost if you ask within 5 minutes).
- Changing chats, dates, engine, model or **What Claude reads**, or clicking **New conversation**, starts over and
  sends everything again.
"""

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
    text = escape(m["text"]).replace("\n", "  \n") or "_(no text in the export)_"   # WhatsApp writes some messages empty
    line = f"`#{m['id']}` {when} · {who}  \n{text}"
    (st.info if cited else st.caption)(line)


def money(usd: float) -> str:
    """Dollars for st.markdown: a bare $ starts a LaTeX formula there."""
    return f"\\${usd:.2f}" if usd >= 0.01 else "less than \\$0.01"


def model_label(model: str) -> str:
    return f"{model} · {next(tip for family, tip in MODEL_TIPS.items() if family in model)}"


@st.cache_data(show_spinner="Counting tokens...")   # Streamlit reruns the script on every click
def count_tokens(engine_key: str, transcript: str, model: str) -> int:
    return ENGINES[engine_key].count_tokens(transcript, model)


def download_buttons(rows, stem: str, title: str, key: str):
    """The messages as CSV (Excel), TXT (like a WhatsApp export) and Markdown, full text from the database."""
    files = {"csv": ("CSV (Excel)", to_csv), "txt": ("TXT", to_txt), "md": ("Markdown", lambda r: to_md(r, title))}
    with st.container(horizontal=True):
        for fmt, (label, convert) in files.items():
            st.download_button(label, convert(rows), f"{stem}.{fmt}", MIME[fmt], key=f"{key}-{fmt}",
                               icon=":material/download:", on_click="ignore")


def show_answer(entry, index: int, text_shown=False):
    """index: the entry's position in state.history (the question is just before it)."""
    if "error" in entry:
        st.error(entry["error"])
        return
    if not text_shown:
        st.markdown(entry["text"])
    if "search" in entry:
        s = entry["search"]
        st.caption(f"Searched for: {escape(', '.join(s['words']))}. {s['found']:,} messages contain these words; "
                   f"Claude received {s['sent']:,} messages with this question (matches and the messages around them): "
                   f"it did not see the rest of the chat."
                   + (f" {s['left_out']:,} less relevant matches did not fit: narrow the dates to include them."
                      if s["left_out"] else ""))
    if entry.get("cost_usd") is not None:
        cached = entry["usage"]["cache_read_input_tokens"]
        st.caption(f"Cost of this question: \\${entry['cost_usd']:.4f}"
                   + (f" ({cached:,} tokens read from the cache)" if cached else ""))
    if entry["cited"]:
        st.caption(f"Download the {len(entry['cited'])} cited messages, with date, time and full text:")
        question = state.history[index - 1]["text"]
        download_buttons(get_messages_by_id(db, entry["cited"]), f"cited-messages-{file_stem(question)}",
                         f"Messages cited for: {question}", key=f"cited-{index}")
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
    state.sent = {"ids": set(), "tokens": 0, "transcript": None}   # search mode: what Claude already has


def prepare_search(question: str):
    """Search mode: Claude chooses the words, the app finds the messages (uses the sidebar's engine, model and
    selection). Returns (transcript, prompt, found, cost in USD of choosing the words)."""
    earlier = [e["text"] for e in state.history[:-1] if e["role"] == "user"]
    with st.spinner("Claude is choosing the words to search for..."):   # not Haiku: it thinks for 30+ s here
        reply = engine.ask(search.about(messages), search.words_request(question, earlier), model=model)
    words = search.parse_words(reply["text"])
    if not words:
        raise engine.EngineError("Claude gave no words to search for. Try asking the question in another way.")
    room = min(search.BUDGET, budget - state.sent["tokens"])
    found = search.find_excerpts(messages, words, room, state.sent["ids"]) | {"words": words}
    words_cost = reply.get("cost_usd") or 0
    if state.session:
        return state.sent["transcript"], search.follow_up_prompt(question, words, found), found, words_cost
    if not found["messages"]:
        raise engine.EngineError(f"No message contains the words Claude searched for ({', '.join(words)}). "
                                 "Ask the question in another way, or use Find messages by word.")
    return format_transcript(found["messages"]), search.first_prompt(question, words, found), found, words_cost


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

engine_keys = ["subscription"] + (["api"] if os.environ.get("ANTHROPIC_API_KEY") else [])
engine_key = st.sidebar.radio("Engine", engine_keys, format_func=lambda k: ENGINES[k].NAME, key="engine",
                              help="Subscription: your Pro/Max plan, no extra cost, uses the plan's usage limits. "
                                   "API: your API key, every question costs money. See “How to use it” on the right.")
if len(engine_keys) == 1:
    st.sidebar.caption("To use the paid Claude API as well, put your API key in `.env` (see the README) "
                       "and restart the app.")
engine = ENGINES[engine_key]
model = st.sidebar.selectbox("Model", engine.MODELS, format_func=model_label,
                             help="Sonnet: good answers (default). Haiku: fastest and cheapest, for small chats and "
                                  "simple questions. Opus: most capable, for hard questions, but costs or uses the "
                                  "most.")

messages = get_messages(db, selected, date_from, date_to)
transcript = format_transcript(messages)
tokens, exact = estimate_tokens(transcript), False
budget = engine.TOKEN_BUDGET[model]
if messages and hasattr(engine, "count_tokens") and tokens <= 2 * budget:   # far over the budget: no need to count
    try:
        tokens, exact = count_tokens(engine_key, transcript, model), True
    except engine.EngineError as e:
        st.sidebar.warning(f"Could not count the tokens exactly, showing an estimate. {e}")
reading = "all"
if messages:   # the index follows the budget, so the choice resets to what fits (no key on purpose)
    reading = st.sidebar.radio("What Claude reads", list(READING), format_func=READING.get,
                               index=int(tokens > budget),
                               help="All the selected messages: the most complete answers, if the selection fits "
                                    "the model's limit. Only the messages about the question: for chats too large "
                                    "to read whole. Claude chooses words to search for and reads only the messages "
                                    "that contain them, with the messages around them. See “How to use it”.")
searching = reading == "search"
blocked = not messages or (tokens > budget and not searching)
if selected:
    size = f"**{tokens:,}** tokens" if exact else f"~**{tokens:,}** estimated tokens"
    weight = min(tokens, search.BUDGET) if searching else tokens
    if hasattr(engine, "estimate_cost"):
        cost = engine.estimate_cost(weight, model)
        st.sidebar.markdown(f"**{len(messages):,}** messages selected  \n{size}  \n"
                            + (f"Cost: up to about **{money(cost['first'])}** per question" if searching else
                               f"Cost: about **{money(cost['first'])}** for the first question, "
                               f"**{money(cost['follow_up'])}** for each follow-up"),
                            help="Estimate with an answer of about 1,000 tokens: long answers, such as summaries, cost "
                                 "a little more. Follow-ups are cheaper only within 5 minutes of the previous "
                                 "question (the messages stay in Anthropic's cache for 5 minutes).")
    else:
        st.sidebar.markdown(f"**{len(messages):,}** messages selected  \n{size}  \n"
                            + (f"Usage: up to **{usage_level(weight)}** per question" if searching else
                               f"Usage: **{usage_level(weight)}**"),
                            help="How much each question weighs on your plan's usage limits "
                                 "(low under 30,000 tokens, medium up to 100,000, high above).")
    if not messages:
        st.sidebar.warning("No messages in this date range.")
    elif tokens > budget and not searching:
        fits = [m for m in engine.MODELS if engine.TOKEN_BUDGET[m] >= tokens]
        st.sidebar.error(f"This selection is about {tokens:,} tokens, over the {budget:,} limit for {model}. "
                         + (f"Choose {' or '.join(fits)}, or select" if fits else "Select")
                         + " fewer chats or a shorter date range, or let Claude read only the messages about "
                           "the question.")
    elif searching:
        st.sidebar.caption(f"Claude chooses words to search for, then reads only the messages that contain them "
                           f"and the messages around them: up to about {search.BUDGET:,} tokens per question.")

if chats:
    with st.sidebar.expander("Remove a chat"):
        doomed = st.selectbox("Chat to remove", list(chats), format_func=lambda i: chats[i]["name"], index=None,
                              placeholder="Choose a chat", key="doomed")
        st.caption("Deletes its messages from the app and the copy of the export saved in `data/`. "
                   "Nothing changes on your phone. You can import it again later.")
        if st.button("Remove", disabled=doomed is None, key="remove"):
            source = delete_chat(db, doomed)
            if source:
                (DATA_DIR / source).unlink(missing_ok=True)
            state.removed = chats[doomed]["name"]
            del state.doomed
            st.rerun()
if "removed" in state:
    st.sidebar.success(f"Removed “{state.pop('removed')}”.")

# --- Main area: conversation -----------------------------------------------------------------

selection = (engine.NAME, model, tuple(sorted(selected)), date_from, date_to, reading)
if state.get("selection") != selection:   # other chats, dates, model or reading: start over
    state.selection = selection
    new_conversation()

top_left, top_right = st.columns([4, 1])
top_left.subheader("Ask about your chats")
if top_right.button("New conversation", disabled=not state.history, key="new"):
    new_conversation()

if not chats:
    st.info("Import a WhatsApp export in the sidebar to start. On the phone: open the chat › ⋮ or the "
            "chat name › More › Export chat › Without media, then save the file and upload it here.")
elif not selected:
    st.info("Choose one or more chats in the sidebar.")
with st.expander("How to use it: what you can do, engine and model", expanded=not state.history):
    st.markdown(GUIDE)
if messages and searching:   # always visible: answers here rest on part of the chat
    st.warning(
        ("**Claude does not read the whole selection**: it is about "
         f"{tokens:,} tokens, over the {budget:,} limit for {model}." if tokens > budget else
         "**Claude does not read the whole selection**: you chose to let it read only the messages about "
         "each question.")
        + f" For each question it reads only the messages that contain the words it searches for, with the "
          f"messages around them (up to about {search.BUDGET:,} tokens). So:\n"
          "- It can **miss messages** that talk about the topic in other words. For an exact word, use "
          "**Find messages by word** below: it is complete.\n"
          "- It **cannot summarize a period or count** over the whole chat (\"what happened in 2025\", \"how many "
          "times…\", \"how did things change\"). For that, narrow the dates until **All the selected messages** "
          "fits, and ask period by period.\n"
          "- If it finds nothing, the messages may still exist: it only means none of the words matched.\n\n"
          "Best for questions about a topic, a person or an event.",
        icon=":material/manage_search:")

if messages:
    with st.expander("Find messages by word (exact and free: Claude is not used)"):
        term = st.text_input("Word or part of a word", key="search", placeholder="e.g. affitto").strip()
        if term:
            found = by_chat(m for m in messages if term.casefold() in m["text"].casefold())
            st.markdown(f"**{len(found):,}** messages contain “{escape(term)}” in the selected chats and dates."
                        + (f" Showing the first {SEARCH_SHOWN}: download them all." if len(found) > SEARCH_SHOWN
                           else ""))
            if found:
                download_buttons(found, f"messages-{file_stem(term)}", f"Messages containing “{term}”", key="search")
            chat = None
            for m in found[:SEARCH_SHOWN]:
                if m["chat_name"] != chat:
                    chat = m["chat_name"]
                    st.markdown(f"**{escape(chat)}**")
                show_message(m, cited=False)

for index, entry in enumerate(state.history):
    with st.chat_message(entry["role"]):
        if entry["role"] == "user":
            st.markdown(entry["text"])
        else:
            show_answer(entry, index)

question = st.chat_input("Ask about a topic, a person or an event in the selected chats" if searching else
                         "Ask a question about the selected chats", disabled=blocked)
if question:
    state.history.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        streamed = hasattr(engine, "ask_stream")
        try:
            sent, prompt, found, extra_cost = transcript, question, None, 0
            if searching:
                sent, prompt, found, extra_cost = prepare_search(question)
            with st.spinner("Claude is reading the chats..."):
                if streamed:
                    stream = engine.ask_stream(sent, prompt, session=state.session, model=model)
                    st.write_stream(stream)
                    result = stream.result
                else:
                    result = engine.ask(sent, prompt, session=state.session, model=model)
        except engine.EngineError as e:
            entry = {"role": "assistant", "error": str(e)}
        else:
            state.session = result["session"]
            valid = [m["id"] for m in messages]
            if found:
                state.sent["ids"].update(m["id"] for m in found["messages"])
                state.sent["tokens"] += found["tokens"]
                state.sent["transcript"] = sent
                valid = state.sent["ids"]
            cost = result.get("cost_usd")
            entry = {"role": "assistant", "text": result["text"],
                     "cost_usd": None if cost is None else cost + extra_cost,
                     "usage": result["usage"], "cited": extract_citations(result["text"], valid)}
            if found:
                entry["search"] = {"words": found["words"], "found": found["found"],
                                   "sent": len(found["messages"]), "left_out": found["left_out"]}
        state.history.append(entry)
        show_answer(entry, len(state.history) - 1, text_shown=streamed and "error" not in entry)

if state.history:   # after the new answer, so the file includes it
    names = ", ".join(chats[i]["name"] for i in selected)
    header = (f"Chats: {names} · {date_from:%d/%m/%Y}–{date_to:%d/%m/%Y} · {engine.NAME}, {model} · "
              f"saved on {datetime.now():%d/%m/%Y %H:%M}")
    st.download_button("Download this conversation", conversation_to_md(state.history, header,
                                                                        lambda ids: get_messages_by_id(db, ids)),
                       f"whatsapp-ask-{datetime.now():%Y-%m-%d-%H%M}.md", MIME["md"], key="conversation",
                       icon=":material/download:", on_click="ignore",
                       help="Questions, answers and cited messages, as a Markdown file.")
