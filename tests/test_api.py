"""API engine with a fake client (never calls Anthropic), plus @pytest.mark.api tests that do (paid)."""

import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from dotenv import load_dotenv

from wa.citations import extract_citations
from wa.context import build_transcript
from wa.engines import api
from wa.engines.api import EngineError, ask, ask_stream, build_system, cost_usd, count_tokens, estimate_cost
from wa.store import connect, get_messages, import_chat

FIXTURES = Path(__file__).parent / "fixtures"
TRANSCRIPT = "<documents>TRANSCRIPT</documents>"


def usage(input_tokens=10, output_tokens=20, cache_creation_input_tokens=5_000, cache_read_input_tokens=None):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=cache_creation_input_tokens,
                           cache_read_input_tokens=cache_read_input_tokens)


def final(text="Il 4 settembre [#12]", **kw):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig"), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, usage=usage(**kw))


class FakeStream:
    def __init__(self, answer):
        self.answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        text = next(b.text for b in self.answer.content if b.type == "text")
        yield from (text[:5], text[5:])

    def get_final_message(self):
        return self.answer


class FakeClient:
    def __init__(self, *answers, tokens=1234):
        self.answers, self.tokens, self.calls, self.counts = list(answers), tokens, [], []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.answers.pop(0))

    def count_tokens(self, **kwargs):
        self.counts.append(kwargs)
        if isinstance(self.tokens, Exception):
            raise self.tokens
        return SimpleNamespace(input_tokens=self.tokens)


def status_error(cls, status, body=None):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls(f"Error code: {status}", response=response, body=body)


def test_contract():
    assert api.NAME == "Claude API (paid)"
    assert api.MODELS == ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"]
    assert api.TOKEN_BUDGET == {"claude-sonnet-5": 800_000, "claude-haiku-4-5": 150_000, "claude-opus-5-5": 800_000}
    assert set(api.PRICES) == set(api.MODELS)
    assert issubclass(EngineError, Exception)
    assert api.SYSTEM_PROMPT.startswith("You answer questions about the user's WhatsApp conversations.\n"
                                        "The transcript is provided with this conversation")


def test_build_system_caches_the_transcript():
    assert build_system(TRANSCRIPT) == [
        {"type": "text", "text": api.SYSTEM_PROMPT},
        {"type": "text", "text": TRANSCRIPT, "cache_control": {"type": "ephemeral"}},
    ]


def test_request_shape():
    client = FakeClient(final())
    result = ask(TRANSCRIPT, "Quando?", client=client)
    call = client.calls[0]
    assert set(call) == {"model", "max_tokens", "system", "messages"}   # no temperature/top_p/top_k/thinking
    assert call["model"] == "claude-sonnet-5" and call["max_tokens"] == 32_000
    assert call["system"] == build_system(TRANSCRIPT)
    assert "Today is" not in str(call["system"])                        # variable text would break the cache
    assert call["messages"] == [{"role": "user", "content": f"Today is {date.today():%d/%m/%Y}.\n\nQuando?"}]
    assert result["text"] == "Il 4 settembre [#12]"                      # thinking blocks are not shown
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 5_000,
                               "cache_read_input_tokens": 0}
    assert result["cost_usd"] == pytest.approx((10 * 2 + 20 * 10 + 5_000 * 2.5) / 1e6)


def test_stream_yields_chunks_then_result():
    stream = ask_stream(TRANSCRIPT, "q", model="claude-haiku-4-5", client=FakeClient(final("Ciao mondo [#1]")))
    assert stream.result is None
    assert list(stream) == ["Ciao ", "mondo [#1]"]
    assert stream.result["text"] == "Ciao mondo [#1]"


def test_history_is_append_only():
    first, second = final("A [#1]"), final("B [#2]", cache_creation_input_tokens=0, cache_read_input_tokens=5_000)
    client = FakeClient(first, second)
    r1 = ask(TRANSCRIPT, "q1", model="claude-opus-5-5", client=client)
    session1 = r1["session"]
    assert [m["role"] for m in session1] == ["user", "assistant"]
    assert session1[1]["content"] is first.content                      # stored exactly as returned, thinking included

    r2 = ask(TRANSCRIPT, "q2", session=session1, model="claude-opus-5-5", client=client)
    sent = client.calls[1]["messages"]
    assert sent[:2] == session1 and sent[0] is session1[0] and sent[1] is session1[1]
    assert sent[2]["content"].endswith("q2")
    assert client.calls[1]["system"] == client.calls[0]["system"]       # same transcript: cache hit
    assert len(session1) == 2                                           # earlier session not changed
    assert len(r2["session"]) == 4 and r2["session"][3]["content"] is second.content
    assert r2["usage"]["cache_read_input_tokens"] == 5_000


def test_cost_math():
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
         "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert cost_usd(u, "claude-sonnet-5") == pytest.approx(2 + 10 + 2.5 + 0.2)
    assert cost_usd(u, "claude-haiku-4-5") == pytest.approx(1 + 5 + 1.25 + 0.1)
    assert cost_usd(u, "claude-opus-5-5") == pytest.approx(4 + 20 + 5 + 0.2)

    est = estimate_cost(400_000, "claude-sonnet-5")
    assert est["first"] == pytest.approx((400_000 * 2.5 + 1_000 * 10) / 1e6)       # about $1.01
    assert est["follow_up"] == pytest.approx((400_000 * 0.2 + 1_000 * 10) / 1e6)   # about $0.09
    assert est["follow_up"] < est["first"] / 5


def test_count_tokens():
    client = FakeClient(tokens=4321)
    assert count_tokens(TRANSCRIPT, "claude-haiku-4-5", client=client) == 4321
    assert client.counts == [{"model": "claude-haiku-4-5", "system": build_system(TRANSCRIPT),
                              "messages": [{"role": "user", "content": "?"}]}]


def test_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EngineError, match="No API key found"):
        ask(TRANSCRIPT, "q")
    with pytest.raises(EngineError, match="No API key found"):
        count_tokens(TRANSCRIPT)


@pytest.mark.parametrize("error, expected", [
    (status_error(anthropic.AuthenticationError, 401), "The API key in .env is not valid"),
    (status_error(anthropic.RateLimitError, 429), "The API rate limit is reached"),
    (status_error(anthropic.BadRequestError, 400,
                  {"type": "error", "error": {"type": "invalid_request_error",
                                              "message": "Your credit balance is too low."}}),
     "The Anthropic API returned an error (400): Your credit balance is too low."),
    (status_error(anthropic.InternalServerError, 500, None), "The Anthropic API returned an error (500): Error code: 500"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
     "Could not reach the Anthropic API"),
])
def test_errors(error, expected):
    with pytest.raises(EngineError, match=re.escape(expected)):
        ask(TRANSCRIPT, "q", client=FakeClient(error))
    with pytest.raises(EngineError, match=re.escape(expected)):
        count_tokens(TRANSCRIPT, client=FakeClient(tokens=error))


# --- Real calls (paid): pytest -m api ---------------------------------------------------------------


@pytest.fixture
def large_transcript():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    db = connect(":memory:")
    chat_id = import_chat(db, FIXTURES / "android_it.txt", name="Marco")   # ~6,000 tokens: over every cache minimum
    yield build_transcript(db, [chat_id]), [m["id"] for m in get_messages(db, [chat_id])]
    db.close()


@pytest.mark.api
@pytest.mark.parametrize("model", api.MODELS)
def test_real_answer_cites_and_follow_up_reads_cache(large_transcript, model):
    transcript, ids = large_transcript
    assert count_tokens(transcript, model) > 4_096
    first = ask(transcript, "Quanto costa l'affitto? Rispondi in una frase.", model=model)
    assert extract_citations(first["text"], ids)
    assert first["usage"]["cache_creation_input_tokens"] + first["usage"]["cache_read_input_tokens"] > 4_000
    second = ask(transcript, "E da quando?", session=first["session"], model=model)
    assert second["usage"]["cache_read_input_tokens"] > 4_000
    assert extract_citations(second["text"], ids)
