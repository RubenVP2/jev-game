"""Reddit through the OAuth API (application-only token from a "script" app)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from ..config import RedditConfig, Secrets
from ..models import Item

log = logging.getLogger(__name__)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
PUBLIC = "https://www.reddit.com"


class RedditClient:
    def __init__(self, client: httpx.AsyncClient, secrets: Secrets):
        self.client = client
        self.secrets = secrets
        self._token: str = ""
        self._expires: float = 0

    @property
    def has_credentials(self) -> bool:
        return bool(self.secrets.reddit_client_id and self.secrets.reddit_client_secret)

    async def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.secrets.reddit_user_agent}
        if not self.has_credentials:
            return headers
        if time.time() >= self._expires:
            resp = await self.client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.secrets.reddit_client_id, self.secrets.reddit_client_secret),
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._expires = time.time() + int(data.get("expires_in", 3600)) - 60
        headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get(self, path: str, **params) -> dict | list:
        # Without credentials, fall back to the public JSON endpoints (stricter rate limits).
        base, suffix = (API, "") if self.has_credentials else (PUBLIC, ".json")
        resp = await self.client.get(f"{base}{path}{suffix}", params=params, headers=await self._headers())
        resp.raise_for_status()
        return resp.json()


def parse_listing(listing: dict, min_score: int) -> list[Item]:
    items = []
    for child in listing.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied") or post.get("over_18") or post.get("score", 0) < min_score:
            continue
        discussion = f"https://www.reddit.com{post['permalink']}"
        url = discussion if post.get("is_self") else post.get("url_overridden_by_dest") or post.get("url") or discussion
        items.append(
            Item(
                source="reddit",
                native_id=post["id"],
                url=url,
                discussion_url=discussion,
                title=post.get("title", ""),
                summary=(post.get("selftext") or "")[:1500],
                author=post.get("author") or "",
                score=int(post.get("score") or 0),
                comments=int(post.get("num_comments") or 0),
                tags=[f"r/{post.get('subreddit')}"] + ([post["link_flair_text"]] if post.get("link_flair_text") else []),
                published_at=datetime.fromtimestamp(post["created_utc"], UTC) if post.get("created_utc") else None,
                extra={"subreddit": post.get("subreddit")},
            )
        )
    return items


async def collect(reddit: RedditClient, cfg: RedditConfig) -> list[Item]:
    items: list[Item] = []
    for sub in cfg.subreddits:
        try:
            listing = await reddit.get(f"/r/{sub}/top", t=cfg.period, limit=25)
        except httpx.HTTPError as exc:
            log.warning("reddit r/%s failed: %s", sub, exc)
            continue
        items.extend(parse_listing(listing, cfg.min_score))
    return items


async def fetch_top_comments(reddit: RedditClient, item: Item, limit: int = 8) -> list[str]:
    try:
        data = await reddit.get(f"/r/{item.extra.get('subreddit')}/comments/{item.native_id}", sort="top", limit=limit, depth=1)
    except httpx.HTTPError as exc:
        log.warning("reddit comments for %s unavailable: %s", item.id, exc)
        return []
    if not isinstance(data, list) or len(data) < 2:
        return []
    comments = [c.get("data", {}) for c in data[1].get("data", {}).get("children", []) if c.get("kind") == "t1"]
    return [c["body"][:1200] for c in comments if c.get("body") and not c.get("stickied")][:limit]
