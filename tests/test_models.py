import pytest
from pydantic import ValidationError

from veille.models import PostContent, ThreadsCopy, canonical_url, threads_length


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/Owner/Repo/tree/main/docs", "https://github.com/owner/repo"),
        ("http://www.example.com/post/?utm_source=hn&id=3", "https://example.com/post?id=3"),
        ("https://m.example.com/a/", "https://example.com/a"),
    ],
)
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected


def test_threads_length_counts_emoji_bytes():
    assert threads_length("abc") == 3
    assert threads_length("🚀") == 4


def test_threads_copy_rejects_over_limit():
    with pytest.raises(ValidationError):
        ThreadsCopy(post="x" * 501, reply="ok")


def test_post_content_requires_cover_and_verdict(sample_content):
    data = sample_content.model_dump()
    data["slides"] = data["slides"][1:]
    with pytest.raises(ValidationError, match="cover"):
        PostContent.model_validate(data)
    data = sample_content.model_dump()
    data["slides"] = data["slides"][:-1]
    with pytest.raises(ValidationError, match="verdict"):
        PostContent.model_validate(data)


def test_secrets_tolerate_empty_values_and_derive_urls(monkeypatch):
    from veille.config import Secrets

    monkeypatch.setenv("DISCORD_CHANNEL_ID", "")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_IDS", "12, 34,")
    monkeypatch.setenv("DOMAIN", "veille.test")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("TIKTOK_REDIRECT_URI", raising=False)
    secrets = Secrets(_env_file=None)
    assert secrets.channel_id == 0
    assert secrets.allowed_user_ids == {12, 34}
    assert secrets.public_base_url == "https://veille.test"
    assert secrets.tiktok_redirect_uri == "https://veille.test/tiktok/callback"
