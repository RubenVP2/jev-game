"""Render carousel slides to JPEG (TikTok photo posts accept JPEG/WebP, Threads accepts JPEG)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from playwright.async_api import async_playwright

from ..config import Settings
from ..models import Item, PostContent

log = logging.getLogger(__name__)

_env = Environment(loader=PackageLoader("veille.carousel", "templates"), autoescape=select_autoescape(["html"]))

SOURCE_LABELS = {"github": "GITHUB TRENDING", "hackernews": "HACKER NEWS", "reddit": "REDDIT"}


def signal_badges(item: Item | None) -> list[tuple[str, str]]:
    """Popularity figures shown on the cover, straight from the source."""
    if item is None:
        return []
    if item.source == "github":
        badges = [(f"{item.score:,}", "stars today")]
        if item.extra.get("total_stars"):
            badges.append((f"{item.extra['total_stars']:,}", "total"))
        return badges
    if item.source == "hackernews":
        return [(f"{item.score:,}", "points"), (f"{item.comments:,}", "comments")]
    if item.source == "reddit":
        return [(f"{item.score:,}", "upvotes"), (f"{item.comments:,}", "comments")]
    return []


def render_html(settings: Settings, content: PostContent, issue: int, date: datetime, item: Item | None) -> str:
    brand, carousel = settings.app.brand, settings.app.carousel
    return _env.get_template("carousel.html").render(
        slides=content.slides,
        brand=brand.name,
        accent=brand.accent,
        handle=brand.handle,
        issue=f"{issue:04d}",
        date=date.strftime("%Y-%m-%d"),
        source=SOURCE_LABELS.get(item.source, item.source.upper()) if item else "",
        signal=signal_badges(item),
        width=carousel.width,
        height=carousel.height,
    )


async def render_slides(
    settings: Settings, content: PostContent, out_dir: Path, issue: int, date: datetime, item: Item | None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_html(settings, content, issue, date, item)
    (out_dir / "carousel.html").write_text(html)
    carousel = settings.app.carousel
    paths: list[Path] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        try:
            page = await browser.new_page(viewport={"width": carousel.width, "height": carousel.height})
            try:
                await page.set_content(html, wait_until="networkidle", timeout=20000)
            except Exception as exc:  # noqa: BLE001 - fonts unreachable: render with fallback fonts
                log.warning("fonts not loaded, rendering with fallbacks: %s", exc)
            await page.evaluate("document.fonts.ready")
            for n in range(1, len(content.slides) + 1):
                path = out_dir / f"slide-{n:02d}.jpg"
                await page.locator(f"#slide-{n}").screenshot(path=str(path), type="jpeg", quality=92)
                paths.append(path)
        finally:
            await browser.close()
    return paths
