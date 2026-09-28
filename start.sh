#!/bin/sh
# Linux/macOS: run ./start.sh to start WhatsApp Ask. It opens in your browser. Press Ctrl+C to stop it.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "The .venv folder is missing. In this folder, run once:"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi
exec .venv/bin/python -m streamlit run app.py
