"""Command line: `veille run` for production, the other commands to test each stage by hand."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import get_settings
from .models import PostContent


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "discord.gateway", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_run(_: argparse.Namespace) -> None:
    from .bot import run
    from .pipeline import Pipeline

    run(Pipeline(get_settings()))


async def cmd_collect(args: argparse.Namespace) -> None:
    from .pipeline import Pipeline

    pipeline = Pipeline(get_settings())
    try:
        items = await pipeline.collect()
        print(f"{len(items)} items collected")
        if not args.no_rank:
            for c in (await pipeline.candidates())[: args.top]:
                editorial = "-" if c.editorial is None else f"{c.editorial:.2f}"
                print(f"{c.score:.2f} (heur {c.heuristic:.2f}, edit {editorial}) [{'+'.join(sorted(c.sources))}] {c.item.title}")
                print(f"      {c.item.url}")
                if c.angle:
                    print(f"      angle: {c.angle}")
    finally:
        await pipeline.aclose()


async def cmd_draft(args: argparse.Namespace) -> None:
    """Full pipeline without Discord or publication: prints the copy and writes the slides."""
    from .pipeline import Pipeline

    pipeline = Pipeline(get_settings())
    try:
        draft_id = await pipeline.create_draft(pipeline.next_slot(), collect=not args.no_collect)
        draft = pipeline.db.get_draft(draft_id)
        content = draft["content"]
        print(f"\nDraft #{draft_id}: {draft['title']}\nAngle: {content['angle']}\n")
        print("--- Threads post ---\n" + content["threads"]["post"])
        print("\n--- Threads reply ---\n" + content["threads"]["reply"])
        print("\n--- TikTok ---\n" + content["tiktok"]["title"] + "\n" + content["tiktok"]["description"])
        folder = pipeline.draft_folder(draft)
        if args.out and folder:
            shutil.copytree(folder, args.out, dirs_exist_ok=True)
            folder = Path(args.out)
        print(f"\nSlides: {folder}")
        # A local preview must not occupy the slot or count as a covered topic.
        pipeline.db.delete_draft(draft_id)
    finally:
        await pipeline.aclose()


async def cmd_demo(args: argparse.Namespace) -> None:
    """Render the bundled sample carousel: checks Playwright and the design without any API key."""
    from .carousel import render

    sample = Path(render.__file__).with_name("sample.json")
    content = PostContent.model_validate(json.loads(sample.read_text()))
    paths = await render.render_slides(get_settings(), content, Path(args.out), 1, datetime.now(), None)
    print("\n".join(str(p) for p in paths))


async def cmd_tiktok_auth(args: argparse.Namespace) -> None:
    import httpx

    from .db import Database
    from .publishers.tiktok import TikTokPublisher
    from .web import STATE_TOKEN

    settings = get_settings()
    db = Database(settings.db_path)
    async with httpx.AsyncClient(timeout=30) as client:
        tiktok = TikTokPublisher(settings, db, client)
        if args.code:
            await tiktok.exchange_code(args.code)
            print("TikTok connected.")
            return
        url, state = tiktok.authorize_url()
        db.set_token(STATE_TOKEN, {"state": state})
        print("Open this URL while logged in to the TikTok account that will post:\n")
        print(url)
        print("\nThe running server receives the callback on TIKTOK_REDIRECT_URI and stores the token.")
        print("Without a running server, copy the `code` parameter from the redirect URL and run:")
        print("  veille tiktok-auth --code <code>")


async def cmd_threads_refresh(_: argparse.Namespace) -> None:
    import httpx

    from .db import Database
    from .publishers.threads import ThreadsPublisher

    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        await ThreadsPublisher(settings, Database(settings.db_path), client).refresh_token()


def main() -> None:
    parser = argparse.ArgumentParser(prog="veille", description="Tech watch -> Threads & TikTok pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Discord bot + scheduler + media server (production)")

    p = sub.add_parser("collect", help="collect sources and print the ranking")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--no-rank", action="store_true", help="skip ranking (no LLM call)")

    p = sub.add_parser("draft", help="generate one draft locally, without Discord or publication")
    p.add_argument("--out", help="copy the slides to this folder")
    p.add_argument("--no-collect", action="store_true", help="reuse items already in the database")

    p = sub.add_parser("demo", help="render the sample carousel")
    p.add_argument("--out", default="out/demo")

    p = sub.add_parser("tiktok-auth", help="connect the TikTok account (OAuth)")
    p.add_argument("--code", help="authorization code copied from the redirect URL")

    sub.add_parser("threads-refresh", help="refresh the Threads long-lived token")

    args = parser.parse_args()
    _setup_logging(args.verbose)
    if args.command == "run":
        cmd_run(args)
        return
    handlers = {
        "collect": cmd_collect,
        "draft": cmd_draft,
        "demo": cmd_demo,
        "tiktok-auth": cmd_tiktok_auth,
        "threads-refresh": cmd_threads_refresh,
    }
    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()
