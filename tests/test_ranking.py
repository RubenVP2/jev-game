from datetime import UTC, datetime, timedelta

from veille.models import Item
from veille.ranking import Triage, TriageEntry, drop_covered, editorial_triage, heuristic_score, merge, rank


def item(source, nid, url, title="t", score=100, comments=0, age_h=None):
    published = datetime.now(UTC) - timedelta(hours=age_h) if age_h is not None else None
    return Item(source=source, native_id=nid, url=url, discussion_url=url, title=title, score=score,
                comments=comments, published_at=published)


def test_merge_groups_same_story_and_prefers_discussion_source():
    gh = item("github", "acme/db", "https://github.com/acme/db", score=900)
    hn = item("hackernews", "1", "https://github.com/acme/db/", score=300)
    other = item("reddit", "x", "https://blog.dev/a")
    candidates = merge([gh, hn, other])
    assert len(candidates) == 2
    merged = next(c for c in candidates if c.related)
    assert merged.item.source == "hackernews"
    assert merged.sources == {"hackernews", "github"}


def test_cross_source_and_freshness_raise_score():
    solo = merge([item("hackernews", "1", "https://a.dev", score=300, age_h=1)])[0]
    double = merge([item("hackernews", "2", "https://b.dev", score=300, age_h=1),
                    item("reddit", "r", "https://b.dev", score=300, age_h=1)])[0]
    old = merge([item("hackernews", "3", "https://c.dev", score=300, age_h=72)])[0]
    assert heuristic_score(double) > heuristic_score(solo) > heuristic_score(old)


def test_drop_covered_by_url_title_and_rejection():
    candidates = merge([
        item("hackernews", "1", "https://a.dev/post", title="Postgres 18 ships async IO"),
        item("hackernews", "2", "https://b.dev/other", title="Postgres 18 ships async I/O"),
        item("hackernews", "3", "https://c.dev", title="Unrelated story about compilers"),
        item("hackernews", "4", "https://d.dev", title="Rejected before"),
    ])
    kept = drop_covered(candidates, [("https://a.dev/post", "Postgres 18 ships async IO")], {"hackernews:4"})
    assert [c.item.native_id for c in kept] == ["3"]


class FakeLLM:
    def __init__(self, triage):
        self.triage = triage

    async def complete_json(self, *args, **kwargs):
        return self.triage


async def test_editorial_triage_reorders_and_zeroes_missing():
    items = [item("hackernews", str(i), f"https://{i}.dev", title=f"story {i}", score=1000 - i * 100) for i in range(3)]
    triage = Triage(ranking=[TriageEntry(index=2, technical_depth=10, novelty=10, audience_fit=10, angle="deep")])
    ranked = await rank(FakeLLM(triage), items, [], set(), shortlist_size=10)
    assert ranked[0].item.native_id == "2"
    assert ranked[0].angle == "deep"
    assert all(c.editorial == 0.0 for c in ranked[1:])


async def test_triage_failure_keeps_heuristic_order():
    from veille.llm import LLMError

    class Failing:
        async def complete_json(self, *a, **k):
            raise LLMError("down")

    candidates = merge([item("hackernews", "1", "https://a.dev", score=100), item("hackernews", "2", "https://b.dev", score=900)])
    await editorial_triage(Failing(), candidates)
    assert all(c.editorial is None for c in candidates)
    ranked = await rank(None, [c.item for c in candidates], [], set(), 10)
    assert ranked[0].item.native_id == "2"
