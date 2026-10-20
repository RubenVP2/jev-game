"""Threads (Meta) publishing: containers, carousels, reply with the source link, long-lived token refresh."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ..config import Settings
from ..db import Database

log = logging.getLogger(__name__)

GRAPH = "https://graph.threads.net/v1.0"
REFRESH_URL = "https://graph.threads.net/refresh_access_token"
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

    async def refresh_token(self) -> None:
        """Long-lived tokens last 60 days and can be refreshed once they are 24 hours old."""
        if not self.token:
            return
        resp = await self.client.get(REFRESH_URL, params={"grant_type": "th_refresh_token", "access_token": self.token})
        if resp.status_code != 200:
            log.warning("threads token refresh failed: %s %s", resp.status_code, resp.text[:300])
            return
        data = resp.json()
        self.db.set_token(
            TOKEN_NAME, {"access_token": data["access_token"], "expires_at": time.time() + int(data.get("expires_in", 0))}
        )
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
