import csv
import io

from wa.export import conversation_to_md, file_stem, to_csv, to_md, to_txt


def msg(id, chat, ts, sender, text, is_system=0):
    return {"id": id, "chat_name": chat, "ts": ts, "sender": sender, "text": text, "is_system": is_system}


MESSAGES = [   # out of order on purpose: files group by chat, then sort by time
    msg(30, "Marco", "2026-09-02T08:40:00", "Marco", "Gli ho scritto:\n\"Gentile sig. Bianchi\""),
    msg(5, "Calcetto", "2026-09-03T22:47:15", "Luca", "+39 333 1234567"),
    msg(27, "Marco", "2026-09-01T09:33:00", "Marco", "L'affitto passa da 650 a 720 euro"),
    msg(2, "Calcetto", "2026-09-01T18:00:00", None, "Luca ha creato il gruppo", is_system=1),
    msg(28, "Marco", "2026-09-01T09:34:00", "Giulia", "<Media omessi>"),
]


def test_csv_opens_in_excel_and_keeps_full_text():
    data = to_csv(MESSAGES)
    assert data.startswith("﻿chat;date;time;sender;text;id\r\n")
    rows = list(csv.reader(io.StringIO(data.removeprefix("﻿"), newline=""), delimiter=";"))
    assert rows[1:] == [
        ["Calcetto", "01/09/2026", "18:00", "(system)", "Luca ha creato il gruppo", "2"],
        ["Calcetto", "03/09/2026", "22:47", "Luca", "'+39 333 1234567", "5"],   # not a formula in Excel
        ["Marco", "01/09/2026", "09:33", "Marco", "L'affitto passa da 650 a 720 euro", "27"],
        ["Marco", "01/09/2026", "09:34", "Giulia", "<Media omessi>", "28"],
        ["Marco", "02/09/2026", "08:40", "Marco", "Gli ho scritto:\n\"Gentile sig. Bianchi\"", "30"],
    ]


def test_csv_neutralises_formulas():
    rows = list(csv.reader(io.StringIO(to_csv([msg(1, "C", "2026-09-01T10:00:00", "A", t) for t in
                                               ("=HYPERLINK(\"x\")", "-5 gradi", "@all", "ok = fine")])
                                       .removeprefix("﻿")), delimiter=";"))
    assert [r[4] for r in rows[1:]] == ["'=HYPERLINK(\"x\")", "'-5 gradi", "'@all", "ok = fine"]


def test_txt_looks_like_a_whatsapp_export():
    assert to_txt(MESSAGES) == (
        "=== Calcetto ===\n"
        "01/09/26, 18:00 - Luca ha creato il gruppo\n"
        "03/09/26, 22:47 - Luca: +39 333 1234567\n"
        "\n"
        "=== Marco ===\n"
        "01/09/26, 09:33 - Marco: L'affitto passa da 650 a 720 euro\n"
        "01/09/26, 09:34 - Giulia: <Media omessi>\n"
        "02/09/26, 08:40 - Marco: Gli ho scritto:\n\"Gentile sig. Bianchi\"\n"
    )


def test_markdown_shows_text_literally():
    data = to_md(MESSAGES + [msg(40, "Marco", "2026-09-26T23:59:00", "Anna", "")], "Messages containing “a”")
    assert data.startswith("# Messages containing “a”\n\n## Calcetto\n\n- `#2` **01/09/2026 18:00** · (system): ")
    assert "\n\n## Marco\n\n- `#27` **01/09/2026 09:33** · Marco: L'affitto passa da 650 a 720 euro\n" in data
    assert "Giulia: \\<Media omessi\\>\n" in data                       # not an HTML tag
    assert "Marco: Gli ho scritto:  \n  \"Gentile sig. Bianchi\"\n" in data   # line break inside the list item
    assert "Anna: _(no text in the export)_\n" in data


def test_conversation_markdown():
    history = [{"role": "user", "text": "Quanto è l'affitto?"},
               {"role": "assistant", "text": "720 euro [#27].", "cited": [27]},
               {"role": "user", "text": "E poi?"},
               {"role": "assistant", "error": "Your plan's usage limit is reached."}]
    looked_up = []
    data = conversation_to_md(history, "Chats: Marco", lambda ids: looked_up.append(ids) or MESSAGES[2:3])
    assert looked_up == [[27]]
    assert data == (
        "# WhatsApp Ask conversation\n\nChats: Marco\n\n---\n\n"
        "### Question\n\nQuanto è l'affitto?\n\n---\n\n"
        "### Answer\n\n720 euro [#27].\n\n**Cited messages**\n\n#### Marco\n\n"
        "- `#27` **01/09/2026 09:33** · Marco: L'affitto passa da 650 a 720 euro\n\n---\n\n"
        "### Question\n\nE poi?\n\n---\n\n"
        "### Answer\n\n_Error: Your plan's usage limit is reached._\n"
    )


def test_file_stem():
    assert file_stem("Quanto è l'affitto?") == "quanto-è-l-affitto"
    assert file_stem("a/b\\c:d*e") == "a-b-c-d-e"
    assert file_stem("???") == "messages"
    assert len(file_stem("x" * 100)) == 40
