"""End to end through real HTTP: an OpenAI-compatible fake server answers triage, facts, writer and judge."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web

from conftest import requires_chromium
from test_harness import DOSSIER, FACTS, GOOD_POST, post
from veille.models import DraftStatus, Item
from veille.pipeline import Pipeline

pytestmark = requires_chromium


def answer_for(system: str) -> str:
    if "editor of a technical briefing" in system:
        return json.dumps({"ranking": [{"index": 0, "technical_depth": 9, "novelty": 8, "audience_fit": 9, "angle": "per-key compaction"}]})
    if "meticulous technical researcher" in system:
        return json.dumps(FACTS)
    if "managing editor" in system:
        scores = dict.fromkeys(["voice", "hook", "mechanism", "grounding", "tradeoff", "structure", "clarity"], 9)
        return json.dumps({"scores": scores, "issues": [], "summary": "ready"})
    return json.dumps(post(GOOD_POST))


@pytest.fixture
async def fake_provider():
    requests = []

    async def completions(request: web.Request) -> web.Response:
        body = await request.json()
        requests.append(body)
        content = answer_for(body["messages"][0]["content"])
        return web.json_response({
            "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        })

    app = web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/v1", requests
    await runner.cleanup()


async def test_draft_end_to_end(settings, db, fake_provider, monkeypatch):
    base_url, requests = fake_provider
    for provider in settings.app.llm.providers.values():
        provider.base_url = base_url
    pipeline = Pipeline(settings, db)
    item = Item(source="hackernews", native_id="1", url="https://github.com/example/ledgerline",
                discussion_url="https://news.ycombinator.com/item?id=1", title="Ledgerline", score=612, comments=184,
                published_at=datetime.now(UTC) - timedelta(hours=2))

    async def collect():
        db.upsert_items([item])
        return [item]

    async def dossier(*args, **kwargs):
        return DOSSIER

    monkeypatch.setattr(pipeline, "collect", collect)
    monkeypatch.setattr(pipeline.sources, "dossier", dossier)

    draft_id = await pipeline.create_draft(pipeline.next_slot())
    draft = db.get_draft(draft_id)

    assert draft["status"] == DraftStatus.PENDING
    assert draft["meta"]["writer"] == "first/m1"
    assert draft["meta"]["score"] == 9.0
    assert "Source: https://github.com/example/ledgerline" in draft["content"]["threads"]["reply"]
    paths = pipeline.media_paths(draft)
    assert len(paths) == 5 and all(p.exists() for p in paths)
    folder = pipeline.draft_folder(draft)
    assert (folder / "facts.json").exists() and (folder / "dossier.txt").exists()
    systems = [r["messages"][0]["content"] for r in requests]
    assert sum("You are the writer" in s for s in systems) == 1
    await pipeline.aclose()
