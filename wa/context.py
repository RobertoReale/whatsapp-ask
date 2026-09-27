"""Transcript formatting, token estimate, usage level."""

from datetime import datetime

from wa.store import get_messages


def format_message(m) -> str:
    """[#1234] 26/09/26 14:32 Marco: text  |  [#1235] 26/09/26 14:33 (system) text"""
    when = datetime.fromisoformat(m["ts"]).strftime("%d/%m/%y %H:%M")
    who = "(system)" if m["is_system"] else f"{m['sender']}:"
    return f"[#{m['id']}] {when} {who} {m['text']}"


def build_transcript(db, chat_ids, date_from=None, date_to=None) -> str:
    """One <document> per chat with messages in the range, as Anthropic recommends for multiple documents."""
    by_chat = {}
    for m in get_messages(db, chat_ids, date_from, date_to):
        by_chat.setdefault(m["chat_id"], []).append(m)
    if not by_chat:
        return ""
    parts = ["<documents>"]
    for index, msgs in enumerate(by_chat.values(), start=1):
        parts += [
            f'  <document index="{index}">',
            f"    <source>{msgs[0]['chat_name']}</source>",
            "    <document_content>",
            *(format_message(m) for m in msgs),
            "    </document_content>",
            "  </document>",
        ]
    parts.append("</documents>")
    return "\n".join(parts)


def estimate_tokens(text: str) -> int:
    """Conservative local estimate: without an API key there is no token-counting endpoint."""
    return len(text) // 3


def usage_level(tokens: int) -> str:
    """How much a question weighs on the plan's usage limits."""
    if tokens < 30_000:
        return "low"
    if tokens <= 100_000:
        return "medium"
    return "high"
