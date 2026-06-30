import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aggregator.sources.github import GithubSource, _to_item

FIXTURE = Path(__file__).parent / "fixtures" / "github_search.json"


@pytest.mark.asyncio
async def test_fetch_with_github_keywords():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls = []

    async def capture(client, query, token, days=7):
        calls.append(query)
        return fixture["items"]

    with patch("aggregator.sources.github._resolve_token", return_value="fake"):
        with patch("aggregator.sources.github._search_github", side_effect=capture):
            src = GithubSource()
            items = await src.fetch({
                "github_keywords": ["ethereum", "bitcoin"],
            })

    assert calls == ["ethereum", "bitcoin"]
    assert len(items) == 2
    assert all(it.source == "github" for it in items)
    assert all(it.id.startswith("github:") for it in items)


@pytest.mark.asyncio
async def test_fetch_falls_back_to_hn_keywords():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls = []

    async def capture(client, query, token, days=7):
        calls.append(query)
        return fixture["items"]

    with patch("aggregator.sources.github._resolve_token", return_value="fake"):
        with patch("aggregator.sources.github._search_github", side_effect=capture):
            src = GithubSource()
            items = await src.fetch({
                "hn_keywords": ["bitcoin"],
                # no github_keywords
            })

    assert calls == ["bitcoin"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_with_symbols():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls = []

    async def capture(client, query, token, days=7):
        calls.append(query)
        return fixture["items"]

    with patch("aggregator.sources.github._resolve_token", return_value="fake"):
        with patch("aggregator.sources.github._search_github", side_effect=capture):
            src = GithubSource()
            await src.fetch({"symbols": ["SOL", "SUI"]})

    assert calls == ["SOL", "SUI"]


@pytest.mark.asyncio
async def test_fetch_skips_when_no_token():
    with patch("aggregator.sources.github._resolve_token", return_value=None):
        src = GithubSource()
        items = await src.fetch({"github_keywords": ["bitcoin"]})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_with_empty_queries_returns_empty():
    src = GithubSource()
    assert await src.fetch({}) == []
    assert await src.fetch({"github_keywords": [], "symbols": []}) == []


@pytest.mark.asyncio
async def test_fetch_deduplicates_across_queries():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def capture(client, query, token, days=7):
        return fixture["items"]

    with patch("aggregator.sources.github._resolve_token", return_value="fake"):
        with patch("aggregator.sources.github._search_github", side_effect=capture):
            src = GithubSource()
            items = await src.fetch({
                "github_keywords": ["ethereum", "bitcoin"],
            })

    # Same items returned for both queries; dedup should collapse to 2.
    assert len(items) == 2


def test_to_item_maps_repo_fields():
    raw = {
        "id": 999,
        "full_name": "test/repo",
        "html_url": "https://github.com/test/repo",
        "description": "A test repository",
        "stargazers_count": 1234,
        "forks_count": 567,
        "open_issues_count": 42,
        "language": "Python",
        "topics": ["python", "testing"],
        "pushed_at": "2026-06-16T12:00:00Z",
        "created_at": "2020-01-01T00:00:00Z",
        "owner": {"login": "testuser"},
    }
    item = _to_item(raw)
    assert item is not None
    assert item.title == "test/repo"
    assert item.text == "A test repository"
    assert item.engagement_raw["stars"] == 1234
    assert item.engagement_raw["forks"] == 567
    assert item.engagement_raw["open_issues"] == 42
    assert item.metadata["owner"] == "testuser"
    assert item.metadata["language"] == "Python"
    assert item.metadata["topics"] == ["python", "testing"]
    assert item.metadata["pushed_at"] == "2026-06-16T12:00:00+00:00"


def test_to_item_truncates_long_description():
    raw = {
        "id": 1,
        "full_name": "x/y",
        "html_url": "https://github.com/x/y",
        "description": "A" * 500,
        "stargazers_count": 10,
        "forks_count": 2,
        "open_issues_count": 0,
        "language": "Go",
        "topics": [],
        "pushed_at": "2026-06-16T12:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "owner": {"login": "u"},
    }
    item = _to_item(raw)
    assert item is not None
    assert len(item.text) == 300


def test_to_item_returns_none_without_url():
    raw = {"id": 1, "full_name": "x/y", "created_at": "2026-06-16T12:00:00Z"}
    assert _to_item(raw) is None


def test_to_item_returns_none_without_date():
    raw = {"id": 1, "html_url": "https://github.com/x/y", "full_name": "x/y"}
    assert _to_item(raw) is None


def test_to_item_parses_created_at_as_aware_datetime():
    raw = {
        "id": 1,
        "full_name": "x/y",
        "html_url": "https://github.com/x/y",
        "description": "",
        "stargazers_count": 0,
        "forks_count": 0,
        "open_issues_count": 0,
        "language": "",
        "topics": [],
        "pushed_at": "2026-06-16T12:00:00Z",
        "created_at": "2026-06-16T12:00:00Z",
        "owner": {"login": "u"},
    }
    item = _to_item(raw)
    assert item is not None
    assert item.created_at.year == 2026
    assert item.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_fetch_subquery_failure_does_not_kill_batch():
    async def side_effect(client, query, token, days=7):
        if query == "fail":
            raise RuntimeError("boom")
        return []

    with patch("aggregator.sources.github._resolve_token", return_value="fake"):
        with patch("aggregator.sources.github._search_github", side_effect=side_effect):
            src = GithubSource()
            items = await src.fetch({
                "github_keywords": ["fail", "bitcoin"],
            })
    # Should not raise; "fail" is logged as a warning, "bitcoin" returns empty.
    assert items == []
