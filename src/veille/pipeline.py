"""Orchestration: collect -> rank -> write -> render -> (Discord validation) -> publish at the slot."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .carousel.render import render_slides
from .config import Settings
from .db import Database
from .llm import LLM
from .models import DraftStatus, Item, PostContent, ThreadsCopy
from .publishers.threads import ThreadsPublisher
from .publishers.tiktok import TikTokPublisher
from .ranking import Candidate, rank
from .sources import Sources
from .writer import Writer

log = logging.getLogger(__name__)


class NoCandidate(RuntimeError):
    pass


def parse_slot(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def upcoming_slots(slots: list[str], tz: ZoneInfo, now: datetime, days: int = 2) -> list[datetime]:
    """Slot datetimes (aware, local timezone) strictly after `now`, sorted."""
    local_now = now.astimezone(tz)
    result = []
    for offset in range(days + 1):
        day = (local_now + timedelta(days=offset)).date()
        for slot in slots:
            dt = datetime.combine(day, parse_slot(slot), tzinfo=tz)
            if dt > local_now:
                result.append(dt)
    return sorted(result)


class Pipeline:
    def __init__(self, settings: Settings, db: Database | None = None):
        self.settings = settings
        self.tz = ZoneInfo(settings.app.timezone)
        self.db = db or Database(settings.db_path)
        self.llm = LLM(settings)
        self.sources = Sources(settings)
        self.writer = Writer(settings, self.llm)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self.threads = ThreadsPublisher(settings, self.db, self.http)
        self.tiktok = TikTokPublisher(settings, self.db, self.http)

    async def aclose(self) -> None:
        await self.sources.aclose()
        await self.http.aclose()

    # --- slots ---------------------------------------------------------------

    def next_slot(self, now: datetime | None = None) -> datetime:
        return upcoming_slots(self.settings.app.schedule.slots, self.tz, now or datetime.now(UTC))[0]

    # --- drafting ------------------------------------------------------------

    async def collect(self) -> list[Item]:
        items = await self.sources.collect()
        self.db.upsert_items(items)
        return items

    async def candidates(self) -> list[Candidate]:
        ranking = self.settings.app.ranking
        return await rank(
            self.llm,
            self.db.recent_items(hours=48),
            self.db.covered_topics(ranking.dedup_days),
            self.db.rejected_item_ids(ranking.dedup_days),
            ranking.shortlist_size,
        )

    def _draft_dir(self, draft_id: int) -> Path:
        # Unguessable directory name: the media server exposes it publicly.
        path = self.settings.media_dir / f"{draft_id:04d}-{secrets.token_hex(8)}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _render(self, draft_id: int, content: PostContent, item: Item | None, folder: Path | None = None) -> list[str]:
        folder = folder or self._draft_dir(draft_id)
        for old in folder.glob("slide-*.jpg"):
            old.unlink()
        paths = await render_slides(self.settings, content, folder, draft_id, datetime.now(self.tz), item)
        return [str(p.relative_to(self.settings.media_dir)) for p in paths]

    async def create_draft(self, slot_at: datetime, collect: bool = True) -> int:
        if collect:
            await self.collect()
        candidates = await self.candidates()
        if not candidates:
            raise NoCandidate("no candidate story left after filtering")
        best = candidates[0]
        log.info("selected %s (score %.2f): %s", best.item.id, best.score, best.item.title)
        dossier = await self.sources.dossier(best.item, best.related)
        content = await self.writer.write(dossier, angle_hint=best.angle)
        draft_id = self.db.create_draft(best.item, slot_at, content.model_dump(), [])
        folder = self._draft_dir(draft_id)
        (folder / "dossier.txt").write_text(dossier)
        media = await self._render(draft_id, content, best.item, folder)
        self.db.update_draft(draft_id, media=media)
        return draft_id

    def draft_folder(self, draft: dict) -> Path | None:
        if not draft["media"]:
            return None
        return (self.settings.media_dir / draft["media"][0]).parent

    async def regenerate(self, draft_id: int, instruction: str = "") -> None:
        draft = self._require(draft_id)
        folder = self.draft_folder(draft)
        dossier = (folder / "dossier.txt").read_text() if folder and (folder / "dossier.txt").exists() else ""
        if not dossier:
            item = self.db.get_item(draft["item_id"])
            dossier = await self.sources.dossier(item) if item else draft["title"]
        previous = PostContent.model_validate(draft["content"])
        content = await self.writer.write(dossier, instruction=instruction, previous=previous)
        media = await self._render(draft_id, content, self.db.get_item(draft["item_id"]), folder)
        self.db.update_draft(draft_id, content=content.model_dump(), media=media, status=DraftStatus.PENDING, error=None)

    def edit_threads(self, draft_id: int, post: str, reply: str) -> None:
        """Manual edit from Discord. Raises pydantic.ValidationError if the text exceeds Threads limits."""
        draft = self._require(draft_id)
        copy = ThreadsCopy(post=post, reply=reply)
        content = draft["content"] | {"threads": copy.model_dump()}
        self.db.update_draft(draft_id, content=content)

    def _require(self, draft_id: int) -> dict:
        draft = self.db.get_draft(draft_id)
        if draft is None:
            raise KeyError(f"draft {draft_id} not found")
        return draft

    def media_paths(self, draft: dict) -> list[Path]:
        return [self.settings.media_dir / p for p in draft["media"]]

    def media_urls(self, draft: dict) -> list[str]:
        base = self.settings.secrets.public_base_url.rstrip("/")
        return [f"{base}/media/{p}" for p in draft["media"]]

    # --- publishing ----------------------------------------------------------

    async def publish(self, draft_id: int, expected: DraftStatus = DraftStatus.APPROVED) -> dict:
        """Publish on every enabled platform. Platforms already done (retry after a failure) are skipped."""
        if not self.db.claim_draft(draft_id, expected, DraftStatus.PUBLISHING):
            raise RuntimeError(f"draft {draft_id} is not {expected.value}")
        draft = self._require(draft_id)
        content = PostContent.model_validate(draft["content"])
        results: dict = dict(draft["results"])
        errors: list[str] = []
        publish_cfg = self.settings.app.publish
        needs_urls = (publish_cfg.threads.enabled and publish_cfg.threads.attach_carousel) or publish_cfg.tiktok.enabled
        if needs_urls and not self.settings.secrets.public_base_url:
            errors.append("PUBLIC_BASE_URL is not set: Threads and TikTok cannot fetch the slides")
        else:
            urls = self.media_urls(draft)
            if publish_cfg.threads.enabled and "threads" not in results:
                try:
                    images = urls if publish_cfg.threads.attach_carousel else []
                    results["threads"] = await self.threads.publish(content.threads.post, content.threads.reply, images)
                except Exception as exc:  # noqa: BLE001 - reported on Discord, retry possible
                    log.exception("threads publish failed for draft %s", draft_id)
                    errors.append(f"Threads: {exc}")
            if publish_cfg.tiktok.enabled and "tiktok" not in results:
                try:
                    results["tiktok"] = await self.tiktok.publish(content.tiktok.title, content.tiktok.description, urls)
                except Exception as exc:  # noqa: BLE001 - reported on Discord, retry possible
                    log.exception("tiktok publish failed for draft %s", draft_id)
                    errors.append(f"TikTok: {exc}")

        status = DraftStatus.FAILED if errors else DraftStatus.PUBLISHED
        self.db.update_draft(draft_id, status=status, results=results, error="\n".join(errors) or None)
        return {"results": results, "errors": errors}

    async def publish_due(self) -> list[tuple[int, dict]]:
        done = []
        for draft in self.db.due_drafts():
            try:
                done.append((draft["id"], await self.publish(draft["id"])))
            except RuntimeError as exc:  # claimed by a concurrent call
                log.info("skip draft %s: %s", draft["id"], exc)
        return done
