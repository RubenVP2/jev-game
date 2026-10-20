"""Hacker News through the Algolia search API (one request, points and comments included)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from ..config import HackerNewsConfig
from ..models import Item

log = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"


def parse_hits(hits: list[dict]) -> list[Item]:
    items = []
    for hit in hits:
        story_id = hit.get("objectID")
        title = hit.get("title")
        if not story_id or not title:
            continue
        discussion = f"https://news.ycombinator.com/item?id={story_id}"
        text = hit.get("story_text") or ""
        items.append(
            Item(
                source="hackernews",
                native_id=str(story_id),
                url=hit.get("url") or discussion,
                discussion_url=discussion,
                title=title,
                summary=BeautifulSoup(text, "html.parser").get_text(" ", strip=True)[:1000] if text else "",
                author=hit.get("author") or "",
                score=int(hit.get("points") or 0),
                comments=int(hit.get("num_comments") or 0),
                published_at=datetime.fromtimestamp(hit["created_at_i"], UTC) if hit.get("created_at_i") else None,
            )
        )
    return items


async def collect(client: httpx.AsyncClient, cfg: HackerNewsConfig) -> list[Item]:
    since = int(time.time()) - cfg.lookback_hours * 3600
    params = {
        "tags": "story",
        "numericFilters": f"points>={cfg.min_points},created_at_i>={since}",
        "hitsPerPage": 60,
    }
    try:
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("hacker news failed: %s", exc)
        return []
    return parse_hits(resp.json().get("hits", []))


def _descendants(node: dict) -> int:
    return sum(1 + _descendants(c) for c in node.get("children") or [])


async def fetch_top_comments(client: httpx.AsyncClient, story_id: str, limit: int = 8) -> list[str]:
    """Top-level comments that sparked the most discussion: where the expert pushback usually is."""
    try:
        resp = await client.get(ITEM_URL.format(id=story_id))
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("HN comments for %s unavailable: %s", story_id, exc)
        return []
    children = [c for c in resp.json().get("children") or [] if c.get("text")]
    children.sort(key=_descendants, reverse=True)
    return [BeautifulSoup(c["text"], "html.parser").get_text(" ", strip=True)[:1200] for c in children[:limit]]
