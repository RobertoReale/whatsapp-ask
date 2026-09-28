# whatsapp-ask

Local app to ask Claude questions about your own WhatsApp chats, exported from the phone (`.txt` / `.zip`). The user selects one or more chats and a date range, asks questions, and gets answers that cite the original messages, which can be opened with their surrounding context.

One project, two AI engines behind the same interface:

| Milestone | Engine | How it calls Claude | Status |
| --- | --- | --- | --- |
| 1 | `subscription` (the "web chat" version) | `claude -p` (Claude Code, non-interactive) with the user's Pro/Max subscription. No API key. | **Complete**: `PLAN.md` |
| 2 | `api` | Anthropic Python SDK with a paid API key | **Active** (started by the user on 2026-09-27): `docs/PLAN-API.md` |

Read `PLAN.md` before starting any work. `docs/DECISIONS.md` lists facts that were verified by hand and the reasons behind non-obvious choices. Do not undo those choices without asking.

## Stack (Milestone 1)

- Python 3.11+ (the user's machine runs 3.14 on Windows 11)
- Streamlit (local UI)
- SQLite via the standard library `sqlite3`
- WhatsApp export parser: **our own, standard library only** (no `whatstk`; see `docs/DECISIONS.md`)
- Claude Code CLI `claude -p` as the AI engine
- pytest

Runtime dependencies: `streamlit`, plus `anthropic` and `python-dotenv` for the API engine (`pytest` for development). Ask before adding any other dependency.

## Commands

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1   | Git Bash: source .venv/Scripts/activate   | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py              # start the app
pytest                            # unit tests (never call Claude)
pytest -m live                    # tests that really call `claude -p` (use some of the plan's usage limits)
pytest -m api                     # tests that call the paid Anthropic API (cost money; need .env)
python scripts/smoke_test.py      # one tiny real call, prints the raw JSON
python scripts/smoke_test_api.py  # one tiny paid API call, prints the answer and usage
```

## Layout

```text
app.py                        # Streamlit UI
wa/parser.py                  # export .txt/.zip -> list of message dicts
wa/store.py                   # SQLite: chats and messages tables
wa/context.py                 # transcript formatting, token estimate, usage level
wa/citations.py               # extract [#id] citations from answers
wa/search.py                  # search mode for selections too large to send whole: Claude picks words, only matches go
wa/export.py                  # messages and conversations as CSV / TXT / Markdown files for download
wa/system_prompt.txt          # instructions for Claude when answering about chats (shared by all engines)
wa/engines/__init__.py        # ENGINES registry: {"subscription": ...} (+ "api" in Milestone 2)
wa/engines/subscription.py    # Milestone 1: `claude -p`
wa/engines/api.py             # Milestone 2: Anthropic SDK with the user's API key (paid)
scripts/smoke_test.py         # one real `claude -p` call
scripts/smoke_test_api.py     # one real Anthropic API call (Milestone 2)
.env.example                  # template for .env (ANTHROPIC_API_KEY); .env is never in git, never read by Claude
tests/fixtures/               # synthetic chats only
tests/                        # pytest
data/                         # user's exports and wa.db: NEVER in git, never read by Claude
docs/                         # PLAN-API.md, DECISIONS.md
_archive/                     # old Italian drafts, superseded: ignore
```

## Engine contract

Every engine module exposes the same small surface, so `app.py` does not care which one is active:

```python
NAME: str                     # label shown in the UI
MODELS: list[str]             # first item is the default
TOKEN_BUDGET: dict[str, int]  # per model; selections above it are blocked
class EngineError(Exception): ...   # message is user-facing, in plain English
def ask(transcript: str, question: str, session=None, model: str | None = None) -> dict:
    """Returns {"text": str, "session": <opaque>, "usage": dict | None}.
    session=None starts a new conversation; pass back the returned session for follow-ups.
    The app stores `session` without looking inside it."""
```

Milestone 2 may add optional functions (`ask_stream`, `count_tokens`, `estimate_cost`). The app checks for them with `hasattr`. The API engine's results also carry `cost_usd` (the app reads it with `.get`). Do not add anything else to the contract.

## Working rules

- Work on `PLAN.md` phases in order, **one phase per session** unless the user explicitly asks for more. A phase is done only when `pytest` is green and its **Done when** is true. Then tick its checkboxes in `PLAN.md`, make one git commit for the phase, write a short summary (what was done and what the user should try by hand), and **stop**.
- If a phase turns out to be wrong or impossible as written, stop and explain. Do not silently redesign it.
- Keep the code simple: no abstractions, options or configurability that `PLAN.md` does not ask for.
- UI text in English. Claude answers in the language of the user's question (the user's chats are mostly Italian).
- Git: never add "Co-authored-by" or any mention of Claude in commit messages. The repo is public at `github.com/RobertoReale/whatsapp-ask`: push only when the user asks, and only after checking that nothing private (exports, `.env`, real names or messages from the user's chats) is in the commits.

## Data and privacy rules

- Never commit `.env`, `data/`, `*.txt`, `*.zip`, `*.db`. `.gitignore` already covers them; check `git status` before every commit.
- Tests use **only synthetic chats** in `tests/fixtures/` (`.gitignore` ignores `*.txt`/`*.zip` everywhere except there and `wa/system_prompt.txt`). Never read files in `data/`: the user runs real exports themselves and reports back.
- Unit tests never call `claude`: `wa/engines/subscription.py` takes an injectable `runner` (default `subprocess.run`), and tests pass a fake one. Real calls are marked `@pytest.mark.live` and excluded by default (`addopts = "-m 'not live'"`).

## Rules for calling Claude (subscription engine)

All of these were verified on 2026-09-26 with Claude Code 2.1.221 on Windows; see `docs/DECISIONS.md`.

- Call the `claude` CLI, never the `anthropic` SDK or an API key, in Milestone 1.
- Resolve the executable with `shutil.which("claude")` (Windows needs the full path).
- Remove `ANTHROPIC_API_KEY` from the subprocess environment. If it is set, Claude Code bills the paid API instead of the subscription. Also remove `CLAUDECODE`.
- Flags: `-p --output-format json --model <sonnet|haiku|opus> --tools "" --safe-mode --system-prompt-file wa/system_prompt.txt`. `--tools ""` means no tools, so Claude only reads and answers. `--safe-mode` disables CLAUDE.md files, skills, hooks, plugins and MCP servers while keeping subscription auth.
- Run the subprocess with `cwd` set to a folder **outside the project** (`<tempdir>/whatsapp-ask-runtime`).
- Send the whole prompt on **stdin**, with no positional prompt argument: transcript first, then the question. This avoids Windows command-line limits and quoting problems. Always use `encoding="utf-8"` (Windows otherwise uses cp1252 and emoji crash).
- Follow-ups: `--resume <session_id>`, with only the new question on stdin. Changing the selected chats, dates, model or engine starts a new conversation.
- Treat the result as failed if `returncode != 0` **or** `is_error` is true in the JSON. `api_error_status` holds the HTTP status (e.g. 429 = plan limit reached).

## Rules for calling Claude (API engine)

Verified on 2026-09-27 with `anthropic` 1.8.0; see `docs/DECISIONS.md` and `docs/PLAN-API.md`.

- Models: `claude-sonnet-5` (default, 1M context), `claude-haiku-4-5` (200K), `claude-opus-5-5` (1M). Prices live in one dict, `PRICES`, in `wa/engines/api.py`. Re-check them on the live docs before changing anything.
- Never send `temperature`, `top_p`, `top_k` (400 on Sonnet 5), `thinking` (adaptive by default on Sonnet 5, always on for Opus 5.5) or an assistant prefill.
- `system` = the shared system prompt, then the transcript with `cache_control: {"type": "ephemeral"}`. Nothing variable in `system`: today's date goes in the user message.
- Every answer call streams, with `max_tokens=32000`. The session is the message list, append-only: the assistant turn is stored exactly as returned (`final.content`, thinking blocks included).
- Without `ANTHROPIC_API_KEY` the SDK raises a `TypeError`, so the engine checks the key itself. Keys must belong to a workspace (an organization-level key gets a 400).
- Unit tests pass a fake `client`. Real calls are marked `@pytest.mark.api` and excluded by default.

## Out of scope

Direct connection to WhatsApp Web/Desktop, unofficial libraries (whatsmeow, Baileys, whatsapp-web.js), vector databases or embeddings, images and voice notes, sending messages, user accounts, and server deployment.
