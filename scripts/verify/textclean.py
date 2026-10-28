"""Text hygiene for anything that came from a PR. Stdlib only (the label job imports it)."""
from __future__ import annotations

import unicodedata

ZWSP = "​"


def has_surrogate(text: str) -> bool:
    return any("\ud800" <= ch <= "\udfff" for ch in text)


def _drop(ch: str, keep_newlines: bool) -> bool:
    if keep_newlines and ch in "\n\t":
        return False
    return unicodedata.category(ch)[0] == "C"  # control, format (bidi overrides), surrogate, private, unassigned


def clean_line(text: str) -> str:
    """One line: every run of whitespace / control / format characters (\\r, \\u2028, bidi
    overrides, lone surrogates ...) becomes one space."""
    out, space = [], False
    for ch in str(text):
        if ch.isspace() or _drop(ch, False):
            if not space:
                out.append(" ")
            space = True
        else:
            out.append(ch)
            space = False
    return "".join(out).strip()


def clean_block(text: str) -> str:
    """Markdown: control / format characters and lone surrogates removed, newlines and tabs
    kept, \\r dropped."""
    return "".join(ch for ch in str(text) if not _drop(ch, True))


def neutralise_mentions(text: str) -> str:
    return text.replace("@", "@" + ZWSP)


def cap(text: str, limit: int, note: str = "…truncated") -> str:
    """text unchanged when it fits; else cut at a line boundary so the result is <= limit."""
    if len(text) <= limit:
        return text
    room = max(limit - len(note) - 1, 0)
    cut = text[:room]
    nl = cut.rfind("\n")
    if nl > 0:
        cut = cut[:nl]
    return f"{cut}\n{note}"[:limit]


def safe_markdown(text: str, limit: int) -> str:
    """What may be posted: cleaned, mentions neutralised (this can only grow the text), THEN
    capped, so the escaped text never exceeds `limit`."""
    return cap(neutralise_mentions(clean_block(text)), limit)
