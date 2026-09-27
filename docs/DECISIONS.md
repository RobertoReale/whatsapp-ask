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
