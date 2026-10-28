"""Discord bot: draft review (approve, publish now, edit, regenerate, reject) and the scheduler."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import ValidationError

from . import web
from .models import DraftStatus, threads_length
from .pipeline import NoCandidate, Pipeline, parse_slot, upcoming_slots

log = logging.getLogger(__name__)

ACTIONS = {
    "approve": ("Approve for slot", discord.ButtonStyle.success, 0),
    "now": ("Publish now", discord.ButtonStyle.primary, 0),
    "edit": ("Edit text", discord.ButtonStyle.secondary, 0),
    "regen": ("Regenerate", discord.ButtonStyle.secondary, 0),
    "another": ("Another topic", discord.ButtonStyle.secondary, 1),
    "reject": ("Reject", discord.ButtonStyle.danger, 1),
    "retry": ("Retry publish", discord.ButtonStyle.primary, 0),
    "unapprove": ("Cancel approval", discord.ButtonStyle.secondary, 0),
}

RETRY_DELAY = timedelta(minutes=20)
DEFAULT_CHANNEL = "veille-drafts"
# View channels, send messages, embed links, attach files, read history, manage channels (#veille-drafts).
INVITE_PERMISSIONS = 1024 | 2048 | 16384 | 32768 | 65536 | 16


def invite_url(application_id: int | str) -> str:
    return (
        f"https://discord.com/oauth2/authorize?client_id={application_id}"
        f"&scope=bot%20applications.commands&permissions={INVITE_PERMISSIONS}"
    )

STATUS_ACTIONS = {
    DraftStatus.PENDING: ["approve", "now", "edit", "regen", "another", "reject"],
    DraftStatus.APPROVED: ["now", "unapprove", "reject"],
    DraftStatus.FAILED: ["retry", "reject"],
}


class ActionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"veille:(?P<action>[a-z]+):(?P<id>\d+)"):
    """Persistent button: keeps working after a bot restart because the draft id lives in custom_id."""

    def __init__(self, action: str, draft_id: int):
        label, style, row = ACTIONS[action]
        super().__init__(discord.ui.Button(label=label, style=style, row=row, custom_id=f"veille:{action}:{draft_id}"))
        self.action = action
        self.draft_id = draft_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.client.handle_action(interaction, self.action, self.draft_id)  # type: ignore[attr-defined]


def draft_view(draft_id: int, status: DraftStatus) -> discord.ui.View | None:
    actions = STATUS_ACTIONS.get(status)
    if not actions:
        return None
    view = discord.ui.View(timeout=None)
    for action in actions:
        view.add_item(ActionButton(action, draft_id))
    return view


class EditModal(discord.ui.Modal, title="Edit the Threads copy"):
    def __init__(self, bot: VeilleBot, draft: dict):
        super().__init__(timeout=900)
        self.bot = bot
        self.draft_id = draft["id"]
        threads = draft["content"]["threads"]
        self.post = discord.ui.TextInput(label="Post (max 500)", style=discord.TextStyle.paragraph, default=threads["post"], max_length=500)
        self.reply = discord.ui.TextInput(label="Reply with source (max 500)", style=discord.TextStyle.paragraph, default=threads["reply"], max_length=500, required=False)
        self.add_item(self.post)
        self.add_item(self.reply)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            self.bot.pipeline.edit_threads(self.draft_id, self.post.value, self.reply.value)
        except ValidationError as exc:
            await interaction.response.send_message(f"Not saved: {exc.errors()[0]['msg']}", ephemeral=True)
            return
        await interaction.response.defer()
        await self.bot.refresh_message(self.draft_id)


class RegenerateModal(discord.ui.Modal, title="Regenerate this draft"):
    instruction = discord.ui.TextInput(
        label="Instruction (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. focus on the benchmark methodology, shorter cover, add a code slide",
        required=False,
        max_length=1000,
    )

    def __init__(self, bot: VeilleBot, draft_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.draft_id = draft_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Regenerating...", ephemeral=True)
        await self.bot.run_regenerate(self.draft_id, self.instruction.value)


class VeilleBot(discord.Client):
    def __init__(self, pipeline: Pipeline):
        super().__init__(intents=discord.Intents.default())
        self.pipeline = pipeline
        self.settings = pipeline.settings
        # A busy event loop (rendering, LLM calls) must delay jobs, never drop them.
        self.scheduler = AsyncIOScheduler(timezone=pipeline.tz, job_defaults={"misfire_grace_time": 900, "coalesce": True})
        self.draft_lock = asyncio.Lock()
        self._web_runner = None
        self._tasks: set[asyncio.Task] = set()
        self._synced = False
        # Resolved at startup when not configured: #veille-drafts and the server owner.
        self.channel_id = pipeline.settings.secrets.channel_id
        self.reviewers = set(pipeline.settings.secrets.allowed_user_ids)
        self.tree = discord.app_commands.CommandTree(self)
        self._register_commands()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _register_commands(self) -> None:
        @self.tree.command(name="draft", description="Draft a post now for the next free slot")
        @discord.app_commands.describe(instruction="Optional writing instruction, e.g. 'focus on the benchmark methodology'")
        async def draft(interaction: discord.Interaction, instruction: str | None = None) -> None:
            if not await self._authorized(interaction):
                return
            slot = self.pipeline.free_slot()
            await interaction.response.send_message(f"Drafting for {self._fmt(slot)}...", ephemeral=True)
            self._spawn(self.prepare_next_slot(slot, instruction or ""))

        @self.tree.command(name="connect", description="Connect the Threads or TikTok account (one-time authorization link)")
        @discord.app_commands.choices(platform=[
            discord.app_commands.Choice(name="Threads", value="threads"),
            discord.app_commands.Choice(name="TikTok", value="tiktok"),
        ])
        async def connect(interaction: discord.Interaction, platform: discord.app_commands.Choice[str]) -> None:
            if not await self._authorized(interaction):
                return
            try:
                url = self.pipeline.connect_url(platform.value)
            except ValueError as exc:
                await interaction.response.send_message(f"Cannot connect {platform.name}: {exc}", ephemeral=True)
                return
            await interaction.response.send_message(
                f"Open this link logged in as the account that will post, then authorize:\n{url}\n"
                "A confirmation is posted here once it is done.",
                ephemeral=True,
            )

        @self.tree.command(name="status", description="Upcoming slots, drafts and connected platforms")
        async def status(interaction: discord.Interaction) -> None:
            if not await self._authorized(interaction):
                return
            await interaction.response.send_message("\n".join(self.pipeline.status_lines())[:2000], ephemeral=True)

    async def _authorized(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.reviewers:
            return True
        await interaction.response.send_message("You are not allowed to review drafts (DISCORD_ALLOWED_USER_IDS).", ephemeral=True)
        return False

    # --- lifecycle -----------------------------------------------------------

    async def setup_hook(self) -> None:
        self.add_dynamic_items(ActionButton)
        self._web_runner = await web.start(self.pipeline, on_connected=self.notify)
        lead = timedelta(minutes=self.settings.app.schedule.draft_lead_minutes)
        for slot in self.settings.app.schedule.slots:
            t = parse_slot(slot)
            fire = datetime(2000, 1, 1, t.hour, t.minute) - lead
            self.scheduler.add_job(self.prepare_next_slot, CronTrigger(hour=fire.hour, minute=fire.minute), name=f"draft {slot}")
            self.scheduler.add_job(self.remind_pending, CronTrigger(hour=t.hour, minute=t.minute), name=f"remind {slot}")
        self.scheduler.add_job(self.publish_due, IntervalTrigger(minutes=1), name="publish due drafts")
        self.scheduler.add_job(self.pipeline.threads.refresh_token, CronTrigger(hour=4, minute=17), name="threads token")
        self.scheduler.start()

    async def on_ready(self) -> None:
        log.info("discord bot ready as %s", self.user)
        if not self._synced:  # on_ready also fires on reconnects
            self._synced = True
            try:
                await self.resolve_defaults()
            except (RuntimeError, discord.HTTPException) as exc:
                log.error("discord setup incomplete: %s", exc)
                return
            channel = await self.channel()
            guild = getattr(channel, "guild", None)
            if guild is not None:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)  # guild commands are available immediately
            if self.pipeline.backend == "uploadpost":
                try:
                    await self.pipeline.uploadpost.profile(refresh=True)  # connected accounts and Threads handle
                except Exception as exc:  # noqa: BLE001
                    log.warning("upload-post profile unavailable: %s", exc)
            await self.notify(f"**{self.settings.app.brand.name}** online.\n" + "\n".join(self.pipeline.status_lines()))
        # Catch up after a restart: the draft for an imminent slot may not exist yet.
        slot = self.pipeline.next_slot()
        lead = timedelta(minutes=self.settings.app.schedule.draft_lead_minutes)
        if slot - datetime.now(UTC) <= lead and self.pipeline.db.active_draft_for_slot(slot) is None:
            self._spawn(self.prepare_next_slot())

    async def close(self) -> None:
        self.scheduler.shutdown(wait=False)
        if self._web_runner:
            await self._web_runner.cleanup()
        await self.pipeline.aclose()
        await super().close()

    async def channel(self) -> discord.abc.Messageable:
        return self.get_channel(self.channel_id) or await self.fetch_channel(self.channel_id)

    async def resolve_defaults(self) -> None:
        """Only the bot token is required: default to #veille-drafts and the server owner as reviewer."""
        if self.channel_id and self.reviewers:
            return
        if not self.guilds:
            raise RuntimeError(f"the bot is not in any Discord server yet, invite it: {invite_url(self.application_id)}")
        guild = self.guilds[0]
        if not self.channel_id:
            channel = discord.utils.get(guild.text_channels, name=DEFAULT_CHANNEL)
            if channel is None:
                channel = await guild.create_text_channel(DEFAULT_CHANNEL, topic="Drafts to review before publication")
            self.channel_id = channel.id
            log.info("using #%s (%s) in %s", channel.name, channel.id, guild.name)
        if not self.reviewers:
            self.reviewers = {guild.owner_id}
            log.info("reviewer: server owner %s", guild.owner_id)

    async def notify(self, text: str) -> None:
        await (await self.channel()).send(text[:2000])

    # --- jobs ----------------------------------------------------------------

    async def prepare_next_slot(self, slot: datetime | None = None, instruction: str = "") -> None:
        slot = slot or self.pipeline.next_slot()
        async with self.draft_lock:
            if self.pipeline.db.active_draft_for_slot(slot) is not None:
                return
            try:
                draft_id = await self.pipeline.create_draft(slot, instruction=instruction)
            except NoCandidate as exc:
                await self.notify(f"No draft for {self._fmt(slot)}: {exc}")
                return
            except Exception as exc:  # noqa: BLE001 - surfaced on Discord instead of dying silently
                log.exception("draft generation failed")
                retry_at = datetime.now(UTC) + RETRY_DELAY
                retry = slot - retry_at > timedelta(minutes=5)
                if retry:
                    self.scheduler.add_job(self.prepare_next_slot, "date", run_date=retry_at, args=[slot, instruction])
                await self.notify(
                    f"Draft generation failed for {self._fmt(slot)}: `{str(exc)[:500]}`"
                    + (f"\nRetrying at {self._fmt(retry_at)}." if retry else "\nUse /draft to try again.")
                )
                return
        await self.post_draft(draft_id)

    async def remind_pending(self) -> None:
        """At slot time, a draft still waiting for review gets a reminder (it publishes as soon as approved)."""
        now = datetime.now(UTC)
        recent = upcoming_slots(self.settings.app.schedule.slots, self.pipeline.tz, now - timedelta(hours=1))
        past = [s for s in recent if s <= now]
        if not past:
            return
        slot = past[-1]
        draft = self.pipeline.db.active_draft_for_slot(slot)
        if draft and draft["status"] == DraftStatus.PENDING:
            await self.notify(f"Draft #{draft['id']} for {self._fmt(slot)} is still waiting for review. Approve it to publish right away.")

    async def publish_due(self) -> None:
        for draft_id, outcome in await self.pipeline.publish_due():
            await self.refresh_message(draft_id)
            await self.notify(self._publish_report(draft_id, outcome))

    # --- Discord rendering ---------------------------------------------------

    def _fmt(self, dt: datetime) -> str:
        return dt.astimezone(self.pipeline.tz).strftime("%a %d %b %H:%M")

    def _publish_report(self, draft_id: int, outcome: dict) -> str:
        lines = [f"**Draft #{draft_id}**: " + ("published" if not outcome["errors"] else "publication failed")]
        threads = outcome["results"].get("threads")
        if threads:
            lines.append(f"Threads: {threads.get('permalink') or threads.get('url') or threads.get('post_id')}")
        tiktok = outcome["results"].get("tiktok")
        if tiktok:
            where = ("sent to your TikTok inbox, finish it in the app" if tiktok.get("mode") == "MEDIA_UPLOAD"
                     else tiktok.get("url") or tiktok.get("status") or "published")
            lines.append(f"TikTok: {where}")
        lines += [f"Skipped (not configured): {name}" for name in outcome.get("skipped", [])]
        lines += [f"Error: {e}" for e in outcome["errors"]]
        return "\n".join(lines)

    def _summary(self, draft: dict) -> tuple[str, discord.Embed]:
        content = draft["content"]
        item = self.pipeline.db.get_item(draft["item_id"])
        header = f"**Draft #{draft['id']}** · slot {self._fmt(draft['slot_at'])} · status **{draft['status'].value}**"
        if draft.get("error"):
            header += f"\nError: {draft['error'][:500]}"
        embed = discord.Embed(title=draft["title"][:256], url=item.discussion_url if item else None, description=f"*{content['angle']}*"[:4096])
        post, reply = content["threads"]["post"], content["threads"]["reply"]
        embed.add_field(name=f"Threads post ({threads_length(post)}/500)", value=post[:1024], inline=False)
        embed.add_field(name=f"Threads reply ({threads_length(reply)}/500)", value=reply[:1024] or "-", inline=False)
        embed.add_field(name="TikTok title", value=content["tiktok"]["title"][:1024], inline=False)
        embed.add_field(name="TikTok description", value=content["tiktok"]["description"][:1024], inline=False)
        meta = draft.get("meta") or {}
        if meta.get("writer"):
            quality = f"written by `{meta['writer']}`"
            if meta.get("score") is not None:
                quality += f" · editor score **{meta['score']:.1f}/10** by `{meta.get('judge', '?')}`"
            if meta.get("revisions"):
                quality += f" · {meta['revisions']} revision(s)"
            if meta.get("open_issues"):
                quality += "\nOpen issues:\n" + "\n".join(f"- {i}" for i in meta["open_issues"][:5])
            embed.add_field(name="Harness", value=quality[:1024], inline=False)
        if item:
            embed.set_footer(text=f"{item.source} · score {item.score} · {item.comments} comments · {item.url}"[:2048])
        return header, embed

    async def post_draft(self, draft_id: int) -> None:
        draft = self.pipeline.db.get_draft(draft_id)
        header, embed = self._summary(draft)
        files = [discord.File(p) for p in self.pipeline.media_paths(draft)[:10]]
        message = await (await self.channel()).send(content=header, embed=embed, files=files, view=draft_view(draft_id, draft["status"]))
        self.pipeline.db.update_draft(draft_id, discord_message_id=message.id)

    async def refresh_message(self, draft_id: int) -> None:
        draft = self.pipeline.db.get_draft(draft_id)
        if not draft or not draft["discord_message_id"]:
            return
        header, embed = self._summary(draft)
        try:
            message = await (await self.channel()).fetch_message(draft["discord_message_id"])
            await message.edit(content=header, embed=embed, view=draft_view(draft_id, draft["status"]))
        except discord.HTTPException as exc:
            log.warning("cannot update message for draft %s: %s", draft_id, exc)

    # --- button handling -----------------------------------------------------

    async def handle_action(self, interaction: discord.Interaction, action: str, draft_id: int) -> None:
        if not await self._authorized(interaction):
            return
        db = self.pipeline.db
        draft = db.get_draft(draft_id)
        if draft is None:
            await interaction.response.send_message("Draft not found.", ephemeral=True)
            return

        if action == "edit":
            await interaction.response.send_modal(EditModal(self, draft))
        elif action == "regen":
            await interaction.response.send_modal(RegenerateModal(self, draft_id))
        elif action == "approve":
            ok = db.claim_draft(draft_id, DraftStatus.PENDING, DraftStatus.APPROVED)
            when = "within a minute" if draft["slot_at"] <= datetime.now(UTC) else self._fmt(draft["slot_at"])
            await self._ack(interaction, draft_id, f"Approved, publishing {when}." if ok else "Draft is no longer pending.")
        elif action == "unapprove":
            ok = db.claim_draft(draft_id, DraftStatus.APPROVED, DraftStatus.PENDING)
            await self._ack(interaction, draft_id, "Back to pending." if ok else "Draft is no longer approved.")
        elif action in {"now", "retry"}:
            expected = {"now": draft["status"], "retry": DraftStatus.FAILED}[action]
            if expected not in (DraftStatus.PENDING, DraftStatus.APPROVED, DraftStatus.FAILED):
                await interaction.response.send_message(f"Draft is {draft['status'].value}.", ephemeral=True)
                return
            await interaction.response.send_message("Publishing...", ephemeral=True)
            try:
                outcome = await self.pipeline.publish(draft_id, expected=expected)
            except RuntimeError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            await self.refresh_message(draft_id)
            await self.notify(self._publish_report(draft_id, outcome))
        elif action == "reject":
            db.update_draft(draft_id, status=DraftStatus.REJECTED)
            await self._ack(interaction, draft_id, "Rejected.")
        elif action == "another":
            db.update_draft(draft_id, status=DraftStatus.REJECTED)
            await self._ack(interaction, draft_id, "Rejected. Drafting another topic for this slot...")
            await self.prepare_next_slot(draft["slot_at"])

    async def _ack(self, interaction: discord.Interaction, draft_id: int, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)
        await self.refresh_message(draft_id)

    async def run_regenerate(self, draft_id: int, instruction: str) -> None:
        old = self.pipeline.db.get_draft(draft_id)
        try:
            await self.pipeline.regenerate(draft_id, instruction)
        except Exception as exc:  # noqa: BLE001
            log.exception("regeneration failed")
            await self.notify(f"Regeneration of draft #{draft_id} failed: `{exc}`")
            return
        # New slides mean new attachments: post a fresh message and retire the old one.
        if old and old["discord_message_id"]:
            try:
                message = await (await self.channel()).fetch_message(old["discord_message_id"])
                await message.edit(content=f"~~Draft #{draft_id}~~ regenerated below.", embed=None, attachments=[], view=None)
            except discord.HTTPException:
                pass
        await self.post_draft(draft_id)


def run(pipeline: Pipeline) -> None:
    token = pipeline.settings.secrets.discord_bot_token
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is required")
    VeilleBot(pipeline).run(token, log_handler=None)
