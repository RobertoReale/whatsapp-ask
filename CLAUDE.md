# whatsapp-ask

Local app to ask Claude questions about your own WhatsApp chats, exported from the phone (`.txt` / `.zip`). The user selects one or more chats and a date range, asks questions, and gets answers that cite the original messages, which can be opened with their surrounding context.

One project, two AI engines behind the same interface:

| Milestone | Engine | How it calls Claude | Status |
| --- | --- | --- | --- |
| 1 | `subscription` (the "web chat" version) | `claude -p` (Claude Code, non-interactive) with the user's Pro/Max subscription. No API key. | **Active**: `PLAN.md` |
| 2 | `api` | Anthropic Python SDK with a paid API key | **Future**: `docs/PLAN-API.md`. Do not implement until the user explicitly starts Milestone 2. |

Read `PLAN.md` before starting any work. `docs/DECISIONS.md` lists facts that were verified by hand and the reasons behind non-obvious choices. Do not undo those choices without asking.

## Stack (Milestone 1)

- Python 3.11+ (the user's machine runs 3.14 on Windows 11)
- Streamlit (local UI)
- SQLite via the standard library `sqlite3`
- WhatsApp export parser: **our own, standard library only** (no `whatstk`; see `docs/DECISIONS.md`)
- Claude Code CLI `claude -p` as the AI engine
- pytest

Runtime dependencies: `streamlit` only (`pytest` for development). Ask before adding any other dependency.

## Commands

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1   | Git Bash: source .venv/Scripts/activate   | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py              # start the app
pytest                            # unit tests (never call Claude)
pytest -m live                    # tests that really call `claude -p` (use some of the plan's usage limits)
python scripts/smoke_test.py      # one tiny real call, prints the raw JSON
```

## Layout

```text
app.py                        # Streamlit UI
wa/parser.py                  # export .txt/.zip -> list of message dicts
wa/store.py                   # SQLite: chats and messages tables
wa/context.py                 # transcript formatting, token estimate, usage level
wa/citations.py               # extract [#id] citations from answers
wa/system_prompt.txt          # instructions for Claude when answering about chats (shared by all engines)
wa/engines/__init__.py        # ENGINES registry: {"subscription": ...} (+ "api" in Milestone 2)
wa/engines/subscription.py    # Milestone 1: `claude -p`
wa/engines/api.py             # Milestone 2 only: Anthropic SDK
scripts/smoke_test.py         # one real `claude -p` call
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

Milestone 2 may add optional functions (`ask_stream`, `count_tokens`, `estimate_cost`). The app checks for them with `hasattr`. Do not add anything else to the contract.

## Working rules

- Work on `PLAN.md` phases in order, **one phase per session** unless the user explicitly asks for more. A phase is done only when `pytest` is green and its **Done when** is true. Then tick its checkboxes in `PLAN.md`, make one git commit for the phase, write a short summary (what was done and what the user should try by hand), and **stop**.
- If a phase turns out to be wrong or impossible as written, stop and explain. Do not silently redesign it.
- Keep the code simple: no abstractions, options or configurability that `PLAN.md` does not ask for.
- UI text in English. Claude answers in the language of the user's question (the user's chats are mostly Italian).
- Git: never add "Co-authored-by" or any mention of Claude in commit messages. Never push.

## Data and privacy rules

- Never commit `.env`, `data/`, `*.txt`, `*.zip`, `*.db`. `.gitignore` already covers them; check `git status` before every commit.
- Tests use **only synthetic chats** in `tests/fixtures/` (`.gitignore` ignores `*.txt`/`*.zip` everywhere except there and `wa/system_prompt.txt`). Never read files in `data/`: the user runs real exports themselves and reports back.
- Unit tests never call `claude`: `wa/engines/subscription.py` takes an injectable `runner` (default `subprocess.run`), and tests pass a fake one. Real calls are marked `@pytest.mark.live` and excluded by default (`addopts = "-m 'not live'"`).

## Rules for calling Claude (subscription engine)

All of these were verified on 2026-09-26 with Claude Code 2.1.221 on Windows; see `docs/DECISIONS.md`.

- Call the `claude` CLI, never the `anthropic` SDK or an API key, in Milestone 1.
- Resolve the executable with `shutil.which("claude")` (Windows needs the full path).
- Remove `ANTHROPIC_API_KEY` from the subprocess environment. If it is set, Claude Code bills the paid API instead of the subscription. Also remove `CLAUDECODE`.
- Flags: `-p --output-format json --model <sonnet|haiku> --tools "" --safe-mode --system-prompt-file wa/system_prompt.txt`. `--tools ""` means no tools, so Claude only reads and answers. `--safe-mode` disables CLAUDE.md files, skills, hooks, plugins and MCP servers while keeping subscription auth.
- Run the subprocess with `cwd` set to a folder **outside the project** (`<tempdir>/whatsapp-ask-runtime`).
- Send the whole prompt on **stdin**, with no positional prompt argument: transcript first, then the question. This avoids Windows command-line limits and quoting problems. Always use `encoding="utf-8"` (Windows otherwise uses cp1252 and emoji crash).
- Follow-ups: `--resume <session_id>`, with only the new question on stdin. Changing the selected chats, dates, model or engine starts a new conversation.
- Treat the result as failed if `returncode != 0` **or** `is_error` is true in the JSON. `api_error_status` holds the HTTP status (e.g. 429 = plan limit reached).

## Out of scope

Direct connection to WhatsApp Web/Desktop, unofficial libraries (whatsmeow, Baileys, whatsapp-web.js), vector databases or embeddings, images and voice notes, sending messages, user accounts, server deployment, and (until Milestone 2) the paid API.
