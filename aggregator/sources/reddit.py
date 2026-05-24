"""Reddit source adapter.

The hot-listing path (`_fetch_subreddit`) hits Reddit's public
`/r/<sub>/hot.json` endpoint directly. The vendored upstream module's `search`
is used only for symbol-targeted queries (`_search_reddit`).

Module-level `_fetch_subreddit` / `_search_reddit` are kept as patchable
indirections so tests can mock without touching the network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from aggregator.sources.base import Item, Source
from aggregator.vendor.last30days import reddit_public

log = logging.getLogger(__name__)


def _user_agent() -> str:
    """Reddit explicitly blocks generic UAs. Honor REDDIT_USER_AGENT from .env."""
    return os.environ.get("REDDIT_USER_AGENT", "news-aggregator/0.1")


def _fetch_subreddit(sub: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch /r/<sub>/hot.json directly. Returns dicts in the shape `_to_item` expects.

    Public endpoint — no OAuth required. Rate limit is ~10 req/min anonymous;
    for a once-daily digest pulling a handful of subs this is fine.
    """
    capped = max(1, min(int(limit), 100))
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit={capped}"
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log.warning("reddit hot fetch failed for r/%s: %s", sub, e)
        return []

    posts: list[dict[str, Any]] = []
    for child in raw.get("data", {}).get("children", []):
        p = child.get("data", {})
        permalink = p.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink else (p.get("url") or "")
        posts.append({
            "reddit_id": p.get("id"),
            "title": p.get("title", ""),
            "url": url,
            "selftext": p.get("selftext", ""),
            "created_utc": p.get("created_utc"),
            "score": p.get("score", 0),
            "num_comments": p.get("num_comments", 0),
            "subreddit": p.get("subreddit", sub),
            "author": p.get("author", ""),
            "engagement": {
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "upvote_ratio": p.get("upvote_ratio"),
            },
        })
    return posts


def _search_reddit(query: str, limit: int = 15) -> list[dict[str, Any]]:
    """Search Reddit globally for a query. Used for symbol-targeted watchlist queries."""
    return reddit_public.search(query=query, depth="default")[:limit]


def _parse_created_at(raw: dict[str, Any]) -> datetime:
    """Extract a UTC datetime from upstream post dict.

    Upstream consistently sets ``created_utc`` as a float epoch; ``date`` as
    YYYY-MM-DD is also present. Fall back to ``created_at`` ISO if needed.
    """
    epoch = raw.get("created_utc")
    if epoch:
        try:
            return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    iso = raw.get("created_at")
    if iso:
        try:
            s = str(iso).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    return datetime.now(timezone.utc)


def _to_item(raw: dict[str, Any]) -> Item:
    """Map an upstream post dict to our Item."""
    url = str(raw.get("url", ""))
    # Derive a stable id from the URL (upstream "R1"/"R2" ids are not stable).
    raw_id = str(raw.get("reddit_id") or raw.get("id") or url)
    upstream_engagement = raw.get("engagement") or {}
    score = upstream_engagement.get("score", raw.get("score", 0))
    num_comments = upstream_engagement.get("num_comments", raw.get("num_comments", 0))

    return Item(
        id=f"reddit:{raw_id}",
        source="reddit",
        title=str(raw.get("title", "")).strip(),
        url=url,
        text=str(raw.get("selftext", "")),
        created_at=_parse_created_at(raw),
        engagement_raw={
            "score": score,
            "upvotes": score,
            "comments": num_comments,
            "upvote_ratio": upstream_engagement.get("upvote_ratio"),
        },
        metadata={
            "subreddit": raw.get("subreddit", ""),
            "author": raw.get("author", ""),
        },
    )


class RedditSource(Source):
    name = "reddit"

    async def fetch(self, queries: dict[str, Any]) -> list[Item]:
        subreddits = queries.get("subreddits") or []
        symbols = queries.get("symbols") or []

        if not subreddits and not symbols:
            return []

        items: list[Item] = []

        for sub in subreddits:
            raws = await asyncio.to_thread(_fetch_subreddit, sub, 25)
            items.extend(_to_item(r) for r in raws)

        for sym in symbols:
            raws = await asyncio.to_thread(_search_reddit, sym, 15)
            items.extend(_to_item(r) for r in raws)

        return items
