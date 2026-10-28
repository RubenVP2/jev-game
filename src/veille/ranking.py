"""Merge duplicates across sources, drop covered topics, score, then let an LLM do the editorial triage."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from .llm import LLM, LLMError
from .models import Item
from .prompts import TRIAGE_SYSTEM, triage_user

log = logging.getLogger(__name__)

SOURCE_PRIORITY = {"hackernews": 0, "reddit": 1, "github": 2}


@dataclass
class Candidate:
    item: Item
    related: list[Item] = field(default_factory=list)
    heuristic: float = 0.0
    editorial: float | None = None
    angle: str = ""

    @property
    def score(self) -> float:
        if self.editorial is None:
            return self.heuristic
        return 0.65 * self.editorial + 0.35 * self.heuristic

    @property
    def sources(self) -> set[str]:
        return {self.item.source, *(r.source for r in self.related)}


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", title.lower()).strip()


def similar_titles(a: str, b: str, threshold: float = 0.82) -> bool:
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio() >= threshold


def merge(items: list[Item]) -> list[Candidate]:
    """Group items pointing at the same canonical URL. The discussion-rich source becomes the primary."""
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.canonical, []).append(item)
    candidates = []
    for group in groups.values():
        group.sort(key=lambda i: (SOURCE_PRIORITY.get(i.source, 9), -i.score))
        candidates.append(Candidate(item=group[0], related=group[1:]))
    return candidates


def _signal(item: Item) -> float:
    if item.source == "github":
        return math.log1p(item.score) / math.log1p(2500)
    if item.source == "hackernews":
        return 0.75 * math.log1p(item.score) / math.log1p(1500) + 0.25 * math.log1p(item.comments) / math.log1p(800)
    if item.source == "reddit":
        return 0.75 * math.log1p(item.score) / math.log1p(6000) + 0.25 * math.log1p(item.comments) / math.log1p(1000)
    return 0.0


def heuristic_score(candidate: Candidate, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    best = max(_signal(i) for i in [candidate.item, *candidate.related])
    cross_source = 0.15 * (len(candidate.sources) - 1)
    published = candidate.item.published_at
    freshness = 1.0
    if published is not None:
        age_h = max(0.0, (now - published).total_seconds() / 3600)
        freshness = 0.5 ** (age_h / 36)  # half-life of 36 hours
    return min(1.0, (best + cross_source) * (0.6 + 0.4 * freshness))


def drop_covered(candidates: list[Candidate], covered: list[tuple[str, str]], rejected_ids: set[str]) -> list[Candidate]:
    covered_urls = {url for url, _ in covered}
    kept = []
    for c in candidates:
        ids = {c.item.id, *(r.id for r in c.related)}
        if ids & rejected_ids or c.item.canonical in covered_urls:
            continue
        if any(similar_titles(c.item.title, title) for _, title in covered):
            continue
        kept.append(c)
    return kept


class TriageEntry(BaseModel):
    index: int
    technical_depth: int = Field(ge=0, le=10)
    novelty: int = Field(ge=0, le=10)
    audience_fit: int = Field(ge=0, le=10)
    angle: str = ""


class Triage(BaseModel):
    ranking: list[TriageEntry]


async def editorial_triage(llm: LLM, candidates: list[Candidate]) -> None:
    """Score each candidate in place. Falls back silently to the heuristic score if every provider fails."""
    if not candidates:
        return
    try:
        triage = await llm.complete_json("triage", TRIAGE_SYSTEM, triage_user(candidates), Triage, temperature=0.2)
    except LLMError as exc:
        log.error("editorial triage unavailable, using heuristic ranking only: %s", exc)
        return
    for entry in triage.ranking:
        if 0 <= entry.index < len(candidates):
            c = candidates[entry.index]
            c.editorial = (0.4 * entry.technical_depth + 0.25 * entry.novelty + 0.35 * entry.audience_fit) / 10
            c.angle = entry.angle
    for c in candidates:
        if c.editorial is None:  # not returned by the model: considered off-topic
            c.editorial = 0.0


async def rank(
    llm: LLM | None,
    items: list[Item],
    covered: list[tuple[str, str]],
    rejected_ids: set[str],
    shortlist_size: int,
) -> list[Candidate]:
    candidates = drop_covered(merge(items), covered, rejected_ids)
    for c in candidates:
        c.heuristic = heuristic_score(c)
    candidates.sort(key=lambda c: c.heuristic, reverse=True)
    shortlist = candidates[:shortlist_size]
    if llm is not None:
        await editorial_triage(llm, shortlist)
    shortlist.sort(key=lambda c: c.score, reverse=True)
    return shortlist
