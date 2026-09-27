import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from wa.citations import extract_citations
from wa.engines import ENGINES, subscription
from wa.engines.subscription import EngineError, ask

PROJECT = Path(__file__).resolve().parent.parent
EXE = "C:/fake/bin/claude.exe"


def ok_json(**kw):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": "Il 4 settembre [#12]", "session_id": "sess-1",
                       "usage": {"input_tokens": 100, "output_tokens": 20}, **kw})


class FakeRunner:
    def __init__(self, stdout=None, stderr="", returncode=0, raises=None):
        self.stdout = ok_json() if stdout is None else stdout
        self.stderr, self.returncode, self.raises = stderr, returncode, raises
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.raises:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)

    @property
    def cmd(self):
        return self.calls[-1][0]

    @property
    def kwargs(self):
        return self.calls[-1][1]


@pytest.fixture(autouse=True)
def fake_which(monkeypatch):
    monkeypatch.setattr(subscription.shutil, "which", lambda name: EXE if name == "claude" else None)


def test_contract():
    assert ENGINES == {"subscription": subscription}
    assert subscription.NAME == "Claude subscription (claude -p)"
    assert subscription.MODELS == ["sonnet", "haiku", "opus"]
    assert subscription.TOKEN_BUDGET == {"sonnet": 600_000, "haiku": 150_000, "opus": 600_000}
    assert issubclass(EngineError, Exception)
    assert subscription.PROMPT_FILE.read_text(encoding="utf-8").startswith(
        "You answer questions about the user's WhatsApp conversations.")


def test_first_question_command_and_stdin():
    run = FakeRunner()
    result = ask("<documents>TRANSCRIPT</documents>", "Quando?", runner=run)
    assert result == {"text": "Il 4 settembre [#12]", "session": "sess-1",
                      "usage": {"input_tokens": 100, "output_tokens": 20}}

    cmd = run.cmd
    assert cmd[0] == EXE and cmd[1] == "-p"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--safe-mode" in cmd
    assert cmd[cmd.index("--system-prompt-file") + 1] == str(subscription.PROMPT_FILE)
    assert "--resume" not in cmd
    # No positional prompt: every argument after -p is a flag or a flag's value.
    assert "Quando?" not in cmd and not any("TRANSCRIPT" in c for c in cmd)
    assert cmd == [EXE, "-p", "--output-format", "json", "--model", "sonnet", "--tools", "",
                   "--safe-mode", "--system-prompt-file", str(subscription.PROMPT_FILE)]

    stdin = run.kwargs["input"]
    transcript, today, question = stdin.split("\n\n")
    assert transcript == "<documents>TRANSCRIPT</documents>"
    assert today.startswith("Today is ") and today.endswith(".")
    assert question == "Quando?"


def test_subprocess_options(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")
    run = FakeRunner()
    ask("t", "q", runner=run, timeout=42)
    kw = run.kwargs
    assert "ANTHROPIC_API_KEY" not in kw["env"] and "CLAUDECODE" not in kw["env"]
    assert kw["env"]["KEEP_ME"] == "yes"
    assert kw["encoding"] == "utf-8" and kw["text"] is True and kw["capture_output"] is True
    assert kw["timeout"] == 42
    cwd = Path(kw["cwd"]).resolve()
    assert cwd == subscription.RUNTIME_DIR.resolve() and cwd.is_dir()
    assert PROJECT not in cwd.parents and cwd != PROJECT


def test_follow_up_resumes_without_transcript():
    run = FakeRunner()
    ask("<documents>TRANSCRIPT</documents>", "E a che ora?", session="sess-1", model="haiku", runner=run)
    cmd = run.cmd
    assert cmd[cmd.index("--resume") + 1] == "sess-1"
    assert cmd[cmd.index("--model") + 1] == "haiku"
    stdin = run.kwargs["input"]
    assert "TRANSCRIPT" not in stdin
    today, question = stdin.split("\n\n")
    assert today.startswith("Today is ") and question == "E a che ora?"


def test_unicode_round_trip():
    run = FakeRunner(stdout=ok_json(result="Sì, alle 20 🍷 [#3]"))
    assert ask("Perché? 😎", "Dov'è?", runner=run)["text"] == "Sì, alle 20 🍷 [#3]"
    assert "😎" in run.kwargs["input"]


def test_not_installed(monkeypatch):
    monkeypatch.setattr(subscription.shutil, "which", lambda name: None)
    run = FakeRunner()
    with pytest.raises(EngineError, match="not installed or not on PATH"):
        ask("t", "q", runner=run)
    assert run.calls == []


@pytest.mark.parametrize("status,result", [
    (401, "Invalid API key"),
    (403, "Forbidden"),
    (None, "Not logged in · Please run /login"),
    (None, "OAuth authentication failed"),
])
def test_not_logged_in(status, result):
    run = FakeRunner(stdout=ok_json(is_error=True, api_error_status=status, result=result), returncode=1)
    with pytest.raises(EngineError, match="not logged in"):
        ask("t", "q", runner=run)


@pytest.mark.parametrize("status,result,returncode", [
    (429, "Too many requests", 1),
    (None, "Claude AI usage limit reached|1790000000", 1),
    (None, "5-hour limit reached ∙ resets 3pm", 0),      # is_error with returncode 0
])
def test_limit_reached(status, result, returncode):
    run = FakeRunner(stdout=ok_json(is_error=True, api_error_status=status, result=result),
                     returncode=returncode)
    with pytest.raises(EngineError, match="usage limit is reached"):
        ask("t", "q", runner=run)


def test_timeout():
    run = FakeRunner(raises=subprocess.TimeoutExpired(cmd="claude", timeout=600))
    with pytest.raises(EngineError, match="took too long"):
        ask("t", "q", runner=run)


def test_other_error_from_result():
    long = "Overloaded " + "x" * 1000
    run = FakeRunner(stdout=ok_json(is_error=True, api_error_status=529, result=long), returncode=1)
    with pytest.raises(EngineError) as e:
        ask("t", "q", runner=run)
    assert str(e.value) == long[:500]


def test_other_error_non_json_stderr():
    run = FakeRunner(stdout="", stderr="Error: unknown option '--safe-mode'", returncode=1)
    with pytest.raises(EngineError, match="unknown option"):
        ask("t", "q", runner=run)


def test_non_json_login_error_is_mapped():
    run = FakeRunner(stdout="Invalid API key · Please run /login", returncode=1)
    with pytest.raises(EngineError, match="not logged in"):
        ask("t", "q", runner=run)


def test_nonzero_returncode_with_success_json_fails():
    run = FakeRunner(returncode=2, stderr="crash")
    with pytest.raises(EngineError):
        ask("t", "q", runner=run)


def test_extract_citations():
    valid = {12, 13, 40, 1234}
    assert extract_citations("Sì [#12][#13], poi [#40].", valid) == [12, 13, 40]
    assert extract_citations("[#13] e [#12] e ancora [#13][#12]", valid) == [13, 12]
    assert extract_citations("[#999] non esiste, [#1234] sì", valid) == [1234]
    assert extract_citations("nessuna citazione, #12, [12], [# 12]", valid) == []
    assert extract_citations("[#12]", []) == []
