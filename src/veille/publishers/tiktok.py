"""TikTok Content Posting API: photo carousels pulled from our public media URLs.

Until the TikTok app passes the audit, DIRECT_POST content is private. MEDIA_UPLOAD sends the
carousel to the creator's TikTok inbox as a draft, to finish (music, publish) in the app.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..db import Database

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com/v2"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_NAME = "tiktok"
SCOPES = "user.info.basic,video.upload,video.publish"


class TikTokError(RuntimeError):
    pass


class TikTokPublisher:
    def __init__(self, settings: Settings, db: Database, client: httpx.AsyncClient):
        self.settings = settings
        self.db = db
        self.client = client
        self.cfg = settings.app.publish.tiktok

    @property
    def configured(self) -> bool:
        return self.db.get_token(TOKEN_NAME) is not None

    # --- OAuth ---------------------------------------------------------------

    @property
    def can_connect(self) -> bool:
        return bool(self.settings.secrets.tiktok_client_key and self.settings.secrets.tiktok_client_secret)

    def authorize_url(self, state: str) -> str:
        query = urlencode({
            "client_key": self.settings.secrets.tiktok_client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": self.settings.secrets.tiktok_redirect_uri,
            "state": state,
        })
        return f"{AUTHORIZE_URL}?{query}"

    async def _token_request(self, **data: str) -> None:
        data |= {"client_key": self.settings.secrets.tiktok_client_key, "client_secret": self.settings.secrets.tiktok_client_secret}
        resp = await self.client.post(
            f"{API}/oauth/token/", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        payload = resp.json()
        if resp.status_code != 200 or "access_token" not in payload:
            raise TikTokError(f"token request failed: {payload}")
        now = time.time()
        self.db.set_token(TOKEN_NAME, {
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "open_id": payload.get("open_id", ""),
            "expires_at": now + int(payload.get("expires_in", 0)),
            "refresh_expires_at": now + int(payload.get("refresh_expires_in", 0)),
        })

    async def exchange_code(self, code: str) -> None:
        await self._token_request(
            code=code, grant_type="authorization_code", redirect_uri=self.settings.secrets.tiktok_redirect_uri
        )

    async def access_token(self) -> str:
        token = self.db.get_token(TOKEN_NAME)
        if token is None:
            raise TikTokError("TikTok is not connected: use /connect on Discord")
        if time.time() > token["expires_at"] - 600:  # access tokens live 24 hours
            await self._token_request(grant_type="refresh_token", refresh_token=token["refresh_token"])
            token = self.db.get_token(TOKEN_NAME)
        return token["access_token"]

    # --- Publishing ----------------------------------------------------------

    async def _post(self, path: str, body: dict) -> dict:
        resp = await self.client.post(
            f"{API}/{path}",
            json=body,
            headers={"Authorization": f"Bearer {await self.access_token()}", "Content-Type": "application/json; charset=UTF-8"},
        )
        payload = resp.json()
        error = payload.get("error", {})
        if resp.status_code != 200 or error.get("code") not in (None, "ok"):
            raise TikTokError(f"{path}: {error.get('code')} {error.get('message')}")
        return payload.get("data", {})

    async def _privacy_level(self) -> str:
        info = await self._post("post/publish/creator_info/query/", {})
        options = info.get("privacy_level_options", [])
        if self.cfg.privacy_level in options:
            return self.cfg.privacy_level
        log.warning("privacy %s not allowed for this account (%s), using SELF_ONLY", self.cfg.privacy_level, options)
        return "SELF_ONLY"

    @property
    def mode(self) -> str:
        # Without the TikTok audit, direct posts are private: "auto" sends a draft to the inbox instead.
        return "MEDIA_UPLOAD" if self.cfg.mode == "auto" else self.cfg.mode

    async def publish(self, title: str, description: str, image_urls: list[str]) -> dict:
        post_info: dict = {"title": title[:90], "description": description}
        if self.mode == "DIRECT_POST":
            post_info |= {"privacy_level": await self._privacy_level(), "disable_comment": False, "auto_add_music": True}
        data = await self._post("post/publish/content/init/", {
            "media_type": "PHOTO",
            "post_mode": self.mode,
            "post_info": post_info,
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": image_urls[:35]},
        })
        publish_id = data["publish_id"]
        status = await self._wait(publish_id)
        return {"publish_id": publish_id, "status": status, "mode": self.mode}

    async def _wait(self, publish_id: str, timeout: float = 180) -> str:
        deadline = time.monotonic() + timeout
        status = "UNKNOWN"
        while time.monotonic() < deadline:
            data = await self._post("post/publish/status/fetch/", {"publish_id": publish_id})
            status = data.get("status", "UNKNOWN")
            if status == "FAILED":
                raise TikTokError(f"publish {publish_id} failed: {data.get('fail_reason')}")
            if status in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}:
                return status
            await asyncio.sleep(5)
        log.warning("tiktok publish %s still %s after %ss", publish_id, status, timeout)
        return status
