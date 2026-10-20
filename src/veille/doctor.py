"""`veille doctor`: check every setting, key and connection, and say exactly what to fix."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from .config import ModelChoice, Settings
from .db import Database
from .llm import LLM
from .models import PostContent
from .publishers.tiktok import TOKEN_NAME as TIKTOK_TOKEN

OK, WARN, FAIL = "ok", "warn", "fail"
SYMBOL = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    area: str
    status: str
    message: str


class Doctor:
    def __init__(self, settings: Settings, live: bool = True):
        self.settings = settings
        self.secrets = settings.secrets
        self.live = live
        self.checks: list[Check] = []

    def add(self, area: str, status: str, message: str) -> None:
        self.checks.append(Check(area, status, message))

    async def run(self) -> list[Check]:
        self.check_config()
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            await asyncio.gather(
                self.check_llm(),
                self.check_sources(client),
                self.check_discord(client),
                self.check_threads(client),
                self.check_public_url(client),
            )
        self.check_tiktok()
        await self.check_render()
        order = ["config", "llm", "discord", "media", "threads", "tiktok", "sources", "render"]
        self.checks.sort(key=lambda c: order.index(c.area) if c.area in order else len(order))
        return self.checks

    # --- checks --------------------------------------------------------------

    def check_config(self) -> None:
        app = self.settings.app
        self.add("config", OK, f"slots {', '.join(app.schedule.slots)} ({app.timezone}), brand {app.brand.name!r}")
        if app.brand.handle in ("", "@yourhandle"):
            self.add("config", WARN, "brand.handle is still the placeholder: set your handle in config.yaml")

    async def check_llm(self) -> None:
        providers = [p for p in self.settings.app.llm.providers if self.settings.api_key(p)]
        if not providers:
            self.add("llm", FAIL, "no API key: set GOOGLE_AI_API_KEY, OPENROUTER_API_KEY or ORCAROUTER_API_KEY")
            return
        self.add("llm", OK, f"keys found for: {', '.join(providers)}")
        llm = LLM(self.settings)
        for task in ("triage", "facts", "write", "judge"):
            try:
                chain = llm.chain(task)
                self.add("llm", OK, f"{task}: " + " -> ".join(f"{c.provider}/{c.model}" for c in chain))
            except Exception as exc:  # noqa: BLE001
                self.add("llm", FAIL, f"{task}: {exc}")
        if not self.live:
            return
        unique: dict[str, ModelChoice] = {}
        for task in ("triage", "facts", "write", "judge"):
            for choice in self.settings.app.llm.tasks.get(task, []):
                if self.settings.api_key(choice.provider):
                    unique[f"{choice.provider}/{choice.model}"] = choice
        results = await asyncio.gather(*(self._ping(llm, c) for c in unique.values()))
        for label, (status, message) in zip(unique, results, strict=True):
            self.add("llm", status, f"{label}: {message}")

    async def _ping(self, llm: LLM, choice: ModelChoice) -> tuple[str, str]:
        start = time.monotonic()
        try:
            completion = await llm.call(
                choice, [{"role": "user", "content": 'Reply with the JSON {"ok": true} and nothing else.'}],
                temperature=0, max_tokens=400, json_output=True,
            )
        except Exception as exc:  # noqa: BLE001
            return FAIL, f"unreachable or unknown model ({str(exc)[:160]}). Fix the model id in config.yaml"
        return OK, f"answers in {time.monotonic() - start:.1f}s ({completion.text[:30]!r})"

    async def check_sources(self, client: httpx.AsyncClient) -> None:
        if not self.live:
            return
        from .sources import BROWSER_UA
        from .sources.github import parse_trending

        try:
            resp = await client.get("https://github.com/trending", headers={"User-Agent": BROWSER_UA})
            n = len(parse_trending(resp.text)) if resp.status_code == 200 else 0
            self.add("sources", OK if n else WARN, f"GitHub Trending: {n} repositories parsed (HTTP {resp.status_code})")
        except httpx.HTTPError as exc:
            self.add("sources", WARN, f"GitHub Trending unreachable: {exc}")
        try:
            resp = await client.get("https://hn.algolia.com/api/v1/search", params={"tags": "front_page"})
            self.add("sources", OK if resp.status_code == 200 else WARN, f"Hacker News: HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            self.add("sources", WARN, f"Hacker News unreachable: {exc}")
        if not (self.secrets.reddit_client_id and self.secrets.reddit_client_secret):
            self.add("sources", WARN, "Reddit: no REDDIT_CLIENT_ID/SECRET, public endpoints are often blocked")
            return
        try:
            resp = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self.secrets.reddit_client_id, self.secrets.reddit_client_secret),
                headers={"User-Agent": self.secrets.reddit_user_agent},
            )
            ok = resp.status_code == 200 and "access_token" in resp.text
            self.add("sources", OK if ok else FAIL, f"Reddit OAuth: HTTP {resp.status_code}" + ("" if ok else " (check the app credentials)"))
        except httpx.HTTPError as exc:
            self.add("sources", WARN, f"Reddit unreachable: {exc}")

    async def check_discord(self, client: httpx.AsyncClient) -> None:
        if not self.secrets.discord_bot_token:
            self.add("discord", FAIL, "DISCORD_BOT_TOKEN is missing")
            return
        if not self.secrets.channel_id:
            self.add("discord", FAIL, "DISCORD_CHANNEL_ID is missing")
        if not self.secrets.allowed_user_ids:
            self.add("discord", FAIL, "DISCORD_ALLOWED_USER_IDS is missing: nobody could approve drafts")
        if not self.live:
            return
        headers = {"Authorization": f"Bot {self.secrets.discord_bot_token}"}
        resp = await client.get("https://discord.com/api/v10/users/@me", headers=headers)
        if resp.status_code != 200:
            self.add("discord", FAIL, f"bot token rejected (HTTP {resp.status_code})")
            return
        self.add("discord", OK, f"bot {resp.json().get('username')!r}")
        if self.secrets.channel_id:
            resp = await client.get(f"https://discord.com/api/v10/channels/{self.secrets.channel_id}", headers=headers)
            if resp.status_code == 200:
                self.add("discord", OK, f"channel #{resp.json().get('name')}")
            else:
                self.add("discord", FAIL, f"channel not accessible (HTTP {resp.status_code}): invite the bot and check the ID")

    async def check_threads(self, client: httpx.AsyncClient) -> None:
        if not self.settings.app.publish.threads.enabled:
            self.add("threads", OK, "disabled in config.yaml")
            return
        db = Database(self.settings.db_path)
        stored = db.get_token("threads")
        token = stored["access_token"] if stored else self.secrets.threads_access_token
        if not token:
            self.add("threads", WARN, "THREADS_ACCESS_TOKEN missing: drafts will skip Threads")
            return
        if not self.live:
            return
        resp = await client.get("https://graph.threads.net/v1.0/me", params={"fields": "id,username", "access_token": token})
        if resp.status_code == 200:
            self.add("threads", OK, f"connected as @{resp.json().get('username')}")
        else:
            self.add("threads", FAIL, f"token rejected (HTTP {resp.status_code}): generate a new long-lived token")

    def check_tiktok(self) -> None:
        cfg = self.settings.app.publish.tiktok
        if not cfg.enabled:
            self.add("tiktok", OK, "disabled in config.yaml")
            return
        if not (self.secrets.tiktok_client_key and self.secrets.tiktok_client_secret):
            self.add("tiktok", WARN, "TIKTOK_CLIENT_KEY/SECRET missing: drafts will skip TikTok")
            return
        token = Database(self.settings.db_path).get_token(TIKTOK_TOKEN)
        if not token:
            self.add("tiktok", WARN, "not connected yet: run `veille tiktok-auth` while the server runs")
            return
        refresh_left = (token.get("refresh_expires_at", 0) - time.time()) / 86400
        self.add("tiktok", OK if refresh_left > 14 else WARN, f"connected, mode {cfg.mode}, refresh token valid {refresh_left:.0f} more days")

    async def check_public_url(self, client: httpx.AsyncClient) -> None:
        base = self.secrets.public_base_url.rstrip("/")
        if not base or "example.com" in base:
            self.add("media", FAIL, "DOMAIN is not set (or still example.com): Threads and TikTok download the slides from it")
            return
        if not base.startswith("https://"):
            self.add("media", WARN, "PUBLIC_BASE_URL should be HTTPS")
        if not self.live:
            return
        try:
            resp = await client.get(f"{base}/healthz")
            status = OK if resp.status_code == 200 else WARN
            self.add("media", status, f"{base}/healthz: HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            self.add("media", WARN, f"{base} unreachable ({exc.__class__.__name__}); normal if the server is not running yet")

    async def check_render(self) -> None:
        from .carousel import render

        sample = Path(render.__file__).with_name("sample.json")
        content = PostContent.model_validate(json.loads(sample.read_text()))
        content.slides = content.slides[:1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = await render.render_slides(self.settings, content, Path(tmp), 1, datetime.now(), None)
            self.add("render", OK, f"Chromium renders slides ({len(result.paths)} test slide)")
        except Exception as exc:  # noqa: BLE001
            self.add("render", FAIL, f"slide rendering failed: {exc}. Run `playwright install --with-deps chromium`")


def format_report(checks: list[Check]) -> str:
    width = max(len(c.area) for c in checks)
    lines = [f" {SYMBOL[c.status]} {c.area.ljust(width)}  {c.message}" for c in checks]
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    lines.append("")
    lines.append("Ready." if not fails else f"{fails} blocking problem(s)" + (f", {warns} warning(s)" if warns else "") + ".")
    return "\n".join(lines)
