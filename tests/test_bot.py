"""Discord bot logic with fake interactions (no network)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from test_pipeline import FakePublisher, make_draft
from veille.bot import ActionButton, VeilleBot, draft_view
from veille.models import DraftStatus
from veille.pipeline import Pipeline


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.modal = None

    async def send_message(self, text, ephemeral=False):
        self.messages.append(text)

    async def send_modal(self, modal):
        self.modal = modal


class FakeInteraction:
    def __init__(self, user_id):
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse()
        self.followup = SimpleNamespace(send=self.response.send_message)


@pytest.fixture
def bot(settings, db, monkeypatch):
    settings.secrets.discord_allowed_user_ids = "42"
    pipeline = Pipeline(settings, db)
    pipeline.threads, pipeline.tiktok = FakePublisher(), FakePublisher()
    bot = VeilleBot(pipeline)
    bot.notified = []

    async def notify(text):
        bot.notified.append(text)

    async def refresh(draft_id):
        return None

    monkeypatch.setattr(bot, "notify", notify)
    monkeypatch.setattr(bot, "refresh_message", refresh)
    return bot


def test_commands_and_views_are_registered(bot):
    assert {c.name for c in bot.tree.get_commands()} == {"draft", "status", "connect"}
    view = draft_view(7, DraftStatus.PENDING)
    assert [c.custom_id for c in view.children][:2] == ["veille:approve:7", "veille:now:7"]
    assert draft_view(7, DraftStatus.PUBLISHED) is None


async def test_unauthorized_user_is_refused(bot, sample_content):
    draft_id = make_draft(bot.pipeline, sample_content, datetime.now(UTC), DraftStatus.PENDING)
    interaction = FakeInteraction(user_id=1)
    await bot.handle_action(interaction, "approve", draft_id)
    assert "not allowed" in interaction.response.messages[0]
    assert bot.pipeline.db.get_draft(draft_id)["status"] == DraftStatus.PENDING


async def test_approve_then_publish_due(bot, sample_content):
    draft_id = make_draft(bot.pipeline, sample_content, datetime.now(UTC) - timedelta(minutes=1), DraftStatus.PENDING)
    interaction = FakeInteraction(user_id=42)
    await bot.handle_action(interaction, "approve", draft_id)
    assert "within a minute" in interaction.response.messages[0]
    await bot.publish_due()
    assert bot.pipeline.db.get_draft(draft_id)["status"] == DraftStatus.PUBLISHED
    assert "published" in bot.notified[-1]


async def test_publish_now_and_double_click(bot, sample_content):
    draft_id = make_draft(bot.pipeline, sample_content, datetime.now(UTC) + timedelta(hours=3), DraftStatus.PENDING)
    await bot.handle_action(FakeInteraction(42), "now", draft_id)
    assert bot.pipeline.db.get_draft(draft_id)["status"] == DraftStatus.PUBLISHED
    second = FakeInteraction(42)
    await bot.handle_action(second, "now", draft_id)
    assert second.response.messages == ["Draft is published."]
    assert len(bot.pipeline.threads.calls) == 1


async def test_edit_opens_a_modal_and_reject(bot, sample_content):
    draft_id = make_draft(bot.pipeline, sample_content, datetime.now(UTC), DraftStatus.PENDING)
    interaction = FakeInteraction(42)
    await bot.handle_action(interaction, "edit", draft_id)
    assert interaction.response.modal.post.default == sample_content.threads.post
    await bot.handle_action(FakeInteraction(42), "reject", draft_id)
    assert bot.pipeline.db.get_draft(draft_id)["status"] == DraftStatus.REJECTED


def test_summary_shows_the_harness_report(bot, sample_content):
    draft_id = make_draft(bot.pipeline, sample_content, datetime.now(UTC), DraftStatus.PENDING)
    bot.pipeline.db.update_draft(draft_id, meta={"writer": "openrouter/x", "judge": "google/y", "score": 8.4, "revisions": 1})
    header, embed = bot._summary(bot.pipeline.db.get_draft(draft_id))
    harness = next(f for f in embed.fields if f.name == "Harness")
    assert "8.4/10" in harness.value and "openrouter/x" in harness.value
    assert "status **pending**" in header


async def test_dynamic_button_round_trip():
    import re

    button = ActionButton("regen", 12)
    match = re.fullmatch(ActionButton.__discord_ui_compiled_template__, button.item.custom_id)
    rebuilt = await ActionButton.from_custom_id(None, button.item, match)
    assert (rebuilt.action, rebuilt.draft_id) == ("regen", 12)


async def test_reminder_for_a_pending_draft_at_slot_time(bot, sample_content):
    now = datetime.now(bot.pipeline.tz).replace(second=0, microsecond=0) - timedelta(minutes=2)
    bot.settings.app.schedule.slots = [now.strftime("%H:%M")]
    draft_id = make_draft(bot.pipeline, sample_content, now, DraftStatus.PENDING)
    await bot.remind_pending()
    assert f"Draft #{draft_id}" in bot.notified[-1]


async def test_failed_generation_schedules_a_retry(bot, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(bot.pipeline, "create_draft", boom)
    added = []
    monkeypatch.setattr(bot.scheduler, "add_job", lambda *a, **k: added.append(k))
    await bot.prepare_next_slot(datetime.now(UTC) + timedelta(hours=2))
    assert "Retrying" in bot.notified[-1]
    assert added and added[0]["args"][1] == ""


async def test_defaults_use_veille_drafts_and_the_server_owner(settings, db, monkeypatch):
    settings.secrets.discord_allowed_user_ids = ""
    settings.secrets.discord_channel_id = ""
    bot = VeilleBot(Pipeline(settings, db))
    created = []

    async def create_text_channel(name, topic=""):
        created.append(name)
        return SimpleNamespace(id=555, name=name)

    guild = SimpleNamespace(name="srv", owner_id=99, text_channels=[], create_text_channel=create_text_channel)
    monkeypatch.setattr(VeilleBot, "guilds", property(lambda self: [guild]))
    await bot.resolve_defaults()
    assert created == ["veille-drafts"] and bot.channel_id == 555 and bot.reviewers == {99}

    existing = SimpleNamespace(id=777, name="veille-drafts")
    guild.text_channels = [existing]
    bot.channel_id, bot.reviewers = 0, set()
    await bot.resolve_defaults()
    assert bot.channel_id == 777 and created == ["veille-drafts"]  # reused, not created twice


def test_invite_url_has_the_needed_permissions():
    from veille.bot import invite_url

    url = invite_url(123)
    assert "client_id=123" in url and "applications.commands" in url and "permissions=117776" in url
