"""Transcript formatting, token estimate, usage level."""

from wa.store import get_messages


def format_message(m) -> str:
    """[#1234] 26/09/26 14:32 Marco: text  |  [#1235] 26/09/26 14:33 (system) text"""
    ts = m["ts"]   # ISO 8601; slicing is 6x faster than strftime, which counts on 100,000+ messages
    when = f"{ts[8:10]}/{ts[5:7]}/{ts[2:4]} {ts[11:16]}"
    who = "(system)" if m["is_system"] else f"{m['sender']}:"
    return f"[#{m['id']}] {when} {who} {m['text']}"


def build_transcript(db, chat_ids, date_from=None, date_to=None) -> str:
    return format_transcript(get_messages(db, chat_ids, date_from, date_to))


def format_transcript(messages) -> str:
    """One <document> per chat, as Anthropic recommends for multiple documents. messages: chronological."""
    by_chat = {}
    for m in messages:
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
    """Conservative local estimate: without an API key there is no token-counting endpoint.

    1.5 characters per token, calibrated on real `usage` (see docs/DECISIONS.md): the
    `[#ID] dd/mm/yy hh:mm` headers make transcripts denser than ordinary text."""
    return len(text) * 2 // 3


def usage_level(tokens: int) -> str:
    """How much a question weighs on the plan's usage limits."""
    if tokens < 30_000:
        return "low"
    if tokens <= 100_000:
        return "medium"
    return "high"
