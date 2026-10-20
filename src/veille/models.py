"""Domain objects shared across the pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator

_TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_src$|source$|fbclid$|gclid$)")


def canonical_url(url: str) -> str:
    """Normalise a URL so that the same story found on several sources collapses to one key."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/") or "/"
    if host == "github.com":
        # github.com/owner/repo/anything -> github.com/owner/repo
        segments = [s for s in path.split("/") if s]
        path = "/" + "/".join(segments[:2]).lower() if len(segments) >= 2 else path.lower()
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    return urlunsplit(("https", host, path, query, ""))


@dataclass
class Item:
    """A candidate story collected from a source."""

    source: str  # github | hackernews | reddit
    native_id: str
    url: str  # what the story is about (article, repository)
    discussion_url: str  # where people talk about it
    title: str
    summary: str = ""
    author: str = ""
    score: int = 0  # stars today, HN points, Reddit upvotes
    comments: int = 0
    tags: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.native_id}"

    @property
    def canonical(self) -> str:
        return canonical_url(self.url)


class DraftStatus(StrEnum):
    PENDING = "pending"  # waiting for validation on Discord
    APPROVED = "approved"  # validated, waiting for its slot
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


# --- LLM output schema -------------------------------------------------------

THREADS_LIMIT = 500


def threads_length(text: str) -> int:
    """Threads counts the text limit in UTF-8 bytes for non-ASCII characters (emojis cost more)."""
    return len(text.encode("utf-8"))


class Slide(BaseModel):
    kind: str = Field(description="cover | points | mechanism | code | stat | compare | verdict")
    kicker: str = ""
    heading: str = ""
    body: str = ""
    bullets: list[str] = []
    code: str = ""
    value: str = ""
    label: str = ""
    left_title: str = ""
    left: list[str] = []
    right_title: str = ""
    right: list[str] = []

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        kinds = {"cover", "points", "mechanism", "code", "stat", "compare", "verdict"}
        if v not in kinds:
            raise ValueError(f"unknown slide kind {v!r}, expected one of {sorted(kinds)}")
        return v


class ThreadsCopy(BaseModel):
    post: str
    reply: str

    @field_validator("post", "reply")
    @classmethod
    def _fits(cls, v: str) -> str:
        if threads_length(v) > THREADS_LIMIT:
            raise ValueError(f"{threads_length(v)} bytes, Threads allows {THREADS_LIMIT}: shorten it")
        return v.strip()


class TikTokCopy(BaseModel):
    title: str
    description: str

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if len(v) > 90:
            raise ValueError(f"title is {len(v)} chars, TikTok allows 90")
        return v.strip()

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        if len(v) > 2200:
            raise ValueError(f"description is {len(v)} chars, keep it under 2200")
        return v.strip()


class PostContent(BaseModel):
    angle: str
    threads: ThreadsCopy
    tiktok: TikTokCopy
    slides: list[Slide]

    @model_validator(mode="after")
    def _structure(self) -> PostContent:
        if not self.slides or self.slides[0].kind != "cover":
            raise ValueError("the first slide must be of kind 'cover'")
        if self.slides[-1].kind != "verdict":
            raise ValueError("the last slide must be of kind 'verdict'")
        return self
