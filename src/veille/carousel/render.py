"""Render carousel slides to JPEG (TikTok photo posts accept JPEG/WebP, Threads accepts JPEG)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
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


def render_html(
    settings: Settings, content: PostContent, issue: int, date: datetime, item: Item | None, handle: str | None = None
) -> str:
    brand, carousel = settings.app.brand, settings.app.carousel
    return _env.get_template("carousel.html").render(
        slides=content.slides,
        brand=brand.name,
        accent=brand.accent,
        handle=brand.handle if handle is None else handle,
        issue=f"{issue:04d}",
        date=date.strftime("%Y-%m-%d"),
        source=SOURCE_LABELS.get(item.source, item.source.upper()) if item else "",
        signal=signal_badges(item),
        width=carousel.width,
        height=carousel.height,
    )


# Measures how much each slide's content exceeds its frame (main block height, code block width).
FILL = 0.94  # content may use 94% of the frame height: keeps air under the header and above the footer

MEASURE_JS = """
() => [...document.querySelectorAll('section.slide')].map((slide, i) => {
  const main = slide.querySelector('main');
  const kids = [...main.children];
  const top = Math.min(...kids.map(k => k.getBoundingClientRect().top));
  const bottom = Math.max(...kids.map(k => k.getBoundingClientRect().bottom));
  const pre = slide.querySelector('pre');
  return {
    index: i + 1,
    over: Math.max(0, (bottom - top) - FILL * main.clientHeight) / (FILL * main.clientHeight),
    wide: pre ? Math.max(0, pre.scrollWidth - pre.clientWidth) / pre.clientWidth : 0,
  };
})
"""

# Last-resort fit: shrink an overflowing slide (zoom) or code block (font size) until it fits.
AUTOFIT_JS = """
() => document.querySelectorAll('section.slide').forEach(slide => {
  const main = slide.querySelector('main');
  const fits = () => {
    const kids = [...main.children];
    const top = Math.min(...kids.map(k => k.getBoundingClientRect().top));
    const bottom = Math.max(...kids.map(k => k.getBoundingClientRect().bottom));
    return bottom - top <= FILL * main.clientHeight;
  };
  for (let z = 1; !fits() && z > 0.66; z -= 0.02) main.style.zoom = z.toFixed(2);
  const pre = slide.querySelector('pre');
  for (let size = 29; pre && pre.scrollWidth > pre.clientWidth && size > 20; size -= 1) pre.style.fontSize = size + 'px';
})
"""


@dataclass
class RenderResult:
    paths: list[Path]
    overflows: list[str]  # problems for the writer, empty when every slide fits as written


async def render_slides(
    settings: Settings,
    content: PostContent,
    out_dir: Path,
    issue: int,
    date: datetime,
    item: Item | None,
    handle: str | None = None,
) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_html(settings, content, issue, date, item, handle)
    (out_dir / "carousel.html").write_text(html)
    carousel = settings.app.carousel
    paths: list[Path] = []
    overflows: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        try:
            page = await browser.new_page(viewport={"width": carousel.width, "height": carousel.height})
            try:
                await page.set_content(html, wait_until="networkidle", timeout=20000)
            except Exception as exc:  # noqa: BLE001 - fonts unreachable: render with fallback fonts
                log.warning("fonts not loaded, rendering with fallbacks: %s", exc)
            await page.evaluate("document.fonts.ready")
            # Height: shorter text reads better than smaller text, so overflow goes back to the writer.
            for m in await page.evaluate(MEASURE_JS.replace("FILL", str(FILL))):
                if m["over"] > 0.01:
                    kind = content.slides[m["index"] - 1].kind
                    pct = round(m["over"] * 100)
                    overflows.append(f"slide {m['index']} ({kind}): text is {pct}% taller than the frame, cut it by about {pct + 10}%")
            await page.evaluate(AUTOFIT_JS.replace("FILL", str(FILL)))
            # Width: a slightly smaller code font is fine; only report code that still does not fit.
            for m in await page.evaluate(MEASURE_JS.replace("FILL", str(FILL))):
                if m["wide"] > 0.01:
                    kind = content.slides[m["index"] - 1].kind
                    overflows.append(f"slide {m['index']} ({kind}): code lines are too wide, re-wrap them under 56 characters")
            for n in range(1, len(content.slides) + 1):
                path = out_dir / f"slide-{n:02d}.jpg"
                await page.locator(f"#slide-{n}").screenshot(path=str(path), type="jpeg", quality=92)
                paths.append(path)
        finally:
            await browser.close()
    return RenderResult(paths, overflows)
