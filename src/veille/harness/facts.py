"""Fact sheet: a model-independent intermediate representation between the dossier and the copy.

Every writer model receives the same structured facts, so the substance of a post does not depend on
which model read the raw dossier. Figures carry a verbatim quote, checked against the dossier.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from ..models import PostContent
from .style import prose_fields

log = logging.getLogger(__name__)


class Figure(BaseModel):
    value: str  # "3.2x", "41%", "12 ms"
    meaning: str  # what was measured, under which conditions
    quote: str  # verbatim excerpt of the dossier containing the figure


class Critique(BaseModel):
    point: str
    attribution: str  # "HN commenter", "r/rust thread", "the README itself"


class FactSheet(BaseModel):
    subject: str  # the thing, by its name
    topic: str  # 1-3 words for the cover kicker, e.g. "DATABASES", "INFERENCE", "SECURITY"
    what_it_is: str
    mechanism: list[str]
    whats_new: str
    figures: list[Figure] = []
    tradeoffs: list[str] = []
    critiques: list[Critique] = []
    code_example: str = ""  # verbatim from the dossier, or empty
    audience: str = ""
    use_if: list[str] = []
    skip_if: list[str] = []
    unknowns: str = ""  # what the dossier does not say


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def clean_fact_sheet(facts: FactSheet, dossier: str) -> FactSheet:
    """Drop figures whose quote is not in the dossier, and code that was not copied from it."""
    haystack = _squash(dossier)
    kept = []
    for figure in facts.figures:
        quote = _squash(figure.quote)
        digits = numbers_in(figure.value)
        if quote and quote in haystack and digits <= numbers_in(figure.quote):
            kept.append(figure)
        else:
            log.info("dropping ungrounded figure %r", figure.value)
    code_ok = not facts.code_example or all(
        _squash(line) in haystack for line in facts.code_example.splitlines() if line.strip()
    )
    return facts.model_copy(update={"figures": kept, "code_example": facts.code_example if code_ok else ""})


# --- figure grounding --------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?")


def _normalize(token: str) -> str:
    token = token.lstrip("+-$").replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def numbers_in(text: str) -> set[str]:
    return {_normalize(m.group(0)) for m in _NUMBER.finditer(text)}


_SCALED = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?([kKmMbB])\b")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}


def _scaled_matches(text: str, number: str, allowed: set[str]) -> bool:
    """'4.1k' is grounded if the dossier says 4,100 (or anything within 5%)."""
    values = []
    for value in allowed:
        try:
            values.append(float(value))
        except ValueError:
            continue
    for m in _SCALED.finditer(text):
        if _normalize(m.group(1)) != number:
            continue
        expanded = float(number) * _SCALE[m.group(2).lower()]
        if any(abs(v - expanded) <= 0.05 * expanded for v in values):
            return True
    return False


def ungrounded_figures(content: PostContent, dossier: str) -> list[str]:
    """Figures in the copy that do not appear in the dossier. Single digits (step counts, '2 caveats') are exempt."""
    allowed = numbers_in(dossier)
    problems = []
    for where, text in prose_fields(content).items():
        for number in sorted(numbers_in(text) - allowed):
            if len(number.replace(".", "")) <= 1 or _scaled_matches(text, number, allowed):
                continue
            problems.append(
                f"{where}: the figure {number!r} is not in the dossier. Use only figures quoted in the fact sheet, "
                "never computed or rounded ones"
            )
    return problems
