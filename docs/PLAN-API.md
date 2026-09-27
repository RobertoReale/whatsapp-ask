# PLAN-API.md: Milestone 2, paid API engine

**Status: active** (started by the user on 2026-09-27). Start only when the user explicitly says so, and only after Milestone 1 (`PLAN.md`) is complete. Before starting, re-check every model fact below against the live Anthropic docs (models, pricing, caching minimums). They were correct on 2026-09-26 but change over time.

Goal: add a second engine, `api`, that calls Claude through the Anthropic Python SDK with the user's API key. It reuses everything from Milestone 1 (parser, store, context, citations, system prompt, UI) and adds exact token counts, cost estimates, streaming and a larger budget (1M context on Sonnet 5). The subscription engine stays; the user picks the engine in the sidebar.

Same working rules as Milestone 1: one phase per session, tests green, tick boxes, one commit, stop.

## What changes in the project

- `requirements.txt`: add `anthropic` and `python-dotenv`.
- `.env.example` with `ANTHROPIC_API_KEY=` (the user creates the real `.env`, which is git-ignored and denied to Claude).
- New `wa/engines/api.py` implementing the engine contract in `CLAUDE.md`, plus the optional `ask_stream`, `count_tokens` and `estimate_cost`.
- `ENGINES` gets `"api"`. The engine is only offered in the UI when `ANTHROPIC_API_KEY` is set.
- Loading `.env` puts the key in `os.environ`. That is fine: the subscription engine already strips `ANTHROPIC_API_KEY` from its subprocess.
- `CLAUDE.md`: update the stack, the dependency list, the "Out of scope" line about the paid API, and add a "Rules for calling Claude (API engine)" section summarizing the model facts below.

## Model facts (verify again before starting)

| Model ID | Context | Input | 5-min cache write | Cache read | Output | Min. cacheable prefix |
| --- | --- | --- | --- | --- | --- | --- |
| `claude-sonnet-5` (default) | 1M | $2.00 | $2.50 | $0.20 | $10.00 | 1,024 tokens |
| `claude-haiku-4-5` | 200K | $1.00 | $1.25 | $0.10 | $5.00 | 4,096 tokens |

Prices are USD per million tokens. Keep them in one dict in `wa/engines/api.py`.

- Sonnet 5: do **not** send `temperature`, `top_p` or `top_k` (400 error). Adaptive thinking is on by default (omit the `thinking` parameter). Thinking tokens count toward `max_tokens` and are billed as output. Thinking text is omitted by default, so only the answer text is shown. No assistant prefill (400).
- Haiku 4.5: no thinking unless requested (leave it off). Sampling parameters are allowed but not needed.
- Use streaming for every answer call, with `max_tokens=32000`.
- Budgets: `TOKEN_BUDGET = {"claude-sonnet-5": 800_000, "claude-haiku-4-5": 150_000}`, leaving room for the question, history and answer.

## Phase A1: Setup

- [x] Dependencies, `.env.example`, `python-dotenv` loading in `app.py`.
- [x] Pytest marker `api` ("calls the paid Anthropic API"), and `addopts = "-m 'not live and not api'"`.
- [x] `scripts/smoke_test_api.py`: one call to `claude-sonnet-5` answering "hi" that prints `usage`.
- [x] In the summary, remind the user to (a) check the input-tokens-per-minute limit for Sonnet 5 on the Claude Console Limits page (new accounts can have low limits, and a large chat can exceed them in one request), and (b) set a monthly spend limit.

**Done when:** the smoke test prints an answer and `usage`, and `pytest` is green.

## Phase A2: API engine (`wa/engines/api.py`)

- [x] `build_system(transcript)`: `[{"type": "text", "text": <system_prompt.txt>}, {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}}]`. The transcript goes in `system` for this engine, so change the first line of the shared system prompt to "The transcript is provided with this conversation" (true for both engines).
- [x] Nothing variable in `system` (it would break the cache): today's date goes in the user message, as in Milestone 1.
- [x] `session` for this engine = the message history list (opaque to the app). History is **append-only**: store the assistant turn exactly as returned (`final_message.content`, thinking blocks included) and never edit earlier turns. Changing chats, dates, model or engine starts a new conversation.
- [x] `ask_stream(transcript, question, session, model)` yields text chunks and, at the end, makes available `{"text", "session", "usage", "cost_usd"}` (e.g. a small generator wrapper object, or a callback). `ask()` wraps it for the contract.
- [x] `count_tokens(transcript, model)` via `client.messages.count_tokens` (free) with the same `system` and a dummy user message. Cache it in the UI with `st.cache_data` (Streamlit reruns the script on every interaction).
- [x] `estimate_cost(tokens, model)`: first question (cache write) and follow-ups (cache read), plus a rough output allowance.
- [x] Log real `usage` per answer (`cache_creation_input_tokens`, `cache_read_input_tokens`, `input_tokens`, `output_tokens`) and the real cost.
- [x] Errors with the SDK's typed exceptions, most specific first: `AuthenticationError` (bad key), `RateLimitError` (suggest a smaller selection or waiting), `APIStatusError`, `APIConnectionError`, raised as `EngineError`.
- [x] Unit tests with a fake client: request shape (system blocks, `cache_control`, `max_tokens`, no sampling params, date in the user message), append-only history, cost math.
- [x] `@pytest.mark.api` tests on the large fixture (it must be over 1,024 tokens, or caching silently does nothing): at least one valid citation; the second question has `cache_read_input_tokens > 0`.

Starter code:

```python
import anthropic

def build_system(transcript: str):
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": transcript, "cache_control": {"type": "ephemeral"}},
    ]

def count_tokens(transcript: str, model: str = "claude-sonnet-5", client=None) -> int:
    client = client or anthropic.Anthropic()
    r = client.messages.count_tokens(
        model=model, system=build_system(transcript),
        messages=[{"role": "user", "content": "?"}],
    )
    return r.input_tokens

# inside ask_stream:
history = list(session or [])
messages = history + [{"role": "user", "content": f"{today}\n\n{question}"}]
with client.messages.stream(model=model, max_tokens=32000,
                            system=build_system(transcript), messages=messages) as stream:
    for chunk in stream.text_stream:
        yield chunk
    final = stream.get_final_message()
new_session = messages + [{"role": "assistant", "content": final.content}]
```

**Done when:** unit tests pass and `pytest -m api` passes with the user's key.

## Phase A3: UI

- [ ] Engine picker in the sidebar ("Claude subscription" / "Claude API"). The API option is shown only when a key is set. The model list comes from the selected engine.
- [ ] If the engine has `count_tokens`, show exact tokens instead of the estimate. If it has `estimate_cost`, show the estimated cost of the first question and of follow-ups.
- [ ] If the engine has `ask_stream`, stream the answer with `st.write_stream`.
- [ ] Under each API answer, the real cost of that question.
- [ ] In-app guidance (asked by the user on 2026-09-27), so someone who only opens the GUI knows what to choose: what each engine is and what it costs (plan limits vs. paid credits), which model fits which question and selection size, how dates and fewer chats save limits or money, that follow-ups are cheaper, and that new conversations resend all the messages.

**Done when:** the user can switch engines and both work end to end.

## Phase A4: Checks

- [ ] Re-run the Milestone 1 real-chat table with the API engine.
- [ ] A follow-up within 5 minutes shows `cache_read_input_tokens > 0` and a much lower cost.
- [ ] `.env` never in git; `git status` clean.

## Optional experiment: Citations API

Only after A2 works. `scripts/try_citations.py` sends a small fixture as a custom-content document (one content block per message) with `citations: {"enabled": true}` and compares citation quality and tokens with the `[#id]` approach. Report the results in the summary and let the user decide. Do not replace the ID approach on your own.

```python
doc = {
    "type": "document",
    "source": {"type": "content", "content": [
        {"type": "text", "text": f"{m['ts']} {m['sender']}: {m['text']}"} for m in messages
    ]},
    "title": chat_name,
    "citations": {"enabled": True},
    "cache_control": {"type": "ephemeral"},
}
# First user message: [doc, {"type": "text", "text": question}]
# In the answer: citations of type content_block_location -> messages[start_block_index]
```
