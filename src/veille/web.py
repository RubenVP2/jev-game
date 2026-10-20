"""Small HTTP server: public slide URLs for Threads/TikTok, TikTok OAuth callback, domain verification files."""

from __future__ import annotations

import logging
import re

from aiohttp import web

from .pipeline import Pipeline

log = logging.getLogger(__name__)

STATE_TOKEN = "tiktok_oauth_state"
_VERIFICATION_FILE = re.compile(r"^[A-Za-z0-9_-]+\.txt$")


def build_app(pipeline: Pipeline) -> web.Application:
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

    async def tiktok_callback(request: web.Request) -> web.Response:
        expected = pipeline.db.get_token(STATE_TOKEN) or {}
        if not expected or request.query.get("state") != expected.get("state"):
            return web.Response(status=400, text="Invalid state. Run `veille tiktok-auth` again.")
        code = request.query.get("code")
        if not code:
            return web.Response(status=400, text=f"TikTok returned no code: {request.query.get('error_description', '')}")
        await pipeline.tiktok.exchange_code(code)
        pipeline.db.set_token(STATE_TOKEN, {})
        log.info("tiktok account connected")
        return web.Response(text="TikTok connected. You can close this tab.")

    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/tiktok/callback", tiktok_callback)
    app.router.add_static("/media/", settings.media_dir, show_index=False, follow_symlinks=False)
    app.router.add_get("/{name}", verification)
    return app


async def start(pipeline: Pipeline, host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    runner = web.AppRunner(build_app(pipeline))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("media server listening on %s:%s", host, port)
    return runner
