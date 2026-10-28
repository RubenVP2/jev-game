"""Collection from every enabled source, and the research dossier the writer works from."""

from __future__ import annotations

import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..models import Item, canonical_url
from . import github, hackernews, reddit

log = logging.getLogger(__name__)

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def extract_article(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = [el.get_text(" ", strip=True) for el in root.find_all(["h1", "h2", "h3", "p", "li", "pre", "blockquote"])]
    text = "\n".join(b for b in blocks if len(b) > 30 or b.startswith(("#", "$")))
    return text[:limit]


class Sources:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=True, headers={"User-Agent": BROWSER_UA}
        )
        self.reddit = reddit.RedditClient(self.client, settings.secrets)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def collect(self) -> list[Item]:
        cfg = self.settings.app.sources
        tasks = []
        if cfg.github.enabled:
            tasks.append(github.collect(self.client, cfg.github))
        if cfg.hackernews.enabled:
            tasks.append(hackernews.collect(self.client, cfg.hackernews))
        if cfg.reddit.enabled:
            tasks.append(reddit.collect(self.reddit, cfg.reddit))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: list[Item] = []
        for result in results:
            if isinstance(result, BaseException):
                log.error("source failed: %r", result)
            else:
                items.extend(result)
        log.info("collected %d items", len(items))
        return items

    async def fetch_article(self, url: str) -> str:
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("article %s unavailable: %s", url, exc)
            return ""
        if "html" not in resp.headers.get("content-type", ""):
            return ""
        return extract_article(resp.text)

    async def dossier(self, item: Item, related: list[Item] | None = None) -> str:
        """Everything the writer is allowed to use. Facts outside this text must not appear in the post."""
        token = self.settings.secrets.github_token
        parts = [
            f"SOURCE: {item.source}",
            f"TITLE: {item.title}",
            f"URL: {item.url}",
            f"DISCUSSION: {item.discussion_url}",
            f"SIGNAL: score={item.score} comments={item.comments} tags={', '.join(item.tags)}",
        ]
        if item.summary:
            parts.append(f"SUMMARY:\n{item.summary}")

        repo = github_repo(item.url)
        comments: list[str] = []
        if repo:
            meta, readme = await asyncio.gather(
                github.fetch_repo_meta(self.client, repo, token), github.fetch_readme(self.client, repo, token)
            )
            if meta:
                parts.append(f"REPOSITORY METADATA: {meta}")
            if readme:
                parts.append(f"README:\n{readme}")
        elif item.url != item.discussion_url:
            article = await self.fetch_article(item.url)
            if article:
                parts.append(f"ARTICLE TEXT:\n{article}")

        for source_item in [item, *(related or [])]:
            if source_item.source == "hackernews":
                comments += await hackernews.fetch_top_comments(self.client, source_item.native_id)
            elif source_item.source == "reddit":
                comments += await reddit.fetch_top_comments(self.reddit, source_item)
        if comments:
            parts.append("PRACTITIONER COMMENTS (opinions, not facts):\n" + "\n---\n".join(comments[:12]))
        return "\n\n".join(parts)


def github_repo(url: str) -> str | None:
    canon = canonical_url(url)
    prefix = "https://github.com/"
    if canon.startswith(prefix):
        path = canon[len(prefix):]
        if path.count("/") == 1:
            return path
    return None
