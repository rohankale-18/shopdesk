"""Grounding check: numbers in a reply that nothing the model was given contains.

The system prompt says to only state numbers that came from tools. This checks it after the
fact, so a made-up figure stands out in the trace instead of slipping by.

It is a heuristic: a flagged number is worth a look, not proof of a mistake (it may be a
figure the model worked out, or a date written in a way we don't recognise). Rounding is
allowed: a tool's 17.9 reported as "18%" counts as found.
"""

import re

_ISO_DATE = re.compile(r"\b(\d{4})-\d{2}-\d{2}\b")
# "Nov 6", "September 30th", "Oct 26 – 31": dates in the reply, not figures.
_MONTH_DAY = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"(?:\s*[–-]\s*\d{1,2}\b)?",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _value(text: str) -> float:
    return float(text.replace(",", ""))


def _source_numbers(texts: list[str]) -> set[float]:
    """Every number in what the model was given. From dates, only the year counts."""
    found: set[float] = set()
    for text in texts:
        found |= {float(y) for y in _ISO_DATE.findall(text)}
        found |= {_value(n) for n in _NUMBER.findall(_ISO_DATE.sub(" ", text))}
    return found


def _is_found(x: float, known: set[float]) -> bool:
    return any(x in (y, round(y), round(y, 1), round(y, 2)) for y in known)


def unsupported_numbers(reply: str, sources: list[str]) -> list[str]:
    """Numbers in `reply` (as written there) not found in any of `sources`, in order, no repeats."""
    text = _LIST_MARKER.sub(" ", _MONTH_DAY.sub(" ", _ISO_DATE.sub(" ", reply)))
    known = _source_numbers(sources)
    flagged: list[str] = []
    for n in _NUMBER.findall(text):
        if not _is_found(_value(n), known) and n not in flagged:
            flagged.append(n)
    return flagged
