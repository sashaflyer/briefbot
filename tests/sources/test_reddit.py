import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aggregator.sources.reddit import RedditSource

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_subreddit_hot.json"


@pytest.mark.asyncio
async def test_fetch_returns_items_from_subreddits():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    with patch("aggregator.sources.reddit._fetch_subreddit", return_value=fixture):
        src = RedditSource()
        items = await src.fetch({
            "subreddits": ["CryptoCurrency"],
            "polymarket_tags": [],
        })

    assert len(items) > 0
    assert all(it.source == "reddit" for it in items)
    assert all(it.id.startswith("reddit:") for it in items)
    assert all(it.url.startswith("http") for it in items)
    assert all("upvotes" in it.engagement_raw or "score" in it.engagement_raw
               for it in items)


@pytest.mark.asyncio
async def test_fetch_handles_empty_subreddit_list():
    src = RedditSource()
    items = await src.fetch({"subreddits": []})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_with_symbol_queries():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with patch("aggregator.sources.reddit._search_reddit", return_value=fixture):
        src = RedditSource()
        items = await src.fetch({"symbols": ["SOL"]})
    assert all(it.source == "reddit" for it in items)


def test_fetch_subreddit_hits_hot_json_and_transforms():
    """Verify the new direct-hit /r/<sub>/hot.json fetcher shapes output correctly."""
    import io
    import json as _json
    from unittest.mock import patch

    from aggregator.sources.reddit import _fetch_subreddit

    fake_reddit_json = {
        "data": {
            "children": [
                {"data": {
                    "id": "abc123",
                    "title": "Bitcoin hit $200k today",
                    "permalink": "/r/CryptoCurrency/comments/abc123/title/",
                    "url": "https://external.example.com/something",
                    "selftext": "body text here",
                    "created_utc": 1716700000.0,
                    "score": 1234,
                    "num_comments": 56,
                    "subreddit": "CryptoCurrency",
                    "author": "satoshi_jr",
                    "upvote_ratio": 0.95,
                }},
                {"data": {
                    "id": "def456",
                    "title": "Daily discussion",
                    "permalink": "/r/CryptoCurrency/comments/def456/title/",
                    "url": "",
                    "selftext": "",
                    "created_utc": 1716800000.0,
                    "score": 50,
                    "num_comments": 200,
                    "subreddit": "CryptoCurrency",
                    "author": "AutoModerator",
                    "upvote_ratio": 1.0,
                }},
            ]
        }
    }

    class FakeResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return _json.dumps(self._data).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp(fake_reddit_json)) as mock_url:
        posts = _fetch_subreddit("CryptoCurrency", limit=25)

    # URL hit was /hot.json with the right sub.
    req = mock_url.call_args.args[0]
    assert "/r/CryptoCurrency/hot.json" in req.full_url
    assert "limit=25" in req.full_url
    # User-Agent header set.
    assert "news-aggregator" in req.get_header("User-agent", "")

    # Shape: 2 posts, each with reddit_id and full reddit.com URL constructed from permalink.
    assert len(posts) == 2
    assert posts[0]["reddit_id"] == "abc123"
    assert posts[0]["url"] == "https://www.reddit.com/r/CryptoCurrency/comments/abc123/title/"
    assert posts[0]["engagement"]["score"] == 1234
    assert posts[0]["engagement"]["upvote_ratio"] == 0.95
    assert posts[1]["author"] == "AutoModerator"


def test_fetch_subreddit_returns_empty_on_network_error():
    import urllib.error
    from unittest.mock import patch
    from aggregator.sources.reddit import _fetch_subreddit

    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("connection refused")):
        posts = _fetch_subreddit("CryptoCurrency", limit=25)
    assert posts == []
