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
