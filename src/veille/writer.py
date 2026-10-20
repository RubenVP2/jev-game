"""Turn a research dossier into the Threads copy, the TikTok copy and the carousel slides."""

from __future__ import annotations

import re

from .config import Settings
from .llm import LLM
from .models import PostContent
from .prompts import BANNED, writer_system, writer_user

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")

# (field, max chars) per slide kind, mirroring the prompt. Overflow breaks the fixed-size layout.
SLIDE_LIMITS = {
    "kicker": 28, "heading": 60, "body": 140, "value": 8, "label": 60, "left_title": 18, "right_title": 18,
}
ITEM_LIMIT = 95
CODE_LINES, CODE_COLS = 12, 60


def editorial_problems(content: PostContent, min_slides: int, max_slides: int) -> list[str]:
    """Rules the schema cannot express. Each problem is sent back to the model to fix."""
    problems = []
    if not min_slides <= len(content.slides) <= max_slides:
        problems.append(f"use between {min_slides} and {max_slides} slides, not {len(content.slides)}")

    texts = {"threads.post": content.threads.post, "threads.reply": content.threads.reply,
             "tiktok.title": content.tiktok.title}
    for n, slide in enumerate(content.slides, 1):
        for field, limit in SLIDE_LIMITS.items():
            value = getattr(slide, field)
            if len(value) > limit:
                problems.append(f"slide {n} ({slide.kind}): {field} is {len(value)} chars, max {limit}")
            texts[f"slide {n} {field}"] = value
        for field in ("bullets", "left", "right"):
            for item in getattr(slide, field):
                if len(item) > ITEM_LIMIT:
                    problems.append(f"slide {n} ({slide.kind}): a {field} item is {len(item)} chars, max {ITEM_LIMIT}")
                texts[f"slide {n} {field}"] = item
        lines = slide.code.splitlines()
        if len(lines) > CODE_LINES or any(len(line) > CODE_COLS for line in lines):
            problems.append(f"slide {n}: code must fit {CODE_LINES} lines of {CODE_COLS} chars")

    for where, text in texts.items():
        lowered = text.lower()
        for phrase in BANNED:
            if phrase in lowered:
                problems.append(f"{where}: banned phrase {phrase!r}")
        if where != "tiktok.title" and _EMOJI.search(text):
            problems.append(f"{where}: no emojis")
        if "!" in text and not where.startswith("slide"):
            problems.append(f"{where}: no exclamation marks")
    if "#" in content.threads.post:
        problems.append("threads.post: no hashtags on Threads")
    return problems


class Writer:
    def __init__(self, settings: Settings, llm: LLM):
        self.settings = settings
        self.llm = llm

    async def write(self, dossier: str, angle_hint: str = "", instruction: str = "", previous: PostContent | None = None) -> PostContent:
        brand, carousel = self.settings.app.brand, self.settings.app.carousel
        system = writer_system(brand.name, brand.tagline, carousel.min_slides, carousel.max_slides)
        user = writer_user(
            dossier,
            angle_hint=angle_hint,
            instruction=instruction,
            previous=previous.model_dump_json(indent=2) if previous else "",
        )
        return await self.llm.complete_json(
            "write",
            system,
            user,
            PostContent,
            temperature=0.6,
            max_tokens=6000,
            check=lambda c: editorial_problems(c, carousel.min_slides, carousel.max_slides),
        )
