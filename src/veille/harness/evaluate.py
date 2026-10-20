"""`veille eval`: run the same dossier through each writer model and compare them on the harness metrics.

The fact sheet is extracted once and shared, exactly as in production, so differences come from the
writer only. Use it to pick the models of the `write` chain and to tune `llm.profiles`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import ModelChoice, Settings
from ..llm import LLM
from ..models import Item
from . import Harness
from .facts import ungrounded_figures
from .style import lint

SAMPLE_DOSSIER = Path(__file__).parent / "eval" / "sample-dossier.txt"


@dataclass
class EvalRow:
    model: str
    seconds: float
    score: float | None = None
    revisions: int = 0
    residual: int = 0  # lint + grounding problems left in the final copy (should be 0)
    hook: str = ""
    error: str = ""


def item_from_dossier(dossier: str) -> Item:
    fields = dict(line.split(": ", 1) for line in dossier.splitlines()[:8] if ": " in line)
    url = fields.get("URL", "https://example.com")
    return Item(source=fields.get("SOURCE", "hackernews"), native_id="eval", url=url,
                discussion_url=fields.get("DISCUSSION", url), title=fields.get("TITLE", "eval"))


async def evaluate(settings: Settings, dossier: str, models: list[ModelChoice], out_dir: Path) -> list[EvalRow]:
    out_dir.mkdir(parents=True, exist_ok=True)
    item = item_from_dossier(dossier)
    base = Harness(settings, LLM(settings))
    facts = await base.extract_facts(dossier)
    (out_dir / "facts.json").write_text(facts.model_dump_json(indent=2))

    rows = []
    for choice in models:
        label = f"{choice.provider}/{choice.model}"
        scoped = settings.model_copy(deep=True)
        scoped.app.llm.tasks["write"] = [choice]
        harness = Harness(scoped, LLM(scoped))
        start = time.monotonic()
        try:
            comp = await harness.compose(item, dossier, [], [], facts=facts)
        except Exception as exc:  # noqa: BLE001 - one failing model must not stop the comparison
            rows.append(EvalRow(label, time.monotonic() - start, error=str(exc)[:200]))
            continue
        carousel = settings.app.carousel
        residual = lint(comp.content, carousel.min_slides, carousel.max_slides) + ungrounded_figures(comp.content, dossier)
        rows.append(EvalRow(
            label, time.monotonic() - start, comp.report.score, comp.report.revisions, len(residual),
            comp.content.threads.post.splitlines()[0] if comp.content.threads.post else "",
        ))
        safe = label.replace("/", "_")
        (out_dir / f"{safe}.json").write_text(json.dumps(
            {"report": comp.report.as_dict(), "residual": residual, "content": comp.content.model_dump()}, indent=2
        ))
    return rows


def format_table(rows: list[EvalRow]) -> str:
    lines = [f"{'model':45} {'score':>6} {'rev':>4} {'left':>5} {'time':>6}  first line"]
    for r in rows:
        if r.error:
            lines.append(f"{r.model:45} {'error':>6}  {r.error}")
            continue
        score = f"{r.score:.1f}" if r.score is not None else "-"
        lines.append(f"{r.model:45} {score:>6} {r.revisions:>4} {r.residual:>5} {r.seconds:>5.0f}s  {r.hook[:70]}")
    return "\n".join(lines)
