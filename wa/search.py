"""Search mode, for selections too large to send whole: Claude picks the words to search for, the app finds
the messages that contain them, and only those, with the messages around them, go to Claude.

Plain case-insensitive substring search in Python, like "Find messages by word" (see docs/DECISIONS.md).
"""

import math
import re
from collections import Counter

from wa.context import estimate_tokens, format_message, format_transcript

BUDGET = 100_000      # estimated tokens of messages sent with each question
NEIGHBOURS = 3        # messages sent before and after each match, from the same chat
MAX_WORDS = 40

WORDS_REQUEST = """\
Do not answer the question below yet. The chats are too long to read whole: first I will search them, and \
only the messages that contain the search words will be sent to you. Write the words to search for.

Rules:
- One word or short phrase per line, and nothing else: no numbering, no headings, no explanations.
- Words that messages about this topic would contain, in the language of the chats (if unsure, the language \
of the question): the specific words, synonyms, names, nicknames, abbreviations, slang, typical phrases \
("andare a vivere") and common misspellings. Up to 20 lines.
- Only words specific to the topic. Leave out everyday words (we, talk, think, idea, life, future, do, go) and \
the question's own filler words: each of them would match thousands of unrelated messages.
- A word matches every message that contains it, even inside a longer word, ignoring case. So drop only the \
ending, to match every form: "affitt" (affitto, affitti, affittare), "conviv" (convivere, convivenza). Never \
cut more: "anda" or "lett" would match unrelated words.
{earlier}
Question: {question}"""

NOTE = ("Note: the chats are too long to send whole. The documents hold only the messages that contain the "
        "search words ({words}), each with up to {n} messages before and after it in the same chat. The other "
        "messages are missing: if the answer is not here, say that you found nothing about it in these "
        "messages, not that it never happened.")


def about(messages) -> str:
    """Stands in for the transcript when Claude picks the words: chat names and who writes in them."""
    chats = dict.fromkeys(m["chat_name"] for m in messages)
    senders = Counter(m["sender"] for m in messages if m["sender"])
    return (f"Chats: {', '.join(chats)}. People who write in them: "
            f"{', '.join(name for name, _ in senders.most_common(20))}.")


def words_request(question: str, earlier=()) -> str:
    earlier = "".join(f"\nEarlier question in this conversation: {q}" for q in earlier)
    return WORDS_REQUEST.format(earlier=earlier, question=question)


def parse_words(text: str) -> list[str]:
    """The search words in Claude's reply, lower case, without list markers or quotes."""
    words = []
    for line in text.splitlines():
        word = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("\"'`«»“”").strip().casefold()
        if 3 <= len(word) <= 40 and not word.endswith(":") and word not in words:
            words.append(word)
    return words[:MAX_WORDS]


def find_excerpts(messages, words, budget: int, sent=frozenset()) -> dict:
    """The matches for `words` in `messages` (chronological), each with its neighbours, within `budget` tokens.

    The matches with the most and rarest words come first. Messages whose ID is in `sent` are already in the
    conversation and are not sent again. Returns {"messages": chronological rows, "found": matching messages,
    "left_out": matches that did not fit, "tokens": estimated tokens}."""
    matches = {}
    for i, m in enumerate(messages):
        text = m["text"].casefold()
        hits = [w for w in words if w in text]
        if hits:
            matches[i] = hits
    counts = Counter(w for hits in matches.values() for w in hits)
    weight = {w: 1 + math.log(len(messages) / n) for w, n in counts.items()}   # rarer words weigh more
    ranked = sorted(matches, key=lambda i: -sum(weight[w] for w in matches[i]))   # ties stay chronological

    positions, chat_rows = {}, {}
    for i, m in enumerate(messages):
        rows = chat_rows.setdefault(m["chat_id"], [])
        positions[i] = (rows, len(rows))
        rows.append(i)

    chosen, tokens = set(), 0
    for i in ranked:
        if messages[i]["id"] in sent:
            continue
        rows, k = positions[i]
        new = [j for j in rows[max(0, k - NEIGHBOURS):k + NEIGHBOURS + 1]
               if j not in chosen and messages[j]["id"] not in sent]
        cost = sum(estimate_tokens(format_message(messages[j]) + "\n") for j in new)
        if tokens + cost > budget:
            break
        chosen.update(new)
        tokens += cost
    left_out = sum(1 for i in matches if i not in chosen and messages[i]["id"] not in sent)
    return {"messages": [messages[j] for j in sorted(chosen)], "found": len(matches), "left_out": left_out,
            "tokens": tokens}


def note(words, left_out: int) -> str:
    text = NOTE.format(words=", ".join(words), n=NEIGHBOURS)
    if left_out:
        text += f" {left_out:,} more messages contain the words but did not fit."
    return text


def first_prompt(question: str, words, found: dict) -> str:
    """The question for the first answer: the excerpts themselves are the transcript."""
    return f"{note(words, found['left_out'])}\n\n{question}"


def follow_up_prompt(question: str, words, found: dict) -> str:
    """A follow-up: the messages found for it that Claude does not have yet go with the question."""
    if not found["messages"]:
        return (f"The search for this question ({', '.join(words)}) found no messages beyond those you already "
                f"have.\n\n{question}")
    return (f"More messages from the same chats, found for this question, in the same format:\n\n"
            f"{format_transcript(found['messages'])}\n\n{note(words, found['left_out'])}\n\n{question}")
