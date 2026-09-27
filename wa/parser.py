"""WhatsApp export (.txt Android, .zip iPhone) -> list of message dicts in chronological order.

Each dict: {ts, sender, text, is_system, has_media}. Standard library only (see docs/DECISIONS.md).
"""

import re
import zipfile
from datetime import datetime
from pathlib import Path

HEADER = re.compile(
    r"^\[?(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),? "
    r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)(?:\s?(?P<ampm>[AaPp]\.?\s?[Mm]\.?))?\]?(?: -)? (?P<rest>.*)$"
)
MEDIA_PLACEHOLDERS = (
    "<media omessi>", "<media omitted>", "immagine omessa", "video omesso", "audio omesso",
    "documento omesso", "sticker omesso", "gif omessa", "image omitted", "video omitted",
    "audio omitted", "document omitted", "sticker omitted", "gif omitted", "<allegato:", "<attached:",
)
BOM, LRM = "﻿", "‎"   # LRM: iPhone puts it before system text and media placeholders
NARROW_NBSP, NBSP = " ", " "
CHAT_NAME = re.compile(r"^(?:Chat WhatsApp con|WhatsApp Chat with|WhatsApp Chat -) (.+)$")


def chat_name_from_filename(path) -> str:
    stem = Path(path).stem
    m = CHAT_NAME.match(stem)
    return m[1].strip() if m else stem


def _read_text(path: Path) -> str:
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
                if name is None:
                    raise ValueError(f"{path.name} does not contain a WhatsApp chat (.txt file).")
                return z.read(name).decode("utf-8-sig")
        return path.read_text(encoding="utf-8-sig")
    except zipfile.BadZipFile:
        raise ValueError(f"{path.name} is not a valid .zip file.")
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} is not a UTF-8 text file, so it is not a WhatsApp export.")


def _day_first(dates: list[str]) -> bool:
    for d in dates:
        a, b = (int(x) for x in re.split(r"[/.]", d)[:2])
        if a > 12:
            return True
        if b > 12:
            return False
    return True


def parse_export(path) -> list[dict]:
    path = Path(path)
    raw = []
    text = _read_text(path).replace(NARROW_NBSP, " ").replace(NBSP, " ")
    for line in text.splitlines():
        m = HEADER.match(line.lstrip(BOM + LRM))
        if m:
            raw.append({**m.groupdict(), "lines": [m["rest"]]})
        elif raw:
            raw[-1]["lines"].append(line)          # continuation of the previous message
    if not raw:
        raise ValueError(f"No WhatsApp messages found in {path.name}. Upload a chat exported "
                         "from the WhatsApp phone app (Export chat, without media).")
    day_first = _day_first([r["date"] for r in raw])
    out = []
    for r in raw:
        d1, d2, y = re.split(r"[/.]", r["date"])
        day, month = (d1, d2) if day_first else (d2, d1)
        year = int(y) + 2000 if len(y) == 2 else int(y)
        hms = [int(x) for x in re.split(r"[:.]", r["time"])] + [0]
        hour = hms[0]
        if r["ampm"]:
            hour = hour % 12 + (12 if r["ampm"][0].lower() == "p" else 0)
        try:
            ts = datetime(year, int(month), int(day), hour, hms[1], hms[2])
        except ValueError:
            raise ValueError(f"Unrecognized date {r['date']} {r['time']} in {path.name}.")
        body = "\n".join(r["lines"])
        sender, sep, msg = body.partition(": ")
        is_system = not sep                          # Android system line: no "Name: "
        if is_system:
            sender, msg = None, body
        has_media = any(p in msg.lstrip(LRM).lower() for p in MEDIA_PLACEHOLDERS)
        if sep and msg.startswith(LRM) and not has_media:   # iPhone system line
            sender, is_system = None, True
        out.append({"ts": ts.isoformat(), "sender": sender, "text": msg.replace(LRM, "").strip(),
                    "is_system": is_system, "has_media": has_media})
    return out
