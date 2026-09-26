"""One tiny real `claude -p` call with the subscription login. Prints the raw JSON."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_DIR = Path(tempfile.gettempdir()) / "whatsapp-ask-runtime"   # outside the project


def main() -> int:
    exe = shutil.which("claude")
    if not exe:
        print("Claude Code is not installed or not on PATH.", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)   # otherwise Claude Code bills the paid API, not the subscription
    env.pop("CLAUDECODE", None)          # set when running inside a Claude Code session
    RUNTIME_DIR.mkdir(exist_ok=True)
    cmd = [exe, "-p", "--output-format", "json", "--model", "sonnet", "--tools", "", "--safe-mode"]
    out = subprocess.run(cmd, input="Reply only: ok", capture_output=True, text=True,
                         encoding="utf-8", cwd=RUNTIME_DIR, env=env, timeout=120)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        print(f"returncode {out.returncode}\nstdout: {out.stdout}\nstderr: {out.stderr}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if out.returncode == 0 and not data.get("is_error") else 1


if __name__ == "__main__":
    sys.exit(main())
