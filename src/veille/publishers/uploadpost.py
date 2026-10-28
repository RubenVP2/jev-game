"""Upload-Post (upload-post.com): one API key publishes the carousel on Threads and TikTok.

Upload-Post holds audited Meta and TikTok apps: no developer app, no domain, no DNS verification
and no public media URL on our side (slides are uploaded as files). The Threads and TikTok accounts
are connected once in the Upload-Post dashboard.
API reference: https://docs.upload-post.com/api/reference/ (POST /upload_photos, GET /uploadposts/status).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from ..config import Settings
from ..db import Database
from ..models import PostContent

log = logging.getLogger(__name__)

API = "https://api.upload-post.com/api"
PROFILE_CACHE = "uploadpost_profile"


class UploadPostError(RuntimeError):
    pass


class UploadPostPublisher:
    def __init__(self, settings: Settings, db: Database, client: httpx.AsyncClient):
        self.settings = settings
        self.db = db
        self.client = client

    @property
    def configured(self) -> bool:
        return bool(self.settings.secrets.uploadpost_api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Apikey {self.settings.secrets.uploadpost_api_key}"}

    async def _get(self, path: str, **params) -> dict:
        resp = await self.client.get(f"{API}{path}", params=params, headers=self._headers, timeout=60)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise UploadPostError(f"{path}: HTTP {resp.status_code} {data.get('message') or data.get('error') or ''}".strip())
        return data

    async def profile(self, refresh: bool = False) -> dict:
        """The Upload-Post profile used to post (UPLOADPOST_USER, or the only/first profile of the account)."""
        cached = self.db.get_token(PROFILE_CACHE)
        if cached and not refresh and time.time() - cached.get("fetched", 0) < 6 * 3600:
            return cached["profile"]
        profiles = (await self._get("/uploadposts/users")).get("profiles", [])
        if not profiles:
            raise UploadPostError("no profile in the Upload-Post account: create one in the dashboard")
        wanted = self.settings.secrets.uploadpost_user
        profile = next((p for p in profiles if p.get("username") == wanted), None) if wanted else profiles[0]
        if profile is None:
            raise UploadPostError(f"UPLOADPOST_USER {wanted!r} not found, profiles: {[p.get('username') for p in profiles]}")
        self.db.set_token(PROFILE_CACHE, {"profile": profile, "fetched": time.time()})
        return profile

    @staticmethod
    def accounts(profile: dict) -> dict[str, dict]:
        """Connected social accounts of a profile, keyed by platform (empty or string entries ignored)."""
        return {k: v for k, v in (profile.get("social_accounts") or {}).items() if isinstance(v, dict) and v}

    def threads_handle(self) -> str:
        cached = self.db.get_token(PROFILE_CACHE) or {}
        account = self.accounts(cached.get("profile", {})).get("threads", {})
        handle = account.get("handle") or account.get("username") or ""
        return handle if not handle or handle.startswith("@") else f"@{handle}"

    def tiktok_mode(self) -> str:
        mode = self.settings.app.publish.tiktok.mode
        # Upload-Post's TikTok app is audited: direct posts are public, so "auto" publishes directly.
        return "DIRECT_POST" if mode == "auto" else mode

    async def publish(self, content: PostContent, images: list[Path], platforms: list[str]) -> dict[str, dict]:
        """Publish on `platforms` in one call. Returns {platform: result}; a failed platform has an "error" key."""
        profile = await self.profile()
        cfg = self.settings.app.publish
        data: dict[str, str | list[str]] = {
            "user": profile["username"],
            "platform[]": platforms,
            "title": content.threads.post,
        }
        if "threads" in platforms:
            data["threads_title"] = content.threads.post
            if content.threads.reply:
                data["threads_first_comment"] = content.threads.reply
        if "tiktok" in platforms:
            data |= {
                "tiktok_title": content.tiktok.title[:90],
                "tiktok_description": content.tiktok.description,
                "post_mode": self.tiktok_mode(),
                "privacy_level": cfg.tiktok.privacy_level,
                "auto_add_music": "true",
                "photo_cover_index": "0",
            }
        files = [("photos[]", (p.name, p.read_bytes(), "image/jpeg")) for p in images[:20]]
        resp = await self.client.post(f"{API}/upload_photos", data=data, files=files, headers=self._headers, timeout=600)
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or payload.get("success") is False and "results" not in payload:
            raise UploadPostError(f"upload_photos: HTTP {resp.status_code} {payload.get('message') or payload.get('error') or ''}".strip())
        if "request_id" in payload and "results" not in payload:
            return await self._wait(payload["request_id"], platforms)
        return self._normalize(payload.get("results") or {}, platforms)

    def _normalize(self, results: dict, platforms: list[str]) -> dict[str, dict]:
        out = {}
        for platform in platforms:
            result = results.get(platform)
            if result is None:
                out[platform] = {"error": "no result returned for this platform"}
            elif result.get("success") is False or result.get("error"):
                out[platform] = {"error": result.get("error") or result.get("message") or "failed"}
            else:
                out[platform] = {k: v for k, v in result.items() if k in ("url", "post_id", "publish_id")} | {"via": "upload-post"}
                if platform == "tiktok":
                    out[platform]["mode"] = self.tiktok_mode()
        return out

    async def _wait(self, request_id: str, platforms: list[str], timeout: float = 600) -> dict[str, dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = await self._get("/uploadposts/status", request_id=request_id)
            if data.get("status") == "completed":
                results = {r.get("platform"): r for r in data.get("results") or []}
                return self._normalize(results, platforms)
            await asyncio.sleep(5)
        return {p: {"error": f"still processing after {timeout:.0f}s (request {request_id})"} for p in platforms}
