"""House style: the single source of truth shared by the writer prompt, the judge prompt and the linter.

Different models reason and write differently. Keeping the rules in one place, stated the same way
to every model and enforced by the same deterministic checks, is what keeps the voice stable.
"""

from __future__ import annotations

import re

from ..models import PostContent

VOICE_RULES = [
    "Write like a staff engineer's internal memo: precise, declarative, dense. Short sentences.",
    "Concrete nouns and verbs. No adjective unless the dossier backs it with evidence.",
    "Explain the mechanism: how it works, not only what it is.",
    "Always state the trade-off or limitation. Practitioner comments are opinions: attribute them "
    "(\"HN commenters point out...\", \"one maintainer notes...\").",
    "End with a verdict that says when to use it and when to skip it.",
    "English only, present tense, active voice. Sentence case for headings.",
    "No emojis, no exclamation marks, no rhetorical questions, no hashtags on Threads.",
    "No first person (I, we, our) and no addressing the reader as \"you guys\". \"You\" is fine for the verdict.",
    "Numbers as digits with units (12 ms, 3.2x, 41%). Every figure comes from the dossier, never computed or estimated.",
]

HOOK_RULES = [
    "Line 1 of the Threads post is a specific, falsifiable claim about the subject, with its name in it.",
    "No question, no 'This is huge', no 'Here's why', no countdown, no teaser that withholds the point.",
    "Do not reuse the opening structure of the recent posts listed in the prompt.",
]

BANNED = [
    "game-changer", "game changer", "revolutionary", "revolutionize", "groundbreaking", "unlock", "unleash",
    "supercharge", "next-level", "mind-blowing", "insane", "dive in", "deep dive", "delve", "landscape",
    "in today's fast-paced", "excited to", "here's why", "let that sink in", "the future of", "leverage",
    "seamless", "cutting-edge", "a must", "you need to", "10x developer", "hidden gem", "buckle up", "thread 🧵",
    "it's worth noting", "in conclusion", "whether you're", "look no further", "elevate", "empower", "robust",
    "harness the power", "paradigm shift", "stay tuned", "what do you think", "thoughts?", "blazing fast",
]

HEDGES = ["arguably", "basically", "essentially", "very ", "really ", "quite ", "literally", "just "]

# Strict layout limits: slides are rendered at a fixed size.
SLIDE_FIELD_LIMITS = {
    "kicker": 28, "heading": 60, "body": 140, "value": 8, "label": 60, "left_title": 18, "right_title": 18,
}
SLIDE_ITEM_LIMIT = 95
CODE_LINES, CODE_COLS = 12, 64  # beyond ~48 columns the renderer shrinks the code font
# (field, min, max) item counts per slide kind, mirroring SLIDE_SPECS.
ITEM_COUNTS = {
    "points": [("bullets", 2, 4)],
    "mechanism": [("bullets", 3, 5)],
    "compare": [("left", 2, 4), ("right", 2, 4)],
    "verdict": [("left", 1, 2), ("right", 1, 2)],
}
THREADS_TARGET = 450  # the hard limit is 500; keep margin for manual edits
MAX_SENTENCE_WORDS = 32

# Style problems are sent back for a fix like the others, but cannot sink a draft: if they remain
# after the last repair, the draft is kept and they are listed on Discord as open issues.
SOFT = "[style] "


def is_soft(problem: str) -> bool:
    return problem.startswith(SOFT)

SLIDE_SPECS = [
    '{"kind": "cover", "kicker": "<= 28 chars: SOURCE / TOPIC, e.g. \'GITHUB / RUST\'", "heading": "<= 60 chars, the claim", "body": "<= 110 chars, what it is in one line"}',
    '{"kind": "points", "heading": "<= 40 chars", "bullets": ["2-4 bullets, each <= 90 chars"]}',
    '{"kind": "mechanism", "heading": "<= 40 chars, e.g. \'How it works\'", "bullets": ["3-5 ordered steps, each <= 80 chars"]}',
    '{"kind": "code", "heading": "<= 40 chars", "code": "<= 12 lines, <= 56 chars per line, copied from the dossier (re-wrap longer lines)", "body": "<= 90 chars caption"}',
    '{"kind": "stat", "value": "<= 8 chars, e.g. \'3.2x\' or \'-41%\'", "label": "<= 60 chars, what was measured", "body": "<= 120 chars, conditions and caveat"}',
    '{"kind": "compare", "heading": "<= 40 chars", "left_title": "<= 18 chars", "left": ["2-4 items <= 40 chars"], "right_title": "<= 18 chars", "right": ["2-4 items <= 40 chars"]}',
    '{"kind": "verdict", "heading": "<= 40 chars", "body": "<= 140 chars, the bottom line", "left": ["1-2 \'use it if\' items <= 60 chars"], "right": ["1-2 \'skip it if\' items <= 60 chars"]}',
]

STRUCTURE_RULES = [
    "Slide 1 is 'cover', the last slide is 'verdict'. Middle slides follow the story: mechanism before numbers, "
    "numbers before trade-offs. Use 'stat' only for a figure quoted in the fact sheet, 'code' only for code "
    "present in the dossier.",
    "Slides do not repeat each other or the Threads post word for word; each slide adds one idea.",
    "Bullets have no trailing period and no leading dash or number.",
]


def style_guide(brand: str, tagline: str) -> str:
    def section(title: str, rules: list[str]) -> str:
        return f"{title}\n" + "\n".join(f"- {r}" for r in rules)

    return "\n\n".join([
        f'"{brand}" is a daily technical brief for senior engineers on Threads and TikTok. Tagline: "{tagline}". '
        "It must not read like the usual tech influencer post.",
        section("VOICE", VOICE_RULES),
        section("HOOK", HOOK_RULES),
        section("STRUCTURE", STRUCTURE_RULES),
        "BANNED PHRASES: " + ", ".join(f'"{b}"' for b in BANNED),
    ])


# --- deterministic checks ----------------------------------------------------

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF]")
# "I" must not match "I/O" or "I-frame"; lowercase "us" must not match "US".
_FIRST_PERSON = re.compile(r"\b(?:[Ww]e|[Ww]e're|[Ww]e've|[Oo]ur|us)\b|(?<![\w/-])I(?:'m|'ve)?(?![\w/-])")
_SENTENCE = re.compile(r"[^.!?\n]+")


def prose_fields(content: PostContent) -> dict[str, str]:
    """Every human-readable text of a post, keyed by a path the model can understand. Code is excluded."""
    fields = {
        "threads.post": content.threads.post,
        "threads.reply": content.threads.reply,
        "tiktok.title": content.tiktok.title,
        "tiktok.description": content.tiktok.description,
    }
    for n, slide in enumerate(content.slides, 1):
        for name in ("kicker", "heading", "body", "value", "label", "left_title", "right_title"):
            if getattr(slide, name):
                fields[f"slide {n} ({slide.kind}).{name}"] = getattr(slide, name)
        for name in ("bullets", "left", "right"):
            for i, item in enumerate(getattr(slide, name), 1):
                fields[f"slide {n} ({slide.kind}).{name}[{i}]"] = item
        if slide.kind == "code" and slide.body:
            fields[f"slide {n} (code).body"] = slide.body
    return fields


def lint(content: PostContent, min_slides: int, max_slides: int) -> list[str]:
    """Rules the schema cannot express. Each problem is phrased so the model can fix it."""
    problems = []
    if not min_slides <= len(content.slides) <= max_slides:
        problems.append(f"use between {min_slides} and {max_slides} slides, not {len(content.slides)}")
    kinds = [s.kind for s in content.slides]
    for kind in set(kinds) - {"points"}:
        if kinds.count(kind) > 1:
            problems.append(f"only one '{kind}' slide is allowed")

    for n, slide in enumerate(content.slides, 1):
        where = f"slide {n} ({slide.kind})"
        for name, limit in SLIDE_FIELD_LIMITS.items():
            value = getattr(slide, name)
            if len(value) > limit:
                problems.append(f"{where}.{name} is {len(value)} chars, max {limit}: shorten it")
        for name in ("bullets", "left", "right"):
            for item in getattr(slide, name):
                if len(item) > SLIDE_ITEM_LIMIT:
                    problems.append(f"{where}.{name} item is {len(item)} chars, max {SLIDE_ITEM_LIMIT}: \"{item[:40]}...\"")
        lines = slide.code.splitlines()
        if len(lines) > CODE_LINES or any(len(line) > CODE_COLS for line in lines):
            problems.append(f"{where}.code must fit {CODE_LINES} lines of {CODE_COLS} chars")
        required = {
            "cover": ["heading"], "points": ["heading", "bullets"], "mechanism": ["heading", "bullets"],
            "code": ["code"], "stat": ["value", "label"], "compare": ["left", "right"], "verdict": ["body", "left", "right"],
        }[slide.kind]
        for name in required:
            if not getattr(slide, name):
                problems.append(f"{where}.{name} is required for this slide kind")
        for name, low, high in ITEM_COUNTS.get(slide.kind, []):
            count = len(getattr(slide, name))
            if count and not low <= count <= high:
                problems.append(f"{where}.{name} has {count} items, use {low} to {high}")

    for where, text in prose_fields(content).items():
        lowered = text.lower()
        for phrase in BANNED:
            if phrase in lowered:
                problems.append(f"{where}: banned phrase {phrase!r}")
        if _EMOJI.search(text):
            problems.append(f"{where}: remove emojis")
        if "!" in text:
            problems.append(f"{where}: remove exclamation marks")
        if _FIRST_PERSON.search(text):
            problems.append(f"{SOFT}{where}: no first person ({_FIRST_PERSON.search(text).group(0)!r})")
        for sentence in _SENTENCE.findall(text):
            if len(sentence.split()) > MAX_SENTENCE_WORDS and not where.startswith("tiktok"):
                problems.append(f"{SOFT}{where}: split the sentence starting \"{sentence.strip()[:40]}...\" (max {MAX_SENTENCE_WORDS} words)")

    post = content.threads.post
    first_line = post.strip().splitlines()[0] if post.strip() else ""
    if "#" in post:
        problems.append("threads.post: no hashtags on Threads")
    if "?" in first_line:
        problems.append("threads.post: line 1 must be a claim, not a question")
    if "http" in post:
        problems.append("threads.post: no link in the main post, links go in the reply")
    if len(post) > THREADS_TARGET:
        problems.append(f"{SOFT}threads.post is {len(post)} chars, keep it under {THREADS_TARGET}")
    hedges = [h.strip() for h in HEDGES if h in f" {post.lower()} "]
    if len(hedges) > 1:
        problems.append(f"{SOFT}threads.post: cut filler words {hedges}")
    return problems
