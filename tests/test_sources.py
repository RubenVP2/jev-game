from veille.sources import extract_article, github_repo
from veille.sources.github import parse_trending
from veille.sources.hackernews import parse_hits
from veille.sources.reddit import parse_listing

TRENDING_HTML = """
<div>
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/acme/fastdb"><span>acme /</span> fastdb</a></h2>
  <p class="col-9">An embedded columnar database</p>
  <div class="f6">
    <span itemprop="programmingLanguage">Rust</span>
    <a href="/acme/fastdb/stargazers">12,345</a>
    <a href="/acme/fastdb/forks">321</a>
    <span class="d-inline-block float-sm-right">1,204 stars today</span>
  </div>
</article>
<article class="Box-row">
  <h2><a href="/solo/tool">solo / tool</a></h2>
  <div class="f6"><span>87 stars today</span></div>
</article>
</div>
"""


def test_parse_trending():
    items = parse_trending(TRENDING_HTML)
    assert [i.native_id for i in items] == ["acme/fastdb", "solo/tool"]
    first = items[0]
    assert first.score == 1204
    assert first.tags == ["Rust"]
    assert first.extra["total_stars"] == 12345
    assert first.summary == "An embedded columnar database"
    assert first.url == "https://github.com/acme/fastdb"


def test_parse_hits_falls_back_to_discussion_url():
    items = parse_hits([
        {"objectID": "1", "title": "Show HN: x", "url": "https://x.dev", "points": 300, "num_comments": 50, "created_at_i": 1_700_000_000},
        {"objectID": "2", "title": "Ask HN: y", "url": None, "points": 200, "num_comments": 10, "story_text": "<p>Body</p>"},
        {"objectID": "3", "title": None},
    ])
    assert len(items) == 2
    assert items[0].score == 300 and items[0].published_at is not None
    assert items[1].url == "https://news.ycombinator.com/item?id=2"
    assert items[1].summary == "Body"


def test_parse_listing_filters():
    listing = {"data": {"children": [
        {"data": {"id": "a", "title": "Good", "score": 500, "num_comments": 40, "permalink": "/r/rust/comments/a/good/",
                  "url": "https://blog.dev/post", "subreddit": "rust", "is_self": False}},
        {"data": {"id": "b", "title": "Low", "score": 10, "permalink": "/r/rust/comments/b/", "subreddit": "rust"}},
        {"data": {"id": "c", "title": "Pinned", "score": 900, "stickied": True, "permalink": "/r/rust/comments/c/", "subreddit": "rust"}},
        {"data": {"id": "d", "title": "Self", "score": 300, "permalink": "/r/rust/comments/d/", "subreddit": "rust", "is_self": True, "selftext": "text"}},
    ]}}
    items = parse_listing(listing, min_score=150)
    assert [i.native_id for i in items] == ["a", "d"]
    assert items[0].url == "https://blog.dev/post"
    assert items[1].url == items[1].discussion_url
    assert items[0].tags[0] == "r/rust"


def test_extract_article_keeps_main_text():
    html = """<html><body><nav>menu menu menu menu menu menu menu menu</nav>
    <article><h1>Title of the article here</h1><p>This paragraph explains the mechanism in enough words.</p>
    <script>evil()</script></article><footer>footer footer footer footer footer footer</footer></body></html>"""
    text = extract_article(html)
    assert "mechanism" in text
    assert "menu" not in text and "evil" not in text and "footer" not in text


def test_github_repo():
    assert github_repo("https://github.com/A/B/issues/3") == "a/b"
    assert github_repo("https://github.com/trending") is None
    assert github_repo("https://example.com/a/b") is None
