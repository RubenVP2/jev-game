"""Consistency harness: the same story produces the same kind of post, whichever model writes it.

    dossier ──► fact sheet ──► writer ──► normalize ──► lint + grounding ──► judge ──► revise (best kept)
                (shared IR)     (style guide,           (deterministic,      (fixed rubric,
                                 exemplars,              model-agnostic)      separate model)
                                 recent hooks)

1. Fact sheet: every writer works from the same structured facts, with figures quoted verbatim.
2. Style guide: one text, used identically by the writer and the judge.
3. Exemplars: human-approved posts (golden files first, then your approved drafts) anchor the voice.
4. Normalization and lint: typography, links, hashtags, limits and banned phrases do not depend on the model.
5. Grounding: a figure absent from the dossier is sent back to the model.
6. Judge: a fixed rubric scored by a separate model; drafts under the bar are revised, the best version wins.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import LLM, LLMError
from ..models import Item, PostContent
from . import prompts
from .facts import FactSheet, clean_fact_sheet, ungrounded_figures
from .normalize import normalize
from .style import is_soft, lint

log = logging.getLogger(__name__)

EXEMPLAR_DIR = Path(__file__).with_name("exemplars")
DOSSIER_EXCERPT = 9000

WEIGHTS = {"voice": 0.2, "hook": 0.15, "mechanism": 0.15, "grounding": 0.2, "tradeoff": 0.1, "structure": 0.1, "clarity": 0.1}


class Scores(BaseModel):
    voice: int = Field(ge=0, le=10)
    hook: int = Field(ge=0, le=10)
    mechanism: int = Field(ge=0, le=10)
    grounding: int = Field(ge=0, le=10)
    tradeoff: int = Field(ge=0, le=10)
    structure: int = Field(ge=0, le=10)
    clarity: int = Field(ge=0, le=10)


class Verdict(BaseModel):
    scores: Scores
    issues: list[str] = []
    summary: str = ""

    @property
    def score(self) -> float:
        return round(sum(getattr(self.scores, k) * w for k, w in WEIGHTS.items()), 2)


@dataclass
class Report:
    """How a draft was produced, shown on Discord and stored with the draft."""

    writer: str = ""
    judge: str = ""
    score: float | None = None
    scores: dict = field(default_factory=dict)
    revisions: int = 0
    open_issues: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Composition:
    content: PostContent
    facts: FactSheet
    report: Report


def golden_exemplars() -> list[PostContent]:
    return [PostContent.model_validate(json.loads(p.read_text())) for p in sorted(EXEMPLAR_DIR.glob("*.json"))]


class Harness:
    def __init__(self, settings: Settings, llm: LLM):
        self.settings = settings
        self.llm = llm
        self.cfg = settings.app.harness

    # --- building blocks -----------------------------------------------------

    def exemplars(self, approved: list[PostContent]) -> list[PostContent]:
        """Your approved posts first (they define the voice best), topped up with the golden files."""
        n = self.cfg.exemplars
        return (approved[:n] + golden_exemplars())[:n]

    async def extract_facts(self, dossier: str) -> FactSheet:
        facts = await self.llm.complete_json(
            "facts", prompts.FACTS_SYSTEM, prompts.facts_user(dossier), FactSheet, temperature=0.1, max_tokens=6000
        )
        return clean_fact_sheet(facts, dossier)

    def _finish(self, content: PostContent, item: Item) -> PostContent:
        return normalize(content, item.url, item.discussion_url, self.settings.app.brand.tiktok_hashtags)

    def problems(self, content: PostContent, item: Item, dossier: str) -> list[str]:
        carousel = self.settings.app.carousel
        content = self._finish(content, item)
        found = lint(content, carousel.min_slides, carousel.max_slides)
        if self.cfg.enforce_grounding:
            found += ungrounded_figures(content, dossier)
        return found

    async def write(
        self,
        item: Item,
        dossier: str,
        facts: FactSheet,
        exemplars: list[PostContent],
        recent_hooks: list[str],
        angle_hint: str = "",
        instruction: str = "",
        previous: PostContent | None = None,
        issues: list[str] | None = None,
    ) -> tuple[PostContent, str]:
        brand, carousel = self.settings.app.brand, self.settings.app.carousel
        content = await self.llm.complete_json(
            "write",
            prompts.writer_system(brand.name, brand.tagline, carousel.min_slides, carousel.max_slides),
            prompts.writer_user(
                facts, dossier[:DOSSIER_EXCERPT], exemplars, recent_hooks, item.url,
                angle_hint=angle_hint, instruction=instruction, previous=previous, issues=issues,
            ),
            PostContent,
            temperature=0.5,
            max_tokens=12000,
            repairs=3,
            check=lambda c: self.problems(c, item, dossier),
            accept=lambda problems: all(is_soft(p) for p in problems),
        )
        return self._finish(content, item), self.llm.last_model

    async def judge(self, content: PostContent, facts: FactSheet, exemplars: list[PostContent], recent_hooks: list[str]) -> tuple[Verdict, str] | None:
        if not self.cfg.judge_enabled:
            return None
        brand = self.settings.app.brand
        try:
            verdict = await self.llm.complete_json(
                "judge",
                prompts.judge_system(brand.name, brand.tagline),
                prompts.judge_user(content, facts, exemplars, recent_hooks),
                Verdict,
                temperature=0.0,
                max_tokens=4000,
            )
        except LLMError as exc:
            log.warning("judge unavailable, keeping the linted draft: %s", exc)
            return None
        return verdict, self.llm.last_model

    # --- full composition ----------------------------------------------------

    async def compose(
        self,
        item: Item,
        dossier: str,
        approved: list[PostContent],
        recent_hooks: list[str],
        angle_hint: str = "",
        instruction: str = "",
        previous: PostContent | None = None,
        facts: FactSheet | None = None,
    ) -> Composition:
        facts = facts or await self.extract_facts(dossier)
        exemplars = self.exemplars(approved)
        content, writer = await self.write(
            item, dossier, facts, exemplars, recent_hooks, angle_hint=angle_hint, instruction=instruction, previous=previous
        )
        report = Report(writer=writer)
        judged = await self.judge(content, facts, exemplars, recent_hooks)
        if judged is None:
            report.open_issues = self.problems(content, item, dossier)
            return Composition(content, facts, report)

        verdict, report.judge = judged
        best, best_verdict = content, verdict
        while best_verdict.score < self.cfg.min_score and best_verdict.issues and report.revisions < self.cfg.max_revisions:
            report.revisions += 1
            log.info("judge score %.2f < %.2f, revision %d", best_verdict.score, self.cfg.min_score, report.revisions)
            try:
                candidate, writer = await self.write(
                    item, dossier, facts, exemplars, recent_hooks,
                    instruction=instruction, previous=best, issues=best_verdict.issues,
                )
            except LLMError as exc:
                log.warning("revision failed, keeping the best version so far: %s", exc)
                break
            judged = await self.judge(candidate, facts, exemplars, recent_hooks)
            if judged is None:
                best, report.writer = candidate, writer
                break
            if judged[0].score >= best_verdict.score:
                best, best_verdict, report.writer = candidate, judged[0], writer

        report.score = best_verdict.score
        report.scores = best_verdict.scores.model_dump()
        report.summary = best_verdict.summary
        report.open_issues = best_verdict.issues if best_verdict.score < self.cfg.min_score else []
        report.open_issues += self.problems(best, item, dossier)
        return Composition(best, facts, report)

    async def fit_slides(self, composition: Composition, item: Item, dossier: str, overflows: list[str], recent_hooks: list[str]) -> PostContent:
        """Rendered slides overflowed their frame: one targeted revision, slide text only."""
        issues = overflows + ["Only shorten the slides listed above; keep everything else identical."]
        content, _ = await self.write(
            item, dossier, composition.facts, self.exemplars([]), recent_hooks,
            previous=composition.content, issues=issues,
        )
        return content
