# WhatsApp Ask

Ask Claude questions about your own WhatsApp chats. You export a chat from your phone, import it here, choose chats and dates, and ask. Every answer cites the original messages, and you can open each one with the messages around it. You can save the messages it finds as CSV (Excel), TXT or Markdown, or search the chats for an exact word without Claude.

It runs on your computer and can use Claude in two ways, which you pick in the sidebar:

- **Claude subscription** (default): your **Claude Pro or Max plan** through Claude Code. No API key and no extra cost; questions use your plan's usage limits.
- **Claude API (paid)**, optional: your own Anthropic API key. Every question costs a little money, and the app shows the cost before and after each question. See [the paid API](#optional-the-paid-claude-api).

The app also explains these choices on its main page, under **How to use it: what you can do, engine and model**.

## 1. Export a chat from your phone

Only the phone apps can export chats (WhatsApp Web and Desktop cannot). Always choose **Without media**.

- **Android:** open the chat › ⋮ (top right) › More › Export chat › Without media. Save the `.txt` file (for example to Google Drive, or email it to yourself) and copy it to your computer.
- **iPhone:** open the chat › tap the contact or group name at the top › Export Chat › Without Media. Save the `.zip` file (for example with Save to Files, AirDrop or email) and copy it to your computer. You don't need to unzip it.

Limits of WhatsApp exports:

- An export holds at most about 40,000 recent messages. The app warns you when a chat looks cut off and shows the date it starts from.
- Chats with **Advanced Chat Privacy** turned on cannot be exported.
- Photos, videos and voice notes are not read. They appear as "media omitted".

## 2. Install (once)

You need:

- **Python 3.11 or newer** ([python.org](https://www.python.org/downloads/); on Windows, tick "Add python.exe to PATH").
- **Claude Code**, logged in with your Pro or Max account. Install it from [claude.com/claude-code](https://claude.com/claude-code), then open a terminal, run `claude` once and log in.

Then open a terminal in this folder and run:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

(macOS/Linux: `python3 -m venv .venv` and `.venv/bin/python -m pip install -r requirements.txt`.)

## 3. Use it

On Windows, double-click **`start.bat`**. The app opens in your browser. To stop it, close the black window.

From a terminal instead: `.venv\Scripts\python -m streamlit run app.py`.

1. **Import**: in the sidebar, upload one or more `.txt` or `.zip` exports. Uploading a chat with the same name again replaces the old copy.
2. **Select**: choose the chats and, if you like, a date range. The sidebar shows how many messages are selected, their size in tokens and either the usage level (low, medium or high; subscription) or the estimated cost (API).
3. **Ask**: type a question in any language. Claude answers in the language of your question.
4. **Check the sources**: open **Cited messages** under an answer to see each cited message, highlighted, with 2 messages before and after it.
5. **Save the results**: under an answer, download its cited messages with date, time and full text as **CSV** (opens in Excel), **TXT** (like a WhatsApp export) or **Markdown**. **Download this conversation**, under the last answer, saves the questions, the answers and their cited messages as Markdown. Files go to your browser's downloads folder.

Follow-up questions continue the same conversation. **New conversation** starts over. Changing the chats, the dates, the engine or the model also starts over.

Tips:

- To collect every message about something, ask "Find all the messages about the rent" and download the cited messages. Claude also finds messages that use other words, but in very long chats it may miss a few. For an exact word, open **Find messages by word** instead: it searches the selected chats and dates without Claude, so it is instant, free and complete, and it has the same downloads.
- Ask for exact facts ("What time are we meeting on Saturday?"), searches ("Find the messages where Marco talks about the rent"), summaries ("What did the group decide in September?") or comparisons across chats ("In which chat did we talk about the flight?").
- If a selection is too large, the app blocks it: choose fewer chats or a shorter date range.
- **Sonnet** (`sonnet`, `claude-sonnet-5`) gives good answers and is the default. **Haiku** (`haiku`, `claude-haiku-4-5`) is the fastest and cheapest, fine for small chats and simple questions, but it cannot read very large selections. **Opus** (`opus`, `claude-opus-5-5`) is the most capable, but uses your plan's limits faster and, on the API, costs twice as much as Sonnet: keep it for hard questions.

## Usage limits

Every question uses part of your plan's usage limits. These are the same limits as claude.ai, and they reset in 5-hour windows.

- The first question sends **all the selected messages** to Claude. That is what the usage level shows: a large selection uses a large share of your limits on every new conversation.
- Follow-up questions continue the conversation. Claude Code keeps the messages in a short-lived cache, so follow-ups within about an hour usually weigh less.
- When the limit is reached, the app says so. Wait for the reset, or select less.
- The subscription engine never uses an API key. Even if `ANTHROPIC_API_KEY` is set (for example in `.env` for the paid engine), it is not passed to Claude Code, so subscription questions are never billed through the paid API.

## Optional: the paid Claude API

Use it if you have no Pro/Max plan, if your plan's limits run out, or if you want exact token counts, costs and answers that appear while they are written.

1. On [platform.claude.com](https://platform.claude.com), add some credit in **Billing** (a few dollars are plenty) and set a **monthly spend limit** in **Settings › Limits**.
2. In **Settings › API Keys**, click **Create Key** and choose a **workspace** (for example "Default"). A key without a workspace does not work with this app.
3. In this folder, copy `.env.example` to `.env`, open it with Notepad and paste the key after `ANTHROPIC_API_KEY=` (PowerShell: `Copy-Item .env.example .env; notepad .env`).
4. Restart the app (close the black window and double-click `start.bat`). **Claude API (paid)** now appears under **Engine** in the sidebar.

What it costs (prices of September 2026, in US dollars): the first question sends all the selected messages, and follow-ups asked within 5 minutes read them from Anthropic's cache for about a tenth of the price.

| Selection | Model | First question | Follow-up within 5 minutes |
| --- | --- | --- | --- |
| A small chat (150 messages, about 6,000 tokens) | Sonnet | about $0.02 | less than $0.01 |
| A big group (9,000 messages, about 375,000 tokens) | Sonnet | about $0.95 | about $0.08 |
| The same big group | Opus | about $1.90 | about $0.10 |

The sidebar shows the exact number of tokens and the estimated cost before you ask. Each answer shows its real cost, and the black `start.bat` window prints it too. The `.env` file stays on your computer and is never added to git.

## Where your data lives

Everything stays on your computer, except the messages you send to Claude with each question.

- **`data/`** in this folder: your uploaded exports and the database (`wa.db`). **Remove a chat**, at the bottom of the sidebar, deletes one chat's messages and its export copy. Delete the folder to remove everything the app imported. It is never added to git.
- **Downloaded files** (cited messages, search results, conversations) contain your messages: they go to your browser's downloads folder, outside the app.
- **Claude Code's session files**: Claude Code saves every conversation, including the chat messages sent, under `%USERPROFILE%\.claude\projects\` in a folder whose name ends with `whatsapp-ask-runtime` (for example `C--Users-<you>-AppData-Local-Temp-whatsapp-ask-runtime`). They are local only. Delete that folder to remove them.
- **Claude API**: the selected messages are sent to the Anthropic API with each question, and nothing is saved on your computer apart from `data/`.
- The app is only reachable from this computer (`localhost`), not from other devices on your network.

WhatsApp Ask is for your own personal use on your own computer. Messages are sent to Anthropic's Claude to answer your questions, under the terms of your Claude plan.

## Troubleshooting

| Message | What to do |
| --- | --- |
| Claude Code is not installed or not on PATH | Install Claude Code, then close and reopen the app. |
| Claude Code is not logged in | Open a terminal, run `claude` and log in with your Pro/Max account. |
| Your plan's usage limit is reached | Wait for the reset, or select fewer chats or dates. |
| Claude took too long | Select fewer chats or a shorter date range. |
| No WhatsApp messages found in … | The file is not a WhatsApp export. Export the chat again from the phone. |
| The .venv folder is missing (from `start.bat`) | Run the two install commands above. |
| No **Claude API** option under Engine | Put your key in `.env` (see [the paid API](#optional-the-paid-claude-api)) and restart the app. |
| The API key in .env is not valid | Create a new key in the Claude Console and paste it in `.env`. |
| … not scoped to a workspace … | Create a new key inside a workspace (for example "Default") and paste it in `.env`. |
| … credit balance is too low | Add credit in **Billing** on platform.claude.com. |
| The API rate limit is reached | Wait a minute, or select fewer chats or a shorter date range. |

## For developers

See `CLAUDE.md`, `PLAN.md` and `docs/PLAN-API.md`. Unit tests never call Claude: `pytest`. Real calls: `pytest -m live` (uses some of your plan's usage limits) and `pytest -m api` (paid, a few cents).

## License

MIT, see [LICENSE](LICENSE).
