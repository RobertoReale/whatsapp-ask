"""Milestone 1 engine: `claude -p` with the Pro/Max subscription. No API key.

The rules for calling the CLI are in CLAUDE.md ("Rules for calling Claude") and docs/DECISIONS.md.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

NAME = "Claude subscription (claude -p)"
MODELS = ["sonnet", "haiku", "opus"]
TOKEN_BUDGET = {"sonnet": 600_000, "haiku": 150_000, "opus": 600_000}   # context windows: 1M, 200k, 1M

RUNTIME_DIR = Path(tempfile.gettempdir()) / "whatsapp-ask-runtime"   # outside the project
PROMPT_FILE = Path(__file__).resolve().parent.parent / "system_prompt.txt"

NOT_INSTALLED = "Claude Code is not installed or not on PATH. Install it and log in with your Pro/Max account."
NOT_LOGGED_IN = "Claude Code is not logged in. Run `claude` once in a terminal and log in."
LIMIT_REACHED = "Your plan's usage limit is reached. Try again after it resets."
TOO_SLOW = "Claude took too long. Select fewer chats or a shorter date range."


class EngineError(Exception):
    pass


def _env() -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)   # otherwise Claude Code bills the paid API, not the subscription
    env.pop("CLAUDECODE", None)          # set when running inside a Claude Code session
    return env


def _error_message(status, text: str) -> str:
    lower = text.lower()
    if status in (401, 403) or any(w in lower for w in ("login", "log in", "logged in", "authenticat")):
        return NOT_LOGGED_IN
    if status == 429 or any(w in lower for w in ("usage limit", "rate limit", "limit reached")):
        return LIMIT_REACHED
    return text[:500] or "Claude Code failed without an error message."


def ask(transcript: str, question: str, session=None, model=None,
        runner=subprocess.run, timeout: int = 600) -> dict:
    exe = shutil.which("claude")
    if not exe:
        raise EngineError(NOT_INSTALLED)
    RUNTIME_DIR.mkdir(exist_ok=True)
    cmd = [exe, "-p", "--output-format", "json", "--model", model or MODELS[0],
           "--tools", "", "--safe-mode", "--system-prompt-file", str(PROMPT_FILE)]
    today = f"Today is {date.today():%d/%m/%Y}."
    if session:
        cmd += ["--resume", session]
        prompt = f"{today}\n\n{question}"             # transcript is already in the conversation
    else:
        prompt = f"{transcript}\n\n{today}\n\n{question}"
    try:
        out = runner(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                     cwd=RUNTIME_DIR, env=_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EngineError(TOO_SLOW)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise EngineError(_error_message(None, out.stderr or out.stdout or ""))
    if out.returncode != 0 or data.get("is_error"):
        text = str(data.get("result") or out.stderr or "")
        raise EngineError(_error_message(data.get("api_error_status"), text))
    return {"text": data["result"], "session": data["session_id"], "usage": data.get("usage")}
