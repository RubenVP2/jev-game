from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from veille.models import DraftStatus, Item
from veille.pipeline import Pipeline, upcoming_slots

PARIS = ZoneInfo("Europe/Paris")


def test_upcoming_slots_in_paris_time():
    now = datetime(2026, 10, 20, 9, 0, tzinfo=PARIS)
    slots = upcoming_slots(["08:00", "19:00"], PARIS, now)
    assert slots[0] == datetime(2026, 10, 20, 19, 0, tzinfo=PARIS)
    assert slots[1] == datetime(2026, 10, 21, 8, 0, tzinfo=PARIS)


def test_upcoming_slots_across_dst_change():
    # Clocks go back on 2026-10-25 at 03:00: 08:00 local is 06:00 UTC before, 07:00 UTC after.
    now = datetime(2026, 10, 23, 20, 0, tzinfo=PARIS)
    before, after = upcoming_slots(["08:00"], PARIS, now)[:2]
    assert before.astimezone(UTC).hour == 6
    assert after.astimezone(UTC).hour == 7


class FakePublisher:
    def __init__(self, fail=False, configured=True):
        self.fail = fail
        self.configured = configured
        self.calls = []

    async def publish(self, *args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("api down")
        return {"post_id": "1"}


@pytest.fixture
def pipeline(settings, db, sample_content):
    p = Pipeline(settings, db)
    p.threads = FakePublisher()
    p.tiktok = FakePublisher()
    return p


def make_draft(pipeline, content, slot_at, status=DraftStatus.APPROVED):
    item = Item(source="hackernews", native_id="1", url="https://a.dev", discussion_url="https://a.dev", title="A story")
    draft_id = pipeline.db.create_draft(item, slot_at, content.model_dump(), ["0001-x/slide-01.jpg", "0001-x/slide-02.jpg"])
    pipeline.db.update_draft(draft_id, status=status)
    return draft_id


async def test_publish_due_publishes_only_approved_past_slots(pipeline, sample_content):
    now = datetime.now(UTC)
    due = make_draft(pipeline, sample_content, now - timedelta(minutes=1))
    future = make_draft(pipeline, sample_content, now + timedelta(hours=1))
    pending = make_draft(pipeline, sample_content, now - timedelta(minutes=1), DraftStatus.PENDING)

    done = await pipeline.publish_due()

    assert [d for d, _ in done] == [due]
    assert pipeline.db.get_draft(due)["status"] == DraftStatus.PUBLISHED
    assert pipeline.db.get_draft(future)["status"] == DraftStatus.APPROVED
    assert pipeline.db.get_draft(pending)["status"] == DraftStatus.PENDING
    _, _, urls = pipeline.threads.calls[0]
    assert urls == ["https://media.test/media/0001-x/slide-01.jpg", "https://media.test/media/0001-x/slide-02.jpg"]


async def test_partial_failure_then_retry_skips_done_platform(pipeline, sample_content):
    pipeline.tiktok = FakePublisher(fail=True)
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC))

    outcome = await pipeline.publish(draft_id)
    assert outcome["errors"] == ["TikTok: api down"]
    assert pipeline.db.get_draft(draft_id)["status"] == DraftStatus.FAILED

    pipeline.tiktok = FakePublisher()
    await pipeline.publish(draft_id, expected=DraftStatus.FAILED)
    assert len(pipeline.threads.calls) == 1  # not posted twice
    assert len(pipeline.tiktok.calls) == 1
    assert pipeline.db.get_draft(draft_id)["status"] == DraftStatus.PUBLISHED


async def test_publish_refuses_wrong_status(pipeline, sample_content):
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC), DraftStatus.PUBLISHED)
    with pytest.raises(RuntimeError):
        await pipeline.publish(draft_id)


async def test_missing_public_url_blocks_publication(pipeline, sample_content):
    pipeline.settings.secrets.public_base_url = ""
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC))
    outcome = await pipeline.publish(draft_id)
    assert "PUBLIC_BASE_URL" in outcome["errors"][0]
    assert pipeline.threads.calls == []


def test_edit_threads_validates_length(pipeline, sample_content):
    from pydantic import ValidationError

    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC), DraftStatus.PENDING)
    pipeline.edit_threads(draft_id, "New post", "New reply")
    assert pipeline.db.get_draft(draft_id)["content"]["threads"] == {"post": "New post", "reply": "New reply"}
    with pytest.raises(ValidationError):
        pipeline.edit_threads(draft_id, "x" * 600, "")


async def test_unconfigured_platform_is_skipped_not_failed(pipeline, sample_content):
    pipeline.tiktok = FakePublisher(configured=False)
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC))
    outcome = await pipeline.publish(draft_id)
    assert outcome["errors"] == []
    assert outcome["skipped"] == ["tiktok"]
    assert pipeline.db.get_draft(draft_id)["status"] == DraftStatus.PUBLISHED


async def test_no_platform_at_all_is_an_error(pipeline, sample_content):
    pipeline.threads = FakePublisher(configured=False)
    pipeline.tiktok = FakePublisher(configured=False)
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC))
    outcome = await pipeline.publish(draft_id)
    assert "no platform is configured" in outcome["errors"][0]


def test_has_substance():
    from veille.pipeline import has_substance

    assert not has_substance("TITLE: x\nURL: y")
    assert has_substance("README:\n" + "x" * 2000)
    assert has_substance("PRACTITIONER COMMENTS (opinions, not facts):\n" + "x" * 2000)


def test_free_slot_skips_slots_with_drafts(pipeline, sample_content):
    first = pipeline.next_slot()
    make_draft(pipeline, sample_content, first, DraftStatus.PENDING)
    assert pipeline.free_slot() > first


def test_validated_contents_and_hooks(pipeline, sample_content):
    make_draft(pipeline, sample_content, datetime.now(UTC), DraftStatus.PUBLISHED)
    make_draft(pipeline, sample_content, datetime.now(UTC), DraftStatus.REJECTED)
    assert len(pipeline.db.validated_contents(5)) == 1
    assert pipeline.db.recent_hooks() == [sample_content.threads.post.splitlines()[0]]
