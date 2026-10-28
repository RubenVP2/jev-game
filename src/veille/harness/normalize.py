"""Deterministic post-processing. Models differ in typography habits; the output must not."""

from __future__ import annotations

import re

from ..models import PostContent, threads_length

_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u00a0": " "})
_DASH = re.compile(r"\s+(?:--|–|-)\s+")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•–—]|\d+[.)])\s+")
_HASHTAG = re.compile(r"(?<!\w)#\w+")


def clean_text(text: str) -> str:
    text = text.translate(_QUOTES)
    text = _DASH.sub(" — ", text)
    text = text.replace("...", "…")
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def clean_item(text: str) -> str:
    return clean_text(_BULLET_PREFIX.sub("", text)).rstrip(".;")


def clean_heading(text: str) -> str:
    text = clean_text(text)
    return text[:-1] if text.endswith(".") and not text.endswith("…") else text


def _hashtag(tag: str) -> str:
    return "#" + re.sub(r"[^a-z0-9]", "", tag.lower().lstrip("#"))


def normalize(content: PostContent, source_url: str, discussion_url: str, brand_hashtags: list[str]) -> PostContent:
    """Same typography for every model, source links always present, TikTok hashtags in house format."""
    c = content.model_copy(deep=True)
    c.angle = clean_text(c.angle)

    c.threads.post = clean_text(_HASHTAG.sub("", c.threads.post))
    reply = clean_text(c.threads.reply)
    # The reply always carries the source: append what the model forgot, if it fits.
    missing = []
    if source_url and source_url not in reply:
        missing.append(f"Source: {source_url}")
    if discussion_url and discussion_url != source_url and discussion_url not in reply:
        missing.append(f"Discussion: {discussion_url}")
    for line in missing:
        last = reply.splitlines()[-1] if reply else ""
        sep = "\n" if last.startswith(("Source:", "Discussion:")) else "\n\n"
        candidate = f"{reply}{sep}{line}".strip()
        if threads_length(candidate) <= 500:
            reply = candidate
    c.threads.reply = reply

    c.tiktok.title = clean_heading(c.tiktok.title)[:90]
    description = clean_text(_HASHTAG.sub("", c.tiktok.description))
    topic_tags = [_hashtag(t) for t in _HASHTAG.findall(content.tiktok.description)]
    tags: list[str] = []
    for tag in topic_tags[:3] + [_hashtag(t) for t in brand_hashtags]:
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
    c.tiktok.description = f"{description}\n\n{' '.join(tags)}".strip()

    for slide in c.slides:
        slide.kicker = clean_text(slide.kicker).upper()
        slide.heading = clean_heading(slide.heading)
        slide.body = clean_text(slide.body)
        slide.label = clean_heading(slide.label)
        slide.value = slide.value.strip()
        slide.left_title = clean_heading(slide.left_title)
        slide.right_title = clean_heading(slide.right_title)
        slide.bullets = [clean_item(b) for b in slide.bullets if b.strip()]
        slide.left = [clean_item(re.sub(r"^use it if:?\s*", "", x, flags=re.I)) for x in slide.left if x.strip()]
        slide.right = [clean_item(re.sub(r"^skip it if:?\s*", "", x, flags=re.I)) for x in slide.right if x.strip()]
        slide.code = slide.code.strip("\n")
    return c
