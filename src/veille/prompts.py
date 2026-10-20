"""Story selection prompt. Writing prompts live in the consistency harness (veille.harness.prompts)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ranking import Candidate


TRIAGE_SYSTEM = """You are the editor of a technical briefing read by senior software engineers, SREs,
security engineers and ML engineers. You pick stories with real engineering substance.

Score every candidate from 0 to 10 on:
- technical_depth: is there a mechanism, an architecture, a benchmark, a postmortem, code to read?
- novelty: is it new information or a new technique, not a rerun of a known debate?
- audience_fit: would a staff engineer forward it to their team?

Score low (0-3): drama, layoffs, career advice, politics, legal fights, product marketing, funding news,
"AI will replace X" opinion pieces, memes, beginner tutorials, listicles, awesome-lists, rants.
Score high: new tools with a clear design, performance work with numbers, incident write-ups, security
disclosures with technical detail, research with code, deep explanations of systems.

For each candidate also give `angle`: one sentence naming the precise technical point the brief should make.

Return JSON only:
{"ranking": [{"index": 0, "technical_depth": 7, "novelty": 6, "audience_fit": 8, "angle": "..."}]}
Include every candidate index exactly once."""


def triage_user(candidates: list[Candidate]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        item = c.item
        sources = ", ".join(sorted(c.sources))
        summary = item.summary.replace("\n", " ")[:300]
        lines.append(f"[{i}] ({sources}; score {item.score}; {item.comments} comments) {item.title}\n    {item.url}\n    {summary}")
    return "Candidates:\n\n" + "\n\n".join(lines)
