"""GitHub Trending (HTML page, there is no official API) + README through the REST API."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..config import GithubConfig
from ..models import Item

log = logging.getLogger(__name__)

TRENDING_URL = "https://github.com/trending/{language}"
_STARS_PERIOD = re.compile(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)")


def _int(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def parse_trending(html: str) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a[href]")
        if link is None:
            continue
        full_name = link["href"].strip("/")
        if full_name.count("/") != 1:
            continue
        desc = article.select_one("p")
        lang = article.select_one('[itemprop="programmingLanguage"]')
        total = article.select_one('a[href$="/stargazers"]')
        period = _STARS_PERIOD.search(article.get_text(" ", strip=True))
        url = f"https://github.com/{full_name}"
        items.append(
            Item(
                source="github",
                native_id=full_name.lower(),
                url=url,
                discussion_url=url,
                title=full_name,
                summary=desc.get_text(" ", strip=True) if desc else "",
                author=full_name.split("/")[0],
                score=_int(period.group(1)) if period else 0,
                tags=[lang.get_text(strip=True)] if lang else [],
                extra={"total_stars": _int(total.get_text()) if total else 0},
            )
        )
    return items


async def collect(client: httpx.AsyncClient, cfg: GithubConfig) -> list[Item]:
    seen: dict[str, Item] = {}
    for language in cfg.languages:
        url = TRENDING_URL.format(language=language).rstrip("/")
        try:
            resp = await client.get(url, params={"since": cfg.since})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("github trending %r failed: %s", language or "all", exc)
            continue
        for item in parse_trending(resp.text):
            if item.score >= cfg.min_stars_today and item.id not in seen:
                seen[item.id] = item
    return list(seen.values())


async def fetch_readme(client: httpx.AsyncClient, full_name: str, token: str = "", limit: int = 15000) -> str:
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = await client.get(f"https://api.github.com/repos/{full_name}/readme", headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("README for %s unavailable: %s", full_name, exc)
        return ""
    return resp.text[:limit]


async def fetch_repo_meta(client: httpx.AsyncClient, full_name: str, token: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = await client.get(f"https://api.github.com/repos/{full_name}", headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError:
        return {}
    data = resp.json()
    return {
        k: data.get(k)
        for k in ("description", "stargazers_count", "forks_count", "license", "created_at", "pushed_at", "topics", "language")
    }
