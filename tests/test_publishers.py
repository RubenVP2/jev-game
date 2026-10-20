"""Contract tests: the exact HTTP calls made to Threads and TikTok, as documented by Meta and TikTok."""

import json
import time

import httpx
import pytest
import respx

from veille.publishers import threads as threads_mod
from veille.publishers import tiktok as tiktok_mod
from veille.publishers.threads import ThreadsPublisher
from veille.publishers.tiktok import TikTokError, TikTokPublisher

GRAPH = "https://graph.threads.net/v1.0"
TIKTOK = "https://open.tiktokapis.com/v2"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(threads_mod.asyncio, "sleep", instant)
    monkeypatch.setattr(tiktok_mod.asyncio, "sleep", instant)


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


# --- Threads -----------------------------------------------------------------


@respx.mock
async def test_threads_carousel_then_reply(settings, db, client):
    settings.secrets.threads_access_token = "tok"
    created = []

    def create(request):
        params = dict(request.url.params)
        created.append(params)
        return httpx.Response(200, json={"id": f"c{len(created)}"})

    respx.post(f"{GRAPH}/me/threads").mock(side_effect=create)
    respx.get(url__regex=rf"{GRAPH}/c\d+").mock(return_value=httpx.Response(200, json={"status": "FINISHED"}))
    published = iter(["post1", "reply1"])
    publish = respx.post(f"{GRAPH}/me/threads_publish").mock(
        side_effect=lambda r: httpx.Response(200, json={"id": next(published)})
    )
    respx.get(f"{GRAPH}/post1").mock(return_value=httpx.Response(200, json={"permalink": "https://threads.net/p/1"}))

    result = await ThreadsPublisher(settings, db, client).publish("Post", "Reply", ["https://m/1.jpg", "https://m/2.jpg"])

    assert result == {"post_id": "post1", "reply_id": "reply1", "permalink": "https://threads.net/p/1"}
    images, carousel, reply = created[:2], created[2], created[3]
    assert all(i["media_type"] == "IMAGE" and i["is_carousel_item"] == "true" for i in images)
    assert [i["image_url"] for i in images] == ["https://m/1.jpg", "https://m/2.jpg"]
    assert carousel == {"media_type": "CAROUSEL", "children": "c1,c2", "text": "Post", "access_token": "tok"}
    assert reply["media_type"] == "TEXT" and reply["reply_to_id"] == "post1" and reply["text"] == "Reply"
    assert [dict(c.request.url.params)["creation_id"] for c in publish.calls] == ["c3", "c4"]


@respx.mock
async def test_threads_container_error_is_reported(settings, db, client):
    settings.secrets.threads_access_token = "tok"
    respx.post(f"{GRAPH}/me/threads").mock(return_value=httpx.Response(200, json={"id": "c1"}))
    respx.get(f"{GRAPH}/c1").mock(return_value=httpx.Response(200, json={"status": "ERROR", "error_message": "bad image"}))
    with pytest.raises(threads_mod.ThreadsError, match="bad image"):
        await ThreadsPublisher(settings, db, client).publish("Post", "", [])


@respx.mock
async def test_threads_oauth_exchange_and_username(settings, db, client):
    settings.secrets.threads_app_id, settings.secrets.threads_app_secret = "app", "secret"
    settings.secrets.threads_redirect_uri = "https://media.test/threads/callback"
    short = respx.post("https://graph.threads.net/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "short", "user_id": 7})
    )
    long = respx.get("https://graph.threads.net/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})
    )
    respx.get(f"{GRAPH}/me").mock(return_value=httpx.Response(200, json={"id": "7", "username": "signal_dev"}))

    publisher = ThreadsPublisher(settings, db, client)
    assert await publisher.exchange_code("abc#_") == "signal_dev"

    form = dict(httpx.QueryParams(short.calls[0].request.content.decode()))
    assert form == {"client_id": "app", "client_secret": "secret", "grant_type": "authorization_code",
                    "redirect_uri": "https://media.test/threads/callback", "code": "abc"}
    assert dict(long.calls[0].request.url.params) == {"grant_type": "th_exchange_token", "client_secret": "secret", "access_token": "short"}
    assert publisher.token == "long" and publisher.username == "signal_dev"
    url = publisher.authorize_url("st")
    assert url.startswith("https://threads.net/oauth/authorize?") and "scope=threads_basic%2Cthreads_content_publish" in url


@respx.mock
async def test_threads_refresh_keeps_the_username(settings, db, client):
    db.set_token("threads", {"access_token": "old", "username": "signal_dev"})
    respx.get("https://graph.threads.net/refresh_access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 5184000})
    )
    publisher = ThreadsPublisher(settings, db, client)
    await publisher.refresh_token()
    assert publisher.token == "new" and publisher.username == "signal_dev"


# --- TikTok ------------------------------------------------------------------


def connect_tiktok(db, expires_in=3600):
    db.set_token("tiktok", {"access_token": "at", "refresh_token": "rt", "open_id": "o",
                            "expires_at": time.time() + expires_in, "refresh_expires_at": time.time() + 86400 * 300})


@respx.mock
async def test_tiktok_photo_draft_to_inbox(settings, db, client):
    connect_tiktok(db)
    init = respx.post(f"{TIKTOK}/post/publish/content/init/").mock(
        return_value=httpx.Response(200, json={"data": {"publish_id": "p1"}, "error": {"code": "ok"}})
    )
    statuses = iter(["PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"])
    respx.post(f"{TIKTOK}/post/publish/status/fetch/").mock(
        side_effect=lambda r: httpx.Response(200, json={"data": {"status": next(statuses)}, "error": {"code": "ok"}})
    )

    result = await TikTokPublisher(settings, db, client).publish("Title", "Description #tech", ["https://m/1.jpg"])

    assert result == {"publish_id": "p1", "status": "SEND_TO_USER_INBOX", "mode": "MEDIA_UPLOAD"}
    body = json.loads(init.calls[0].request.content)
    assert body == {
        "media_type": "PHOTO", "post_mode": "MEDIA_UPLOAD",
        "post_info": {"title": "Title", "description": "Description #tech"},
        "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": ["https://m/1.jpg"]},
    }
    assert init.calls[0].request.headers["Authorization"] == "Bearer at"


@respx.mock
async def test_tiktok_direct_post_falls_back_to_allowed_privacy(settings, db, client):
    connect_tiktok(db)
    settings.app.publish.tiktok.mode = "DIRECT_POST"
    respx.post(f"{TIKTOK}/post/publish/creator_info/query/").mock(return_value=httpx.Response(
        200, json={"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}}
    ))
    init = respx.post(f"{TIKTOK}/post/publish/content/init/").mock(
        return_value=httpx.Response(200, json={"data": {"publish_id": "p1"}, "error": {"code": "ok"}})
    )
    respx.post(f"{TIKTOK}/post/publish/status/fetch/").mock(
        return_value=httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}})
    )
    await TikTokPublisher(settings, db, client).publish("T", "D", ["https://m/1.jpg"])
    info = json.loads(init.calls[0].request.content)["post_info"]
    assert info["privacy_level"] == "SELF_ONLY" and info["auto_add_music"] is True


@respx.mock
async def test_tiktok_refreshes_an_expiring_token(settings, db, client):
    connect_tiktok(db, expires_in=60)
    refresh = respx.post(f"{TIKTOK}/oauth/token/").mock(return_value=httpx.Response(200, json={
        "access_token": "at2", "refresh_token": "rt2", "expires_in": 86400, "refresh_expires_in": 86400 * 365, "open_id": "o",
    }))
    publisher = TikTokPublisher(settings, db, client)
    assert await publisher.access_token() == "at2"
    form = dict(httpx.QueryParams(refresh.calls[0].request.content.decode()))
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt"


@respx.mock
async def test_tiktok_failure_reason_is_reported(settings, db, client):
    connect_tiktok(db)
    respx.post(f"{TIKTOK}/post/publish/content/init/").mock(
        return_value=httpx.Response(200, json={"data": {"publish_id": "p1"}, "error": {"code": "ok"}})
    )
    respx.post(f"{TIKTOK}/post/publish/status/fetch/").mock(
        return_value=httpx.Response(200, json={"data": {"status": "FAILED", "fail_reason": "url_ownership_unverified"}, "error": {"code": "ok"}})
    )
    with pytest.raises(TikTokError, match="url_ownership_unverified"):
        await TikTokPublisher(settings, db, client).publish("T", "D", ["https://m/1.jpg"])


# --- connection flow -----------------------------------------------------------


async def test_connect_requires_app_keys_and_checks_state(settings, db):
    from veille.pipeline import Pipeline

    pipeline = Pipeline(settings, db)
    with pytest.raises(ValueError, match="THREADS_APP_ID"):
        pipeline.connect_url("threads")
    settings.secrets.threads_app_id, settings.secrets.threads_app_secret = "app", "secret"
    url = pipeline.connect_url("threads")
    state = dict(httpx.URL(url).params)["state"]
    with pytest.raises(ValueError, match="invalid or expired"):
        await pipeline.complete_connect("threads", "forged", "code")
    assert state
    await pipeline.aclose()


async def test_handle_comes_from_the_threads_account(settings, db):
    from veille.pipeline import Pipeline

    pipeline = Pipeline(settings, db)
    settings.app.brand.handle = ""
    assert pipeline.handle() == ""
    db.set_token("threads", {"access_token": "t", "username": "signal_dev"})
    assert pipeline.handle() == "@signal_dev"
    settings.app.brand.handle = "@custom"
    assert pipeline.handle() == "@custom"
    await pipeline.aclose()


# --- Upload-Post ---------------------------------------------------------------

UPLOADPOST = "https://api.upload-post.com/api"
PROFILES = {"success": True, "profiles": [{"username": "signal", "social_accounts": {
    "threads": {"handle": "signal_dev", "username": "123"}, "tiktok": {"handle": "signal.dev"}, "x": ""}}]}


def multipart_fields(request) -> dict[str, list[str]]:
    """Text fields of a multipart body, by name (files excluded)."""
    import re

    fields: dict[str, list[str]] = {}
    body = request.content.decode("latin-1")
    for part in body.split("--" + request.headers["content-type"].split("boundary=")[1]):
        m = re.search(r'name="([^"]+)"(?!; filename)\r\n\r\n(.*)\r\n$', part, re.S)
        if m:
            fields.setdefault(m.group(1), []).append(m.group(2))
    return fields


@respx.mock
async def test_uploadpost_publishes_threads_and_tiktok_in_one_call(settings, db, client, sample_content, tmp_path):
    from veille.publishers.uploadpost import UploadPostPublisher

    settings.secrets.uploadpost_api_key = "key"
    respx.get(f"{UPLOADPOST}/uploadposts/users").mock(return_value=httpx.Response(200, json=PROFILES))
    upload = respx.post(f"{UPLOADPOST}/upload_photos").mock(return_value=httpx.Response(200, json={
        "success": True,
        "results": {"threads": {"success": True, "url": "https://threads.net/@signal_dev/post/1", "post_id": "1"},
                    "tiktok": {"success": True, "publish_id": "p1"}},
    }))
    images = []
    for n in (1, 2):
        path = tmp_path / f"slide-0{n}.jpg"
        path.write_bytes(b"jpeg")
        images.append(path)

    publisher = UploadPostPublisher(settings, db, client)
    result = await publisher.publish(sample_content, images, ["threads", "tiktok"])

    assert result["threads"]["url"].endswith("/post/1")
    assert result["tiktok"] == {"publish_id": "p1", "via": "upload-post", "mode": "DIRECT_POST"}
    request = upload.calls[0].request
    assert request.headers["Authorization"] == "Apikey key"
    fields = multipart_fields(request)
    assert fields["user"] == ["signal"]
    assert fields["platform[]"] == ["threads", "tiktok"]
    assert fields["threads_title"][0].replace("\r\n", "\n") == sample_content.threads.post
    assert fields["threads_first_comment"][0].startswith(sample_content.threads.reply.splitlines()[0])
    assert fields["post_mode"] == ["DIRECT_POST"] and fields["privacy_level"] == ["PUBLIC_TO_EVERYONE"]
    assert request.content.count(b'name="photos[]"') == 2
    assert publisher.threads_handle() == "@signal_dev"


@respx.mock
async def test_uploadpost_async_status_and_partial_failure(settings, db, client, sample_content, tmp_path):
    from veille.publishers.uploadpost import UploadPostPublisher

    settings.secrets.uploadpost_api_key = "key"
    respx.get(f"{UPLOADPOST}/uploadposts/users").mock(return_value=httpx.Response(200, json=PROFILES))
    respx.post(f"{UPLOADPOST}/upload_photos").mock(return_value=httpx.Response(200, json={"success": True, "request_id": "r1"}))
    statuses = iter([{"status": "in_progress"}, {"status": "completed", "results": [
        {"platform": "threads", "success": True, "message": "ok"},
        {"platform": "tiktok", "success": False, "message": "account needs reauth"},
    ]}])
    respx.get(f"{UPLOADPOST}/uploadposts/status").mock(side_effect=lambda r: httpx.Response(200, json=next(statuses)))
    image = tmp_path / "slide-01.jpg"
    image.write_bytes(b"jpeg")

    result = await UploadPostPublisher(settings, db, client).publish(sample_content, [image], ["threads", "tiktok"])
    assert result["threads"]["via"] == "upload-post"
    assert result["tiktok"] == {"error": "account needs reauth"}


async def test_pipeline_uses_uploadpost_when_its_key_is_set(settings, db, sample_content):
    from datetime import UTC, datetime

    from test_pipeline import make_draft
    from veille.models import DraftStatus
    from veille.pipeline import Pipeline

    pipeline = Pipeline(settings, db)
    assert pipeline.backend == "direct"
    settings.secrets.uploadpost_api_key = "key"
    settings.secrets.public_base_url = ""  # not needed with Upload-Post
    assert pipeline.backend == "uploadpost"

    calls = []

    async def publish(content, images, platforms):
        calls.append(platforms)
        return {"threads": {"url": "u", "via": "upload-post"}, "tiktok": {"error": "quota"}}

    pipeline.uploadpost.publish = publish
    draft_id = make_draft(pipeline, sample_content, datetime.now(UTC))
    outcome = await pipeline.publish(draft_id)
    assert outcome["errors"] == ["TikTok: quota"]
    assert db.get_draft(draft_id)["status"] == DraftStatus.FAILED

    async def retry(content, images, platforms):
        calls.append(platforms)
        return {"tiktok": {"publish_id": "p", "via": "upload-post"}}

    pipeline.uploadpost.publish = retry
    await pipeline.publish(draft_id, expected=DraftStatus.FAILED)
    assert calls == [["threads", "tiktok"], ["tiktok"]]  # Threads is not posted twice
    assert db.get_draft(draft_id)["status"] == DraftStatus.PUBLISHED
    await pipeline.aclose()
