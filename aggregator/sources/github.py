"""GitHub source adapter — searches repositories via the GitHub Search API.

Uses ``api.github.com/search/repositories`` (free, rate-limited to 10 req/min
for authenticated users). Auth via ``GITHUB_TOKEN`` env var or
``gh auth token`` CLI fallback.

Network model: one ``httpx.AsyncClient`` per ``fetch()`` call, fanning out
concurrently. All keyword subqueries share the client's connection pool,
so requests to the same host reuse a TCP/TLS connection. This matches the
RSS adapter's async-first pattern and avoids wasting thread-pool slots on
I/O-bound HTTP waits.

Test seam: ``_search_github`` is the async entrypoint; tests patch it to
return canned item lists without network.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from aggregator.sources.base import Item, Source

log = logging.getLogger(__name__)

_SEARCH_URL = "https://api.github.com/search/repositories"
_USER_AGENT = "briefbot/0.2"
_HTTP_TIMEOUT_S = 15.0
# Per-keyword result cap. Keeps the pipeline bounded while still surfacing
# the most-engaged items. 15 matches the HN adapter's default.
_PER_QUERY_LIMIT = 15


def _resolve_token() -> str | None:
    """Resolve GitHub auth token from env or ``gh`` CLI."""
    env_token = os.environ.get("GITHUB_TOKEN")
    if env_token:
        return env_token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


async def _search_github(
    client: httpx.AsyncClient, query: str, token: str, days: int = 7,
) -> list[dict[str, Any]]:
    """Search GitHub repositories for *query* with recent activity.

    Returns a list of raw GitHub Search API item dicts. Returns an empty
    list on any failure (auth, network, rate-limit).

    Repos are filtered to those pushed in the last *days* days and sorted
    by stars (most popular first).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"{query} pushed:>{since}"
    params = urllib.parse.urlencode({
        "q": q,
        "sort": "stars",
        "order": "desc",
        "per_page": str(_PER_QUERY_LIMIT),
    })
    url = f"{_SEARCH_URL}?{params}"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        log.warning("github HTTP %d: %s", e.response.status_code, url)
        return []
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
        log.warning("github fetch error: %s", e)
        return []
    if not isinstance(data, dict):
        return []
    return data.get("items", [])


def _to_item(raw: dict[str, Any]) -> Item | None:
    """Map a GitHub Search API repo item to our Item. Returns None if unparseable."""
    html_url = raw.get("html_url", "")
    if not html_url:
        return None

    created_at_str = raw.get("created_at")
    if not created_at_str:
        return None
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

    full_name = raw.get("full_name", "")
    title = full_name or raw.get("name", "")
    description = (raw.get("description") or "").strip()
    language = raw.get("language") or ""
    topics = raw.get("topics") or []
    stars = raw.get("stargazers_count", 0) or 0
    forks = raw.get("forks_count", 0) or 0
    open_issues = raw.get("open_issues_count", 0) or 0
    pushed_at_str = raw.get("pushed_at")
    pushed_at = None
    if pushed_at_str:
        try:
            pushed_at = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    owner = ""
    owner_obj = raw.get("owner")
    if isinstance(owner_obj, dict):
        owner = owner_obj.get("login", "")

    native_id = str(raw.get("id") or html_url)

    return Item(
        id=f"github:{native_id}",
        source="github",
        title=title,
        url=html_url,
        text=description[:300] if description else "",
        created_at=created_at,
        engagement_raw={
            "stars": stars,
            "forks": forks,
            "open_issues": open_issues,
        },
        metadata={
            "owner": owner,
            "language": language,
            "topics": topics,
            "pushed_at": pushed_at.isoformat() if pushed_at else None,
        },
    )


class GithubSource(Source):
    name = "github"

    async def fetch(self, queries: dict[str, Any]) -> list[Item]:
        keywords = queries.get("github_keywords") or queries.get("hn_keywords") or []
        symbols = queries.get("symbols") or []
        all_queries = list(keywords) + list(symbols)
        if not all_queries:
            return []

        token = await asyncio.to_thread(_resolve_token)
        if not token:
            log.info("github: no GITHUB_TOKEN or gh CLI; skipping")
            return []

        timeout = httpx.Timeout(_HTTP_TIMEOUT_S)
        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(
                *(_search_github(client, q, token) for q in all_queries),
                return_exceptions=True,
            )
        items: list[Item] = []
        seen_ids: set[str] = set()
        for raws in results:
            if isinstance(raws, Exception):
                log.warning("github subquery failed: %s", raws)
                continue
            for r in raws:
                it = _to_item(r)
                if it is not None and it.id not in seen_ids:
                    seen_ids.add(it.id)
                    items.append(it)
        return items
