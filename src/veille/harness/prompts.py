"""Prompts of the harness. All of them embed the same style guide, worded identically for every model."""

from __future__ import annotations

import json

from ..models import PostContent
from .facts import FactSheet
from .style import SLIDE_SPECS, style_guide

FACTS_SYSTEM = """You are a meticulous technical researcher. Read the DOSSIER and extract a fact sheet that a
writer will use without seeing anything else. Precision matters more than coverage.

Rules:
- Only facts stated in the dossier. If something is unclear or missing, say so in "unknowns".
- "figures": every number worth citing (benchmarks, sizes, counts, versions, dates), each with a VERBATIM
  quote copied character for character from the dossier that contains the number. No computed numbers.
- "critiques": objections or caveats raised in the practitioner comments, with who raised them.
  Comments are opinions, never facts about the subject.
- "code_example": a short usage snippet copied verbatim from the dossier (README, article), or "".
- "mechanism": 3-5 short steps explaining how it actually works.
- "topic": 1-3 words in capitals for a cover kicker, e.g. "DATABASES", "LLM INFERENCE", "SUPPLY CHAIN".

Return JSON only:
{"subject": "", "topic": "", "what_it_is": "", "mechanism": [""], "whats_new": "",
 "figures": [{"value": "", "meaning": "", "quote": ""}], "tradeoffs": [""],
 "critiques": [{"point": "", "attribution": ""}], "code_example": "", "audience": "",
 "use_if": [""], "skip_if": [""], "unknowns": ""}"""


def facts_user(dossier: str) -> str:
    return f"DOSSIER:\n{dossier}"


OUTPUT_SCHEMA = """OUTPUT: one JSON object, nothing else.
{{
  "angle": "one sentence: the precise technical point of this brief",
  "threads": {{
    "post": "<= 450 characters. Line 1: the claim. Then 2-4 short lines: mechanism, the figure that matters, the trade-off. No link, no hashtag.",
    "reply": "<= 450 characters. One extra technical detail or the main caveat, then 'Source: <url>'."
  }},
  "tiktok": {{
    "title": "<= 80 characters, plain and specific",
    "description": "2-4 sentences summarising the brief, then 2-3 lowercase topic hashtags"
  }},
  "slides": [ ...{min_slides} to {max_slides} slides... ]
}}

SLIDE KINDS (text limits are strict, slides have a fixed size):
{slide_specs}"""


def writer_system(brand: str, tagline: str, min_slides: int, max_slides: int) -> str:
    schema = OUTPUT_SCHEMA.format(min_slides=min_slides, max_slides=max_slides, slide_specs="\n".join(f"- {s}" for s in SLIDE_SPECS))
    return (
        "You are the writer of the brief described below. Follow the style guide exactly: several writers "
        "work on this publication and readers must not be able to tell them apart.\n\n"
        f"{style_guide(brand, tagline)}\n\n"
        "FACTS: use only the FACT SHEET (and the dossier excerpt for exact wording and code). "
        "Every figure must be one of the fact sheet figures, written the same way.\n\n"
        f"{schema}"
    )


def exemplar_block(exemplars: list[PostContent]) -> str:
    if not exemplars:
        return ""
    parts = []
    for n, ex in enumerate(exemplars, 1):
        slides = [s.model_dump(exclude_defaults=True) for s in ex.slides]
        parts.append(
            f"EXAMPLE {n}\nThreads post:\n{ex.threads.post}\n\nThreads reply:\n{ex.threads.reply}\n\n"
            f"Slides:\n{json.dumps(slides, ensure_ascii=False)}"
        )
    return (
        "STYLE REFERENCES: published briefs of this publication. Match their voice, density, rhythm and "
        "structure. Their subjects and facts are unrelated to today's story: never reuse them.\n\n"
        + "\n\n---\n\n".join(parts)
    )


def recent_hooks_block(hooks: list[str]) -> str:
    if not hooks:
        return ""
    return "RECENT OPENING LINES (do not reuse their structure):\n" + "\n".join(f"- {h}" for h in hooks)


def writer_user(
    facts: FactSheet,
    dossier_excerpt: str,
    exemplars: list[PostContent],
    recent_hooks: list[str],
    source_url: str,
    angle_hint: str = "",
    instruction: str = "",
    previous: PostContent | None = None,
    issues: list[str] | None = None,
) -> str:
    parts = [exemplar_block(exemplars), recent_hooks_block(recent_hooks)]
    parts.append(f"FACT SHEET:\n{facts.model_dump_json(indent=2)}")
    parts.append(f"SOURCE URL (for the reply): {source_url}")
    if angle_hint:
        parts.append(f"EDITOR'S SUGGESTED ANGLE (keep it unless the fact sheet supports a sharper one): {angle_hint}")
    if previous is not None:
        parts.append(f"PREVIOUS VERSION:\n{previous.model_dump_json(indent=2)}")
        if issues:
            parts.append("EDITOR'S REVIEW, fix every point and keep what works:\n" + "\n".join(f"- {i}" for i in issues))
    if instruction:
        parts.append(f"EDITOR'S INSTRUCTION FOR THIS VERSION (follow it): {instruction}")
    parts.append(f"DOSSIER EXCERPT (reference only):\n{dossier_excerpt}")
    return "\n\n".join(p for p in parts if p)


JUDGE_SYSTEM = """You are the managing editor of the publication described below. Several writers (different
AI models) produce its briefs. Your job is to keep them indistinguishable: same voice, same standards.

{style}

Review the DRAFT against the style guide, the FACT SHEET and the STYLE REFERENCES. Score each criterion
from 0 to 10, strictly: 8 means publishable as is, 10 is rare.
- voice: matches the style references and the voice rules (density, tone, no filler, no hype)
- hook: line 1 is a specific claim that makes an engineer stop; not reused from recent opening lines
- mechanism: explains how it works, correctly, in plain technical terms
- grounding: every claim and figure is supported by the fact sheet; opinions are attributed
- tradeoff: the limitation is stated honestly and the verdict is useful
- structure: slides progress logically, each adds one idea, no repetition with the Threads post
- clarity: an engineer outside this niche understands it on first read

"issues": concrete, actionable edits, each naming the field, e.g. "threads.post line 2: replace 'very fast'
with the 3.2x figure". Empty if nothing should change. No praise.

Return JSON only:
{{"scores": {{"voice": 0, "hook": 0, "mechanism": 0, "grounding": 0, "tradeoff": 0, "structure": 0, "clarity": 0}},
  "issues": [""], "summary": "one sentence"}}"""


def judge_system(brand: str, tagline: str) -> str:
    return JUDGE_SYSTEM.format(style=style_guide(brand, tagline))


def judge_user(draft: PostContent, facts: FactSheet, exemplars: list[PostContent], recent_hooks: list[str]) -> str:
    parts = [
        exemplar_block(exemplars),
        recent_hooks_block(recent_hooks),
        f"FACT SHEET:\n{facts.model_dump_json(indent=2)}",
        f"DRAFT:\n{draft.model_dump_json(indent=2)}",
    ]
    return "\n\n".join(p for p in parts if p)
