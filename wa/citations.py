"""Extract [#id] citations from answers."""

import re

CITATION = re.compile(r"\[#(\d+)\]")


def extract_citations(text: str, valid_ids) -> list[int]:
    """IDs cited in text, in order of first appearance, keeping only those in valid_ids."""
    valid = set(valid_ids)
    return list(dict.fromkeys(i for i in map(int, CITATION.findall(text)) if i in valid))
