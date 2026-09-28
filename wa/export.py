"""Save messages and conversations as files: CSV, plain text (like a WhatsApp export) and Markdown."""

import csv
import io
import re
from datetime import datetime

MIME = {"csv": "text/csv", "txt": "text/plain", "md": "text/markdown"}


def by_chat(messages):
    """By chat, then by time: the text and Markdown files put a heading above each chat."""
    return sorted(messages, key=lambda m: (m["chat_name"], m["ts"], m["id"]))


def _sender(m) -> str:
    return "(system)" if m["is_system"] else m["sender"]


def _md(text: str) -> str:
    """Chat text shown literally in Markdown (e.g. "<Media omessi>" is not an HTML tag)."""
    return re.sub(r"([\\`*_\[\]<>#|~])", r"\\\1", text)


def to_csv(messages) -> str:
    """Semicolon-separated, with a BOM: Excel with Italian (and most European) settings opens it in columns.

    A cell starting with = + - @ gets a leading ', otherwise Excel reads it as a formula
    ("+39 333…" becomes an error, "=HYPERLINK(…)" from a chat becomes a link)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["chat", "date", "time", "sender", "text", "id"])
    for m in by_chat(messages):
        when = datetime.fromisoformat(m["ts"])
        text = "'" + m["text"] if m["text"][:1] in ("=", "+", "-", "@") else m["text"]
        writer.writerow([m["chat_name"], f"{when:%d/%m/%Y}", f"{when:%H:%M}", _sender(m), text, m["id"]])
    return "\ufeff" + out.getvalue()


def to_txt(messages) -> str:
    """Like a WhatsApp export ("dd/mm/yy, hh:mm - Sender: text"), with the chat name above each chat."""
    lines, chat = [], None
    for m in by_chat(messages):
        if m["chat_name"] != chat:
            chat = m["chat_name"]
            lines += [""] * bool(lines) + [f"=== {chat} ==="]
        who = "" if m["is_system"] else f"{m['sender']}: "
        lines.append(f"{datetime.fromisoformat(m['ts']):%d/%m/%y, %H:%M} - {who}{m['text']}")
    return "\n".join(lines) + "\n"


def md_list(messages, heading="##") -> list[str]:
    """One Markdown list item per message, under a heading per chat."""
    lines, chat = [], None
    for m in by_chat(messages):
        if m["chat_name"] != chat:
            chat = m["chat_name"]
            lines += [""] * bool(lines) + [f"{heading} {_md(chat)}", ""]
        text = _md(m["text"]).replace("\n", "  \n  ") or "_(no text in the export)_"
        lines.append(f"- `#{m['id']}` **{datetime.fromisoformat(m['ts']):%d/%m/%Y %H:%M}** · "
                     f"{_md(_sender(m))}: {text}")
    return lines


def to_md(messages, title: str) -> str:
    return "\n".join([f"# {_md(title)}", "", *md_list(messages)]) + "\n"


def conversation_to_md(history, header: str, cited_messages) -> str:
    """history: the app's entries; cited_messages(ids) returns the rows for the cited IDs."""
    lines = ["# WhatsApp Ask conversation", "", header]
    for entry in history:
        lines += ["", "---", ""]
        if entry["role"] == "user":
            lines += ["### Question", "", entry["text"]]
        elif "error" in entry:
            lines += ["### Answer", "", f"_Error: {entry['error']}_"]
        else:
            lines += ["### Answer", "", entry["text"]]
            if "search" in entry:
                lines += ["", f"_Searched for: {_md(', '.join(entry['search']['words']))}. Claude read only the "
                          f"messages containing these words and the messages around them._"]
            if entry["cited"]:
                lines += ["", "**Cited messages**", "", *md_list(cited_messages(entry["cited"]), "####")]
    return "\n".join(lines) + "\n"


def file_stem(text: str) -> str:
    """A safe file name part: letters, digits and dashes only."""
    return re.sub(r"\W+", "-", text).strip("-")[:40].lower() or "messages"
