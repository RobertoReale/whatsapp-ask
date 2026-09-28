# Decisions and verified facts

Things checked by hand before development started, and why the plan looks the way it does. If something here stops being true (new Claude Code version, new WhatsApp export format), update this file and tell the user.

## 2026-09-26: plans reviewed and merged

The project started as two separate Italian drafts (`_archive/whatsapp-ask-web_chat`, `_archive/whatsapp-ask-api`). They were merged into one project with two engines behind one contract: subscription first (Milestone 1), API later (Milestone 2).

### `claude -p` behaviour (Claude Code 2.1.221, Windows 11)

Verified with real calls:

- `claude -p --output-format json --model sonnet --tools "" --safe-mode --system-prompt ...` with the prompt on stdin (no positional argument) works with the Pro/Max login and no API key.
- The JSON has `type`, `subtype`, `is_error`, `result`, `session_id`, `usage` (`input_tokens`, `output_tokens`, cache fields), `modelUsage` (per model, including `contextWindow`: 1,000,000 for `claude-sonnet-5`), `total_cost_usd` (notional under a subscription: do not show it as a cost), `api_error_status`, `num_turns`, `duration_ms`, `stop_reason`.
- `--resume <session_id>` with a new question on stdin continues the conversation and returns the same `session_id`.
- Calling it from Python with `subprocess.run(..., text=True, encoding="utf-8")` round-trips Italian text and emoji. Without `encoding="utf-8"`, Windows uses cp1252 and emoji fail.
- With `--system-prompt`, the base overhead is about 170 input tokens, so almost everything counted is the transcript.
- Running inside a Claude Code session (env `CLAUDECODE=1`) works in `-p` mode, but the engine removes `CLAUDECODE` anyway to be safe.
- `--safe-mode` disables CLAUDE.md, skills, hooks, plugins and MCP servers, and keeps normal auth. `--bare` is **not** usable: it disables OAuth, so the subscription login cannot be used.

### Parser: our own, not `whatstk`

`whatstk` 0.8.1 was tested on a synthetic Italian Android export and **lost data**: it dropped both system lines (the encryption notice and "Anna ha aggiunto Luca") and flagged normal user messages as `system`. On iPhone it worked, but it leaves Italian placeholders such as `immagine omessa`, which the old `<Media omessi>` check missed. It also pulls in pandas.

A ~60-line standard-library parser (in `PLAN.md`, Phase 1) handled both fixtures correctly: all system lines kept, multi-line messages joined, U+200E/U+202F handled, Italian Android and iPhone media placeholders detected.

### Other fixes to the original drafts

- SQLite ignores `ON DELETE CASCADE` unless `PRAGMA foreign_keys = ON` is set on each connection.
- The prompt goes on stdin (not as an argument): this avoids the Windows command-line length limit and quoting of `"`, `%` and newlines, and puts the question after the documents, as Anthropic recommends for long context.
- Windows commands (`.venv\Scripts\...`) were added next to the Unix ones.
- Streamlit 1.64 and pytest 9 install fine on Python 3.14.
- API engine: the live cache test needs a fixture over 1,024 tokens (Sonnet 5 caching minimum; 4,096 for Haiku 4.5), otherwise `cache_read_input_tokens` stays 0. The Haiku ID is `claude-haiku-4-5`.

### Terms of use

The subscription engine is for the user's personal use on their own machine. Do not turn it into a service for other people: that needs the API engine and the user's own API key.

## 2026-09-27: token estimate and budgets calibrated (Phase 6)

Real `usage` input tokens (`input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`) from `claude -p` with Sonnet, next to the original estimate `len(text) // 3`:

| Transcript | Characters (about) | `len // 3` | Real input tokens | Characters per token |
| --- | --- | --- | --- | --- |
| Synthetic fixture `android_it.txt` (150 messages) | 9,300 | 3,107 | 5,992 | 1.56 |
| User's real group chat (9,115 messages) | 640,000 | 213,387 | 375,747 | 1.70 |

The `[#ID] dd/mm/yy hh:mm` header on every line makes transcripts much denser than ordinary text, so `len // 3` was about 1.8–1.9× too low. These numbers replace the ones in `PLAN.md` Phases 3 and 4:

- `estimate_tokens` is now `len(text) * 2 // 3` (1.5 characters per token): slightly above the real count in both cases, so still conservative.
- `TOKEN_BUDGET`: `sonnet` 600,000 (context window 1,000,000, as reported in `modelUsage`; the real 375,747-token chat worked, and the margin leaves room for follow-ups and answers). `haiku` stays at 150,000 (Haiku 4.5 context window: 200,000, as reported in `modelUsage`).
- `usage_level` thresholds unchanged (30,000 / 100,000), but they now apply to a realistic token count, so the same selection shows a higher level than before.

## 2026-09-27: Opus added, empty messages

- **Opus** was added as a third model at the user's request (`MODELS = ["sonnet", "haiku", "opus"]`; `sonnet` stays the default). A real `claude -p --model opus` call with the app's flags works on the user's plan: the model is `claude-opus-5`, with a 1,000,000-token context window, so `TOKEN_BUDGET["opus"]` is 600,000 like Sonnet. Opus uses the plan's limits faster, so the UI says so.
- **Empty messages**: real Android exports contain lines like `14/09/26, 18:05 - Anna: ` with nothing after the colon (272 of 9,115 and 70 of 1,794 messages in the user's two chats; probably content WhatsApp does not export, such as view-once media). The parser is right to keep them as messages with empty text. The UI shows them as "(no text in the export)".

## 2026-09-27: Milestone 2 started, model facts re-checked

Re-checked on the live Anthropic docs (models overview, pricing, prompt caching) before Phase A1. The facts in `docs/PLAN-API.md` still hold:

- `claude-sonnet-5`: 1M context, $2 input / $2.50 5-min cache write / $0.20 cache read / $10 output per million tokens, minimum cacheable prefix 1,024 tokens. The $2/$10 price is now the standard price (the planned rise to $3/$15 was cancelled).
- `claude-haiku-4-5` (alias of `claude-haiku-4-5-20251001`): 200K context, $1 / $1.25 / $0.10 / $5, minimum cacheable prefix 4,096 tokens.
- The full 1M context is billed at the standard rate (no long-context surcharge).

New since the plan was written: **Claude Opus 5.5** (`claude-opus-5-5`: 1M context, $4 / $5 / $0.20 / $20, minimum cacheable prefix 512, adaptive thinking always on). The plan's API engine offers Sonnet 5 and Haiku 4.5 only; adding Opus 5.5 is the user's call.

SDK versions installed: `anthropic` 1.8.0, `python-dotenv` 1.2.3. Without a key, the SDK raises a `TypeError` ("Could not resolve authentication method"), not an `AnthropicError`, so code must check `ANTHROPIC_API_KEY` itself before calling.

Smoke test (Phase A1): `claude-sonnet-5` answered "hi" with 8 input and 14 output tokens (`thinking_tokens` 0). `usage` now also has `cache_creation` (5-min and 1-hour split), `inference_geo`, `output_tokens_details.thinking_tokens` and `service_tier`. An **organization-level** API key fails with 400 "This API key is not scoped to a workspace" unless every request sends the `anthropic-workspace-id` header, and the SDK does not read a workspace ID from the environment. So the README tells the user to create the key inside a workspace (for example "Default"); the code stays unchanged.

## 2026-09-27: API engine (Phase A2)

- **Opus 5.5 added** at the user's request: `MODELS = ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"]`, budget 800,000 like Sonnet 5. Opus 5.5 thinking cannot be turned off, and its thinking blocks are tied to the model and the conversation; the app already starts a new conversation when the model changes.
- `pytest -m api` on the 150-message fixture, first question then a follow-up:

| Model | Cached prefix (tokens) | First question | Follow-up |
| --- | --- | --- | --- |
| `claude-sonnet-5` | 5,797 (cache write) | $0.0152 | $0.0019 (cache read) |
| `claude-haiku-4-5` | 4,920 | $0.0064 | $0.0007 |
| `claude-opus-5-5` | 5,797 | $0.0324 | $0.0029 |

  Haiku 4.5 uses the older tokenizer, so the same text counts about 15% fewer tokens. The local estimate `len * 2 // 3` gives about 6,200 for this fixture, so it stays a slight overestimate for every model.
- Usage and real cost of every answer are printed to the console (the `start.bat` window), and shown under each answer in the UI (Phase A3).

## 2026-09-27: UI for two engines (Phase A3)

- The engine is a sidebar radio; "Claude API (paid)" appears only when `ANTHROPIC_API_KEY` is set (from `.env`). Each model has a one-line tip, the main page has a "How to choose the engine and the model" guide (asked for by the user), and an over-budget selection names the models that can read it.
- `OUTPUT_ALLOWANCE` in the cost estimate went from 2,000 to 1,000 tokens: real short answers used 40–200 output tokens, and 2,000 made follow-ups look ten times dearer than they were.
- Streamlit Markdown treats text between two `$` as a LaTeX formula (the user saw "0.17 ** for the first question" in italics), so dollar amounts are written as `\$`.
- Tests never load the real `.env`: the app fixture replaces `dotenv.load_dotenv` and removes the key.

## 2026-09-27: checks with real chats (Phase A4)

The user ran the API engine (`claude-sonnet-5`) on their real 1:1 chat (1,794 messages) and sent screenshots:

- Exact size: 65,976 tokens (`count_tokens`). The local estimate `len * 2 // 3` gives about 72,000, so it stays a slight overestimate.
- First question: $0.1718, eight valid citations. Follow-ups: $0.0162 and $0.0214, each with 65,971 tokens read from the cache, about ten times cheaper.
- A question about something not in the chat got "I find no messages about…", with nothing invented. A follow-up ("and at what time?") stayed coherent and cited the messages it reasoned from.
- The big group (9,115 messages) counts 303,301 tokens with Haiku 4.5's older tokenizer, so Haiku is blocked, and the error suggests `claude-sonnet-5` or `claude-opus-5-5`.
- As in Milestone 1, the user checked a few representative questions instead of the whole table.
- `.env` is ignored and has never been in any commit.

## 2026-09-27: downloads, word search, removing chats

Asked for by the user ("save in a file all the messages about X, with date and time"), outside `PLAN.md` and `docs/PLAN-API.md`.

- Claude has no tools (`--tools ""`, no tools on the API), so it never writes files. The app builds them: under each answer, the cited messages as CSV, TXT and Markdown, **taken from the database** (full text, exact date and time), not copied from Claude's answer. Claude only chooses which messages are relevant.
- Claude may miss a few messages in very long chats, so there is also **Find messages by word**: a plain case-insensitive substring search (`str.casefold`) over the selected messages, in Python. No FTS5 or index: the selection is already in memory, and SQLite `LIKE` ignores case only for ASCII (`È` ≠ `è`). The page shows the first 100 results; the downloads have all of them.
- CSV: `;` separator and a UTF-8 BOM, so Excel with Italian settings opens it in columns with accents intact (with `,` it puts everything in one column). A cell starting with `=`, `+`, `-` or `@` gets a leading `'`: otherwise Excel reads it as a formula ("+39 333…" becomes `#NAME?`, and a chat message could carry a working `=HYPERLINK`).
- TXT follows the WhatsApp export line format (`dd/mm/yy, hh:mm - Sender: text`) with a `=== Chat ===` line above each chat. Every file groups messages by chat, then sorts them by time.
- Markdown escapes the characters that would change the text (`<Media omessi>` would otherwise vanish as an HTML tag) and includes the `#ID`, so the conversation file's `[#27]` citations can be matched.
- System prompt rule 3 now asks for **every** relevant message (not a sample), each with its `[#ID]`: without the brackets the app finds no citations and there is nothing to download.
- Download buttons use `on_click="ignore"`, so saving a file does not rerun the app. **Download this conversation** is rendered after the new answer, so the file includes it.
- **Remove a chat** (sidebar) deletes the chat (its messages go with `ON DELETE CASCADE`) and the export copy the app saved in `data/` on upload (`source_file`, a bare file name).

## 2026-09-27: Linux

- `pytest` passes on Linux (Docker `python:3.11-slim`, so also the minimum Python version) and `./start.sh` starts the app there. The code needed no change: paths use `pathlib`, every file and subprocess uses `encoding="utf-8"`, and `shutil.which("claude")` and `tempfile.gettempdir()` (`/tmp`) work the same way.
- One test was Windows-only: it read the file extension from the download button's URL. Streamlit guesses that extension from the MIME type with `mimetypes`, and Linux without `/etc/mime.types` knows none for `text/markdown`. The downloaded file is still named correctly (Streamlit sends our `file_name` in `Content-Disposition`), so the test now checks the file names instead.
- `start.sh` (Linux/macOS, next to `start.bat`) must keep LF line endings: `.gitattributes` forces them, otherwise `core.autocrlf` on Windows could break the `#!/bin/sh` line.
- Not verified: a real `claude -p` call on Linux (Claude Code is not installed in the test container). The flags are the same on every platform.

## 2026-09-27: very long chats (search mode)

Asked for by the user, with a screenshot: a real two-year 1:1 chat exported "from the beginning" held **167,887 messages** (2.6 MB zip, first message 15/09/2024).

- **The 40,000-message export limit is wrong** (at least today, for exports without media). The app warned that such a chat "may be truncated", which was false, so the warning and `TRUNCATED_AT` are gone.
- At about 41 tokens per message (the calibration above), that chat is about 7 million tokens: over ten times the 600,000 / 800,000 budgets. Options weighed:
  - **Scan in parts** (same question on each slice, then combine): complete, but about 12 full-budget calls per question, about $14 on the API with Sonnet, and on the subscription most of a 5-hour window. Not built.
  - **Monthly summaries** built once: large job, and summaries lose the exact messages the citations need. Not built.
  - **Search first** (built): Claude writes search words, only matching messages go to Claude. Small, cheap per question, citations work unchanged.
- **Search mode** (`wa/search.py`): the words come from the same engine and the **selected model**, through the normal `ask` (no new engine function; the chat names and senders stand in for the transcript). Haiku was tried first as the "fast" choice, but through `claude -p` it thought for about 4,000 tokens and 35–42 seconds; Sonnet took 5 seconds and 122 output tokens, with better words. Haiku also cut stems too short ("anda", "lett") until the request said not to.
- Matching is a case-insensitive substring search in Python, like **Find messages by word**, not FTS5: the selection is already in memory, 2 seconds is fast enough, and there is no index to build and keep in step with imports and removals. (FTS5 prefix queries such as `affitt*` would also work for stems.) Matches with more and rarer words rank first (weight 1 + ln(messages / matches of the word)); each brings 3 messages before and after from the same chat, up to 100,000 estimated tokens per question.
- Follow-ups search again. The first transcript stays the same (the API engine caches it), and new messages go inside the follow-up question. Citations are checked against the messages actually sent.
- Speed with a synthetic 170,000-message chat: reading and formatting the selection takes about 0.6 s per Streamlit rerun (`format_message` now slices the ISO date instead of `strftime`, six times faster), and a search with 30 words about 2 s. Exact token counting (API) is skipped when the estimate is over twice the budget.
- Checked live (subscription, Sonnet) on the synthetic fixture: 12 words, 61 of 150 messages sent, correct answer with valid citations. Not yet checked on the user's real chat.
