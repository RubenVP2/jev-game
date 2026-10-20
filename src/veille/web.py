"""Small HTTP server: public slide URLs for Threads/TikTok, OAuth callbacks (Threads, TikTok), domain verification files."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from aiohttp import web

from .pipeline import Pipeline

log = logging.getLogger(__name__)

_VERIFICATION_FILE = re.compile(r"^[A-Za-z0-9_-]+\.txt$")


def build_app(pipeline: Pipeline, on_connected: Callable[[str], Awaitable[None]] | None = None) -> web.Application:
    settings = pipeline.settings
    public_dir = settings.data_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    async def healthz(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def verification(request: web.Request) -> web.StreamResponse:
        # TikTok "URL prefix" verification: drop the file they give you in data/public/.
        name = request.match_info["name"]
        path = public_dir / name
        if not _VERIFICATION_FILE.match(name) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    def oauth_callback(platform: str):
        async def handler(request: web.Request) -> web.Response:
            code = request.query.get("code")
            if not code:
                reason = request.query.get("error_description") or request.query.get("error_message") or "no code"
                return web.Response(status=400, text=f"Authorization refused: {reason}")
            try:
                message = await pipeline.complete_connect(platform, request.query.get("state", ""), code)
            except Exception as exc:  # noqa: BLE001 - shown to the person who clicked
                log.warning("%s connection failed: %s", platform, exc)
                return web.Response(status=400, text=f"Connection failed: {exc}")
            log.info(message)
            if on_connected is not None:
                await on_connected(message)
            return web.Response(text=f"{message}. You can close this tab.")

        return handler

    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/tiktok/callback", oauth_callback("tiktok"))
    app.router.add_get("/threads/callback", oauth_callback("threads"))
    app.router.add_static("/media/", settings.media_dir, show_index=False, follow_symlinks=False)
    app.router.add_get("/{name}", verification)
    return app


async def start(
    pipeline: Pipeline,
    host: str = "0.0.0.0",
    port: int = 8080,
    on_connected: Callable[[str], Awaitable[None]] | None = None,
) -> web.AppRunner:
    runner = web.AppRunner(build_app(pipeline, on_connected))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("media server listening on %s:%s", host, port)
    return runner
