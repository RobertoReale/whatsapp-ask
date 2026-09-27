"""Milestone 2 engine: the Anthropic API with the user's key (paid, billed per token).

The model facts behind this file are in docs/PLAN-API.md and docs/DECISIONS.md. The whole transcript
goes in `system` with a cache breakpoint, so follow-ups within 5 minutes read it from the cache.
"""

import os
from datetime import date
from pathlib import Path

import anthropic

NAME = "Claude API (paid)"
MODELS = ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"]
TOKEN_BUDGET = {"claude-sonnet-5": 800_000, "claude-haiku-4-5": 150_000,   # context windows: 1M, 200k, 1M
                "claude-opus-5-5": 800_000}
PRICES = {   # USD per million tokens (2026-09-27): input, 5-minute cache write, cache read, output
    "claude-sonnet-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "cache_write": 1.25, "cache_read": 0.10, "output": 5.00},
    "claude-opus-5-5": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
}
MAX_TOKENS = 32_000          # thinking tokens count toward this and are billed as output
OUTPUT_ALLOWANCE = 1_000     # rough output (thinking + answer) per question; real short answers: 40-200 tokens

PROMPT_FILE = Path(__file__).resolve().parent.parent / "system_prompt.txt"
SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")

NO_KEY = "No API key found. Copy .env.example to .env, paste your Anthropic API key and restart the app."
BAD_KEY = "The API key in .env is not valid. Create a new key in the Claude Console and paste it in .env."
RATE_LIMIT = ("The API rate limit is reached. Wait a minute and try again, "
              "or select fewer chats or a shorter date range.")
NO_CONNECTION = "Could not reach the Anthropic API. Check your internet connection and try again."


class EngineError(Exception):
    pass


def _client(client):
    if client:
        return client
    if not os.environ.get("ANTHROPIC_API_KEY"):   # without a key the SDK raises a TypeError, not an API error
        raise EngineError(NO_KEY)
    return anthropic.Anthropic()


def _engine_error(e: anthropic.AnthropicError) -> EngineError:
    if isinstance(e, anthropic.AuthenticationError):
        return EngineError(BAD_KEY)
    if isinstance(e, anthropic.RateLimitError):
        return EngineError(RATE_LIMIT)
    if isinstance(e, anthropic.APIStatusError):
        error = e.body.get("error") if isinstance(e.body, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        return EngineError(f"The Anthropic API returned an error ({e.status_code}): {(message or e.message)[:500]}")
    if isinstance(e, anthropic.APIConnectionError):
        return EngineError(NO_CONNECTION)
    return EngineError(str(e)[:500])


def build_system(transcript: str) -> list[dict]:
    # Nothing variable here (like today's date): any change would break the cache.
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}},
    ]


def cost_usd(usage: dict, model: str) -> float:
    p = PRICES[model]
    return (usage["input_tokens"] * p["input"] + usage["cache_creation_input_tokens"] * p["cache_write"]
            + usage["cache_read_input_tokens"] * p["cache_read"] + usage["output_tokens"] * p["output"]) / 1e6


def estimate_cost(tokens: int, model: str) -> dict:
    """Rough cost in USD of the first question (writes the cache) and of a follow-up within 5 minutes (reads it)."""
    p = PRICES[model]
    output = OUTPUT_ALLOWANCE * p["output"]
    return {"first": (tokens * p["cache_write"] + output) / 1e6,
            "follow_up": (tokens * p["cache_read"] + output) / 1e6}


def count_tokens(transcript: str, model: str | None = None, client=None) -> int:
    """Exact input tokens of the transcript and system prompt (the endpoint is free)."""
    try:
        r = _client(client).messages.count_tokens(model=model or MODELS[0], system=build_system(transcript),
                                                  messages=[{"role": "user", "content": "?"}])
    except anthropic.AnthropicError as e:
        raise _engine_error(e) from e
    return r.input_tokens


class AnswerStream:
    """Iterate to get the answer's text chunks. Afterwards `result` holds
    {"text", "session", "usage", "cost_usd"}. Errors are raised as EngineError while iterating."""

    def __init__(self, transcript, question, session, model, client):
        self.transcript, self.question, self.session = transcript, question, session
        self.model, self.client = model or MODELS[0], client
        self.result = None

    def __iter__(self):
        client = _client(self.client)
        history = list(self.session or [])
        messages = history + [{"role": "user", "content": f"Today is {date.today():%d/%m/%Y}.\n\n{self.question}"}]
        try:
            with client.messages.stream(model=self.model, max_tokens=MAX_TOKENS,
                                        system=build_system(self.transcript), messages=messages) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
        except anthropic.AnthropicError as e:
            raise _engine_error(e) from e
        u = final.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
                 "cache_read_input_tokens": u.cache_read_input_tokens or 0}
        cost = cost_usd(usage, self.model)
        print(f"[api] {self.model} usage {usage} cost ${cost:.4f}", flush=True)   # shows in the start.bat window
        self.result = {
            "text": "".join(b.text for b in final.content if b.type == "text"),
            # Append-only: the assistant turn is stored exactly as returned, thinking blocks included.
            "session": messages + [{"role": "assistant", "content": final.content}],
            "usage": usage,
            "cost_usd": cost,
        }


def ask_stream(transcript: str, question: str, session=None, model: str | None = None, client=None) -> AnswerStream:
    return AnswerStream(transcript, question, session, model, client)


def ask(transcript: str, question: str, session=None, model: str | None = None, client=None) -> dict:
    stream = ask_stream(transcript, question, session=session, model=model, client=client)
    for _ in stream:
        pass
    return stream.result
