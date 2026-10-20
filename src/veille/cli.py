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
        draft_id = await pipeline.create_draft(pipeline.free_slot(), collect=not args.no_collect, instruction=args.instruction or "")
        draft = pipeline.db.get_draft(draft_id)
        content, meta = draft["content"], draft["meta"]
        print(f"\nDraft #{draft_id}: {draft['title']}\nAngle: {content['angle']}")
        score = f"{meta['score']:.1f}/10 by {meta.get('judge')}" if meta.get("score") is not None else "not judged"
        print(f"Writer: {meta.get('writer')} · editor score {score} · revisions {meta.get('revisions', 0)}")
        for issue in meta.get("open_issues", []):
            print(f"  open issue: {issue}")
        print()
        print("--- Threads post ---\n" + content["threads"]["post"])
        print("\n--- Threads reply ---\n" + content["threads"]["reply"])
        print("\n--- TikTok ---\n" + content["tiktok"]["title"] + "\n" + content["tiktok"]["description"])
        folder = pipeline.draft_folder(draft)
        if args.out:
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
    result = await render.render_slides(get_settings(), content, Path(args.out), 1, datetime.now(), None)
    print("\n".join(str(p) for p in result.paths))
    for overflow in result.overflows:
        print(f"overflow: {overflow}")


async def cmd_connect(args: argparse.Namespace) -> None:
    """Same as /connect on Discord: prints the authorization link; the running server receives the callback."""
    from .pipeline import Pipeline

    pipeline = Pipeline(get_settings())
    try:
        if args.code:
            print(await pipeline.complete_connect(args.platform, None, args.code))
            return
        print("Open this link logged in as the account that will post, then authorize:\n")
        print(pipeline.connect_url(args.platform))
        print("\nThe running server stores the token. Without it, copy `code` from the redirect URL and run:")
        print(f"  veille connect {args.platform} --code <code>")
    finally:
        await pipeline.aclose()


async def cmd_threads_refresh(_: argparse.Namespace) -> None:
    import httpx

    from .db import Database
    from .publishers.threads import ThreadsPublisher

    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        await ThreadsPublisher(settings, Database(settings.db_path), client).refresh_token()


async def cmd_doctor(args: argparse.Namespace) -> None:
    from .doctor import FAIL, Doctor, format_report

    checks = await Doctor(get_settings(), live=not args.offline).run()
    print(format_report(checks))
    if any(c.status == FAIL for c in checks):
        raise SystemExit(1)


async def cmd_eval(args: argparse.Namespace) -> None:
    from .config import ModelChoice
    from .harness.evaluate import SAMPLE_DOSSIER, evaluate, format_table

    settings = get_settings()
    dossier = Path(args.dossier).read_text() if args.dossier else SAMPLE_DOSSIER.read_text()
    if args.models:
        models = [ModelChoice(provider=m.split("/", 1)[0], model=m.split("/", 1)[1]) for m in args.models.split(",")]
    else:
        models = [c for c in settings.app.llm.tasks.get("write", []) if settings.api_key(c.provider)]
    if not models:
        raise SystemExit("no writer model with an API key: add a key or pass --models provider/model,...")
    rows = await evaluate(settings, dossier, models, Path(args.out))
    print(format_table(rows))
    print(f"\nFull outputs: {args.out}")


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
    p.add_argument("--instruction", help="writing instruction for this draft")
    p.add_argument("--no-collect", action="store_true", help="reuse items already in the database")

    p = sub.add_parser("demo", help="render the sample carousel")
    p.add_argument("--out", default="out/demo")

    p = sub.add_parser("connect", help="connect the Threads or TikTok account (OAuth link)")
    p.add_argument("platform", choices=["threads", "tiktok"])
    p.add_argument("--code", help="authorization code copied from the redirect URL")

    sub.add_parser("threads-refresh", help="refresh the Threads long-lived token")

    p = sub.add_parser("doctor", help="check keys, models, Discord, Threads, TikTok, media URL and rendering")
    p.add_argument("--offline", action="store_true", help="configuration only, no network call")

    p = sub.add_parser("eval", help="compare writer models on the same dossier with the consistency harness")
    p.add_argument("--models", help="comma-separated provider/model list (default: the write chain)")
    p.add_argument("--dossier", help="dossier text file (default: bundled sample)")
    p.add_argument("--out", default="out/eval")

    args = parser.parse_args()
    _setup_logging(args.verbose)
    if args.command == "run":
        cmd_run(args)
        return
    handlers = {
        "collect": cmd_collect,
        "draft": cmd_draft,
        "demo": cmd_demo,
        "connect": cmd_connect,
        "threads-refresh": cmd_threads_refresh,
        "doctor": cmd_doctor,
        "eval": cmd_eval,
    }
    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()
