"""One tiny paid call to the Anthropic API with the key in .env. Prints the answer and `usage`."""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

MODEL = "claude-sonnet-5"


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set: copy .env.example to .env and paste your key.", file=sys.stderr)
        return 1
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(model=MODEL, max_tokens=1000,
                                         messages=[{"role": "user", "content": "hi"}])
    except anthropic.AnthropicError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("answer:", "".join(b.text for b in message.content if b.type == "text"))
    print("model:", message.model, "| stop_reason:", message.stop_reason)
    print("usage:", message.usage.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
