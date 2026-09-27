# WhatsApp Ask

Ask Claude questions about your own WhatsApp chats. You export a chat from your phone, import it here, choose chats and dates, and ask. Every answer cites the original messages, and you can open each one with the messages around it.

It runs on your computer and uses your **Claude Pro or Max subscription** through Claude Code. No API key and no extra cost.

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
2. **Select**: choose the chats and, if you like, a date range. The sidebar shows how many messages are selected, the estimated size and the usage level (low, medium or high).
3. **Ask**: type a question in any language. Claude answers in the language of your question.
4. **Check the sources**: open **Cited messages** under an answer to see each cited message, highlighted, with 2 messages before and after it.

Follow-up questions continue the same conversation. **New conversation** starts over. Changing the chats, the dates or the model also starts over.

Tips:

- Ask for exact facts ("What time are we meeting on Saturday?"), searches ("Find the messages where Marco talks about the rent"), summaries ("What did the group decide in September?") or comparisons across chats ("In which chat did we talk about the flight?").
- If a selection is too large, the app blocks it: choose fewer chats or a shorter date range.
- `sonnet` gives good answers and is the default. `haiku` is faster and fine for small chats and simple questions. `opus` is the most capable, but uses your plan's limits faster: keep it for hard questions.

## Usage limits

Every question uses part of your plan's usage limits. These are the same limits as claude.ai, and they reset in 5-hour windows.

- The first question sends **all the selected messages** to Claude. That is what the usage level shows: a large selection uses a large share of your limits on every new conversation.
- Follow-up questions continue the conversation. Claude Code keeps the messages in a short-lived cache, so follow-ups within about an hour usually weigh less.
- When the limit is reached, the app says so. Wait for the reset, or select less.
- The app never uses an API key. If `ANTHROPIC_API_KEY` is set on your computer, the app ignores it, so you are never billed through the paid API.

## Where your data lives

Everything stays on your computer, except the messages you send to Claude with each question.

- **`data/`** in this folder: your uploaded exports and the database (`wa.db`). Delete the folder to remove everything the app imported. It is never added to git.
- **Claude Code's session files**: Claude Code saves every conversation, including the chat messages sent, under `%USERPROFILE%\.claude\projects\` in a folder whose name ends with `whatsapp-ask-runtime` (for example `C--Users-<you>-AppData-Local-Temp-whatsapp-ask-runtime`). They are local only. Delete that folder to remove them.
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

## For developers

See `CLAUDE.md` and `PLAN.md`. Unit tests never call Claude: `pytest`. Real calls: `pytest -m live` (uses some of your usage limits).
