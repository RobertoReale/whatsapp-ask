from wa import search
from wa.context import estimate_tokens, format_message


def msgs(*rows):
    """rows: (chat_id, text); IDs from 1, one minute apart, chronological."""
    return [{"id": i, "chat_id": chat, "chat_name": f"Chat {chat}", "ts": f"2026-09-01T10:{i:02d}:00",
             "sender": "Anna" if i % 2 else "Luca", "text": text, "is_system": 0, "has_media": 0}
            for i, (chat, text) in enumerate(rows, start=1)]


def test_parse_words():
    reply = ('Here are the search words:\n- Affitt\n* canone\n1. "padrone di casa"\n2) «Bianchi»\n• affitt\n'
             'ok\n\n' + "\n".join(f"parola{i}" for i in range(50)))
    words = search.parse_words(reply)
    assert words[:4] == ["affitt", "canone", "padrone di casa", "bianchi"]   # no heading, no duplicate, no "ok"
    assert len(words) == search.MAX_WORDS


def test_words_request_and_about():
    text = search.words_request("E quando?", ["Quanto è l'affitto?"])
    assert text.startswith("Do not answer the question below yet")
    assert text.endswith("\n\nEarlier question in this conversation: Quanto è l'affitto?\nQuestion: E quando?")
    alone = search.words_request("E quando?")
    assert "Earlier question" not in alone and alone.endswith("unrelated words.\n\nQuestion: E quando?")
    about = search.about(msgs((1, "a"), (2, "b"), (1, "c")))
    assert about == "Chats: Chat 1, Chat 2. People who write in them: Anna, Luca."


def test_find_excerpts_neighbours_in_the_same_chat():
    rows = msgs(*[(1, f"chat {i}") for i in range(10)], (2, "altra chat"), (1, "l'AFFITTO è alto"),
                (2, "altra chat"), *[(1, f"dopo {i}") for i in range(5)])
    found = search.find_excerpts(rows, ["affitt"], 100_000)
    assert found["found"] == 1 and found["left_out"] == 0
    ids = [m["id"] for m in found["messages"]]
    assert ids == [8, 9, 10, 12, 14, 15, 16]          # 3 before and 3 after in chat 1, not chat 2's 11 and 13
    assert found["tokens"] == sum(estimate_tokens(format_message(m) + "\n") for m in found["messages"])


def test_find_excerpts_ranks_rare_and_many_words_within_the_budget():
    filler = [(1, "niente") for _ in range(8)]
    rows = msgs((1, "casa"), *filler, (1, "casa casa"), *filler, (1, "casa e affitto"), *filler, (1, "casa"))
    window = sum(estimate_tokens(format_message(m) + "\n") for m in rows[15:22])   # message 19 and neighbours
    found = search.find_excerpts(rows, ["casa", "affitt"], window)
    assert found["found"] == 4 and found["left_out"] == 3
    assert [m["id"] for m in found["messages"]] == list(range(16, 23))   # "casa e affitto": both, one rare
    assert search.find_excerpts(rows, ["zzz"], 100_000) == {"messages": [], "found": 0, "left_out": 0, "tokens": 0}


def test_find_excerpts_skips_what_was_sent():
    rows = msgs((1, "affitto"), (1, "a"), (1, "b"), (1, "c"), (1, "d"), (1, "e"), (1, "affitto"))
    found = search.find_excerpts(rows, ["affitt"], 100_000, sent={1, 2, 3, 4})
    assert [m["id"] for m in found["messages"]] == [5, 6, 7]
    assert found["found"] == 2 and found["left_out"] == 0


def test_prompts():
    rows = msgs((1, "affitto"))
    found = {"messages": rows, "found": 3, "left_out": 2, "tokens": 10}
    first = search.first_prompt("Quanto?", ["affitt", "canone"], found)
    assert first.startswith("Note: the chats are too long to send whole. The documents hold only the messages "
                            "that contain the search words (affitt, canone), each with up to 3 messages")
    assert first.endswith("2 more messages contain the words but did not fit.\n\nQuanto?")
    follow = search.follow_up_prompt("E poi?", ["affitt"], found)
    assert follow.startswith("More messages from the same chats") and "[#1] 01/09/26 10:01 Anna: affitto" in follow
    assert follow.endswith("E poi?")
    none = search.follow_up_prompt("E poi?", ["affitt"], {**found, "messages": [], "left_out": 0})
    assert none == "The search for this question (affitt) found no messages beyond those you already have.\n\nE poi?"
