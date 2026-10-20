"""Threads (Meta) publishing: containers, carousels, reply with the source link, long-lived token refresh."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..db import Database

log = logging.getLogger(__name__)

GRAPH = "https://graph.threads.net/v1.0"
REFRESH_URL = "https://graph.threads.net/refresh_access_token"
AUTHORIZE_URL = "https://threads.net/oauth/authorize"
SHORT_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
LONG_TOKEN_URL = "https://graph.threads.net/access_token"
SCOPES = "threads_basic,threads_content_publish"
TOKEN_NAME = "threads"


class ThreadsError(RuntimeError):
    pass


class ThreadsPublisher:
    def __init__(self, settings: Settings, db: Database, client: httpx.AsyncClient):
        self.settings = settings
        self.db = db
        self.client = client
        self.user_id = settings.secrets.threads_user_id or "me"

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @property
    def token(self) -> str:
        stored = self.db.get_token(TOKEN_NAME)
        return stored["access_token"] if stored else self.settings.secrets.threads_access_token

    @property
    def username(self) -> str:
        stored = self.db.get_token(TOKEN_NAME) or {}
        return stored.get("username", "")

    @property
    def can_connect(self) -> bool:
        return bool(self.settings.secrets.threads_app_id and self.settings.secrets.threads_app_secret)

    # --- OAuth: one click from Discord instead of copying tokens ---------------

    def authorize_url(self, state: str) -> str:
        query = urlencode({
            "client_id": self.settings.secrets.threads_app_id,
            "redirect_uri": self.settings.secrets.threads_redirect_uri,
            "scope": SCOPES,
            "response_type": "code",
            "state": state,
        })
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> str:
        """Authorization code -> short-lived token (1 hour) -> long-lived token (60 days). Returns the username."""
        secrets = self.settings.secrets
        resp = await self.client.post(SHORT_TOKEN_URL, data={
            "client_id": secrets.threads_app_id,
            "client_secret": secrets.threads_app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": secrets.threads_redirect_uri,
            "code": code.removesuffix("#_"),
        })
        short = resp.json()
        if resp.status_code != 200 or "access_token" not in short:
            raise ThreadsError(f"code exchange failed: {short}")
        resp = await self.client.get(LONG_TOKEN_URL, params={
            "grant_type": "th_exchange_token", "client_secret": secrets.threads_app_secret, "access_token": short["access_token"],
        })
        long_lived = resp.json()
        if resp.status_code != 200 or "access_token" not in long_lived:
            raise ThreadsError(f"long-lived token exchange failed: {long_lived}")
        self.db.set_token(TOKEN_NAME, {
            "access_token": long_lived["access_token"],
            "expires_at": time.time() + int(long_lived.get("expires_in", 0)),
            "user_id": str(short.get("user_id", "")),
        })
        await self.fetch_profile()
        return self.username

    async def fetch_profile(self) -> None:
        """Store the account username: the carousel footer shows it when brand.handle is empty."""
        data = await self._call("GET", "me", fields="id,username")
        stored = self.db.get_token(TOKEN_NAME) or {"access_token": self.token}
        self.db.set_token(TOKEN_NAME, stored | {"username": data.get("username", ""), "user_id": data.get("id", "")})

    async def refresh_token(self) -> None:
        """Long-lived tokens last 60 days and can be refreshed once they are 24 hours old."""
        if not self.token:
            return
        resp = await self.client.get(REFRESH_URL, params={"grant_type": "th_refresh_token", "access_token": self.token})
        if resp.status_code != 200:
            log.warning("threads token refresh failed: %s %s", resp.status_code, resp.text[:300])
            return
        data = resp.json()
        stored = self.db.get_token(TOKEN_NAME) or {}
        self.db.set_token(
            TOKEN_NAME, stored | {"access_token": data["access_token"], "expires_at": time.time() + int(data.get("expires_in", 0))}
        )
        if not self.username:
            await self.fetch_profile()
        log.info("threads token refreshed")

    async def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        resp = await self.client.request(method, f"{GRAPH}/{path}", params=params)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in data:
            raise ThreadsError(f"{path}: {data.get('error', resp.text[:300])}")
        return data

    async def _container(self, **params) -> str:
        data = await self._call("POST", f"{self.user_id}/threads", **params)
        return data["id"]

    async def _wait(self, container_id: str, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = await self._call("GET", container_id, fields="status,error_message")
            status = data.get("status")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise ThreadsError(f"container {container_id} {status}: {data.get('error_message')}")
            await asyncio.sleep(3)
        raise ThreadsError(f"container {container_id} not ready after {timeout}s")

    async def _publish(self, container_id: str) -> str:
        await self._wait(container_id)
        data = await self._call("POST", f"{self.user_id}/threads_publish", creation_id=container_id)
        return data["id"]

    async def publish(self, post: str, reply: str, image_urls: list[str]) -> dict:
        if image_urls and len(image_urls) >= 2:
            children = []
            for url in image_urls[:20]:
                children.append(await self._container(media_type="IMAGE", image_url=url, is_carousel_item="true"))
            for child in children:
                await self._wait(child)
            container = await self._container(media_type="CAROUSEL", children=",".join(children), text=post)
        else:
            container = await self._container(media_type="TEXT", text=post)
        post_id = await self._publish(container)
        result = {"post_id": post_id}
        if reply:
            reply_container = await self._container(media_type="TEXT", text=reply, reply_to_id=post_id)
            result["reply_id"] = await self._publish(reply_container)
        try:
            data = await self._call("GET", post_id, fields="permalink")
            result["permalink"] = data.get("permalink", "")
        except ThreadsError:
            pass
        return result
