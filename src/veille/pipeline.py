"""Orchestration: collect -> rank -> write -> render -> (Discord validation) -> publish at the slot."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from .carousel.render import RenderResult, render_slides
from .config import Settings
from .db import Database
from .harness import Harness
from .harness.facts import FactSheet
from .llm import LLM, LLMError
from .models import DraftStatus, Item, PostContent, ThreadsCopy
from .publishers.threads import ThreadsPublisher
from .publishers.tiktok import TikTokPublisher
from .ranking import Candidate, rank
from .sources import Sources

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


def has_substance(dossier: str) -> bool:
    """A post needs primary material (README, article or self-post) or a real discussion to work from."""
    primary = any(marker in dossier for marker in ("README:", "ARTICLE TEXT:", "SUMMARY:"))
    discussion = "PRACTITIONER COMMENTS" in dossier
    return len(dossier) >= 1500 and (primary or discussion)


class Pipeline:
    def __init__(self, settings: Settings, db: Database | None = None):
        self.settings = settings
        self.tz = ZoneInfo(settings.app.timezone)
        self.db = db or Database(settings.db_path)
        self.llm = LLM(settings)
        self.sources = Sources(settings)
        self.harness = Harness(settings, self.llm)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self.threads = ThreadsPublisher(settings, self.db, self.http)
        self.tiktok = TikTokPublisher(settings, self.db, self.http)

    async def aclose(self) -> None:
        await self.sources.aclose()
        await self.http.aclose()

    # --- account connection (OAuth) --------------------------------------------

    def _publisher(self, platform: str) -> ThreadsPublisher | TikTokPublisher:
        if platform not in ("threads", "tiktok"):
            raise ValueError(f"unknown platform {platform!r}")
        return self.threads if platform == "threads" else self.tiktok

    def connect_url(self, platform: str) -> str:
        """Authorization link to open once; the callback on DOMAIN stores the token."""
        publisher = self._publisher(platform)
        if not publisher.can_connect:
            keys = "THREADS_APP_ID/THREADS_APP_SECRET" if platform == "threads" else "TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET"
            raise ValueError(f"set {keys} in .env first")
        if not self.settings.secrets.public_base_url:
            raise ValueError("set DOMAIN in .env first: the authorization returns to https://DOMAIN")
        state = secrets.token_urlsafe(16)
        self.db.set_token(f"oauth_state:{platform}", {"state": state, "created": datetime.now(UTC).isoformat()})
        return publisher.authorize_url(state)

    async def complete_connect(self, platform: str, state: str | None, code: str) -> str:
        """Validate the state (anti-CSRF), exchange the code, return a confirmation message."""
        expected = self.db.get_token(f"oauth_state:{platform}") or {}
        if state is not None and state != expected.get("state"):
            raise ValueError("invalid or expired link: start again with /connect")
        publisher = self._publisher(platform)
        if platform == "threads":
            username = await publisher.exchange_code(code)
            message = f"Threads connected as @{username}"
        else:
            await publisher.exchange_code(code)
            message = "TikTok connected"
        self.db.set_token(f"oauth_state:{platform}", {})
        return message

    def handle(self) -> str:
        """Footer handle: brand.handle if set, else the connected Threads username."""
        configured = self.settings.app.brand.handle
        if configured:
            return configured
        return f"@{self.threads.username}" if self.threads.username else ""

    # --- slots ---------------------------------------------------------------

    def next_slot(self, now: datetime | None = None) -> datetime:
        return upcoming_slots(self.settings.app.schedule.slots, self.tz, now or datetime.now(UTC))[0]

    def free_slot(self, now: datetime | None = None) -> datetime:
        """The next slot that has no active draft (for manual /draft requests)."""
        slots = upcoming_slots(self.settings.app.schedule.slots, self.tz, now or datetime.now(UTC), days=7)
        return next((s for s in slots if self.db.active_draft_for_slot(s) is None), slots[-1])

    def status_lines(self) -> list[str]:
        lines = []
        for slot in upcoming_slots(self.settings.app.schedule.slots, self.tz, datetime.now(UTC))[:4]:
            draft = self.db.active_draft_for_slot(slot)
            state = f"draft #{draft['id']} **{draft['status'].value}**: {draft['title']}" if draft else "no draft yet"
            lines.append(f"`{slot.strftime('%a %d %b %H:%M')}` {state}")
        providers = [p for p in self.settings.app.llm.providers if self.settings.api_key(p)]
        lines.append("LLM providers: " + (", ".join(providers) or "**none, add an API key**"))
        tiktok_mode = self.settings.app.publish.tiktok.mode
        lines.append(
            f"Threads: {'connected' if self.threads.configured else 'not configured'} · "
            f"TikTok: {'connected' if self.tiktok.configured else 'not connected'} ({tiktok_mode})"
        )
        stats = self.db.stats()
        if stats:
            lines.append("Drafts: " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
        return lines

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

    def draft_folder(self, draft: dict) -> Path:
        folder = draft["meta"].get("folder")
        if folder:
            return self.settings.media_dir / folder
        if draft["media"]:
            return (self.settings.media_dir / draft["media"][0]).parent
        return self._draft_dir(draft["id"])

    async def _render(self, draft_id: int, content: PostContent, item: Item | None, folder: Path) -> RenderResult:
        for old in folder.glob("slide-*.jpg"):
            old.unlink()
        return await render_slides(self.settings, content, folder, draft_id, datetime.now(self.tz), item, handle=self.handle())

    async def _compose_and_render(
        self,
        draft_id: int,
        item: Item,
        dossier: str,
        folder: Path,
        angle_hint: str = "",
        instruction: str = "",
        previous: PostContent | None = None,
        facts: FactSheet | None = None,
    ) -> None:
        """Harness composition, render, one targeted revision if a slide overflows, then save everything."""
        approved = []
        for raw in self.db.validated_contents(self.settings.app.harness.exemplars):
            try:
                approved.append(PostContent.model_validate(raw))
            except ValidationError:  # an old draft from a previous schema must not block writing
                continue
        hooks = self.db.recent_hooks()
        composition = await self.harness.compose(
            item, dossier, approved, hooks, angle_hint=angle_hint, instruction=instruction, previous=previous, facts=facts
        )
        (folder / "facts.json").write_text(composition.facts.model_dump_json(indent=2))
        rendered = await self._render(draft_id, composition.content, item, folder)
        if rendered.overflows:
            log.info("draft %s: slides overflow, asking for shorter text: %s", draft_id, rendered.overflows)
            try:
                composition.content = await self.harness.fit_slides(composition, item, dossier, rendered.overflows, hooks)
                rendered = await self._render(draft_id, composition.content, item, folder)
            except LLMError as exc:
                log.warning("fit revision failed, keeping auto-fitted slides: %s", exc)
        meta = composition.report.as_dict() | {"folder": folder.name, "overflows": rendered.overflows}
        self.db.update_draft(
            draft_id,
            content=composition.content.model_dump(),
            media=[str(p.relative_to(self.settings.media_dir)) for p in rendered.paths],
            meta=meta,
        )

    async def create_draft(self, slot_at: datetime, collect: bool = True, attempts: int = 3, instruction: str = "") -> int:
        """Draft the best candidate; if its dossier is too thin or writing fails, move on to the next one."""
        if collect:
            await self.collect()
        candidates = await self.candidates()
        if not candidates:
            raise NoCandidate("no candidate story left after filtering")
        errors = []
        for candidate in candidates[:attempts]:
            item = candidate.item
            log.info("drafting %s (score %.2f): %s", item.id, candidate.score, item.title)
            dossier = await self.sources.dossier(item, candidate.related)
            if not has_substance(dossier):
                log.info("skip %s: dossier too thin", item.id)
                errors.append(f"{item.title}: dossier too thin")
                continue
            draft_id = self.db.create_draft(item, slot_at, {"threads": {"post": ""}}, [])
            folder = self._draft_dir(draft_id)
            (folder / "dossier.txt").write_text(dossier)
            try:
                await self._compose_and_render(draft_id, item, dossier, folder, angle_hint=candidate.angle, instruction=instruction)
                return draft_id
            except LLMError as exc:
                log.warning("drafting %s failed: %s", item.id, exc)
                errors.append(f"{item.title}: {exc}")
                self.db.delete_draft(draft_id)
            except BaseException:
                self.db.delete_draft(draft_id)  # never leave a half-written draft behind
                raise
        raise NoCandidate("no draft could be written: " + " | ".join(errors))

    async def regenerate(self, draft_id: int, instruction: str = "") -> None:
        draft = self._require(draft_id)
        folder = self.draft_folder(draft)
        item = self.db.get_item(draft["item_id"])
        if item is None:
            raise KeyError(f"item {draft['item_id']} of draft {draft_id} not found")
        dossier_file, facts_file = folder / "dossier.txt", folder / "facts.json"
        dossier = dossier_file.read_text() if dossier_file.exists() else await self.sources.dossier(item)
        facts = FactSheet.model_validate_json(facts_file.read_text()) if facts_file.exists() else None
        await self._compose_and_render(
            draft_id, item, dossier, folder,
            instruction=instruction, previous=PostContent.model_validate(draft["content"]), facts=facts,
        )
        self.db.update_draft(draft_id, status=DraftStatus.PENDING, error=None)

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
        skipped: list[str] = []
        cfg = self.settings.app.publish
        platforms = []
        for name, enabled, publisher in (
            ("threads", cfg.threads.enabled, self.threads),
            ("tiktok", cfg.tiktok.enabled, self.tiktok),
        ):
            if not enabled or name in results:
                continue
            if not publisher.configured:
                skipped.append(name)  # e.g. TikTok not connected yet: publish elsewhere, do not fail
                continue
            platforms.append(name)

        if platforms and not self.settings.secrets.public_base_url:
            errors.append("PUBLIC_BASE_URL is not set: Threads and TikTok cannot fetch the slides")
            platforms = []
        urls = self.media_urls(draft)
        for name in platforms:
            try:
                if name == "threads":
                    images = urls if cfg.threads.attach_carousel else []
                    results["threads"] = await self.threads.publish(content.threads.post, content.threads.reply, images)
                else:
                    results["tiktok"] = await self.tiktok.publish(content.tiktok.title, content.tiktok.description, urls)
            except Exception as exc:  # noqa: BLE001 - reported on Discord, retry possible
                log.exception("%s publish failed for draft %s", name, draft_id)
                errors.append(f"{'Threads' if name == 'threads' else 'TikTok'}: {exc}")
        if not results and not errors:
            errors.append("no platform is configured: set THREADS_ACCESS_TOKEN and/or connect TikTok")

        status = DraftStatus.FAILED if errors else DraftStatus.PUBLISHED
        self.db.update_draft(draft_id, status=status, results=results, error="\n".join(errors) or None)
        return {"results": results, "errors": errors, "skipped": skipped}

    async def publish_due(self) -> list[tuple[int, dict]]:
        done = []
        for draft in self.db.due_drafts():
            try:
                done.append((draft["id"], await self.publish(draft["id"])))
            except RuntimeError as exc:  # claimed by a concurrent call
                log.info("skip draft %s: %s", draft["id"], exc)
        return done
