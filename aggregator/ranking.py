"""Scoring, dedup, and ranking functions extracted from pipeline.py."""
from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING, Any

from aggregator.sources.base import Item
from aggregator.vendor.last30days import dedupe as _dedupe
from aggregator.vendor.last30days import schema as _schema

if TYPE_CHECKING:
    from aggregator.config import Config

log = logging.getLogger(__name__)


def item_to_source_item(item: Item) -> "_schema.SourceItem":
    """Convert our Item -> upstream SourceItem just enough for dedupe."""
    return _schema.SourceItem(
        item_id=item.id,
        source=item.source,
        title=item.title,
        body=item.text,
        url=item.url,
        author=str(item.metadata.get("author") or "") or None,
        container=None,
    )


def safe_log1p(value: float | int | None) -> float:
    """math.log1p clamped to non-negative inputs."""
    return math.log1p(max(0, value or 0))


def engagement_score(item: Item, *, scoring: "Config | None" = None) -> float:
    """Single sortable engagement number.

    Per-source weights from vendored signals.py override global config weights
    when available. log1p scaling prevents high-engagement outliers from
    dominating. Final score is multiplied by source quality.
    """
    from aggregator.config import ScoringConfig

    raw = item.engagement_raw
    source = item.source

    # Per-source engagement weights. These could be moved to ScoringConfig
    # if different operators want different source priorities.
    per_source: dict[str, list[tuple[str, float]]] = {
        "hackernews":  [("points", 0.55), ("comments", 0.45)],
        "polymarket":  [("volume", 0.60), ("liquidity", 0.40)],
        "github":      [("stars", 0.80), ("forks", 0.20)],
    }

    weights = per_source.get(source)
    if weights:
        score = sum(
            w * safe_log1p(raw.get(field))
            for field, w in weights
        )
    else:
        w_up = scoring.weight_upvotes if scoring else 1.0
        w_sc = scoring.weight_score if scoring else 1.0
        w_co = scoring.weight_comments if scoring else 0.1
        w_vo = scoring.weight_volume if scoring else 0.001
        score = (
            w_up * safe_log1p(raw.get("upvotes"))
            + w_sc * safe_log1p(raw.get("score"))
            + w_co * safe_log1p(raw.get("comments"))
            + w_vo * safe_log1p(raw.get("volume"))
        )

    source_quality: dict[str, float] = {
        "hackernews": 0.8,
        "polymarket": 0.5,
        "github": 0.7,
    }
    score *= source_quality.get(source, 0.6)

    return score


def cap_per_symbol(
    items: list[Item],
    canonical_symbols: list[str],
    alias_map: dict[str, str],
    per_symbol_top_n: int,
) -> list[Item]:
    """Group items by canonical ticker; keep at most ``per_symbol_top_n`` each."""
    buckets: dict[str, list[Item]] = {sym: [] for sym in canonical_symbols}
    canon_lower = {s.lower(): s for s in canonical_symbols}
    alias_patterns = {
        alias: re.compile(rf"\b{re.escape(alias)}\b")
        for alias in alias_map
    }
    for it in items:
        matched = None
        tag = (it.metadata.get("watchlist_symbol") or "").strip().lower()
        if tag and tag in canon_lower:
            matched = canon_lower[tag]
        else:
            text = f"{it.title} {it.text or ''}".lower()
            for alias_lower, canon in alias_map.items():
                if alias_patterns[alias_lower].search(text):
                    matched = canon
                    break
        if matched is None:
            continue
        if len(buckets[matched]) < per_symbol_top_n:
            buckets[matched].append(it.with_metadata(watchlist_symbol=matched))
    out: list[Item] = []
    for sym in canonical_symbols:
        out.extend(buckets[sym])
    return out


def score_and_dedup(items: list[Item], *, top_n: int,
                    scoring: "Config | None" = None) -> list[Item]:
    """Sort by engagement, dedupe, truncate to top_n."""
    if not items:
        return []

    ranked_first = sorted(items, key=lambda it: engagement_score(it, scoring=scoring), reverse=True)

    pre_cap = max(top_n * 10, 200)
    if len(ranked_first) > pre_cap:
        log.info("pre-truncating %d -> %d items before dedup", len(ranked_first), pre_cap)
        ranked_first = ranked_first[:pre_cap]

    by_id = {item.id: item for item in ranked_first}
    source_items = [item_to_source_item(it) for it in ranked_first]
    try:
        deduped = _dedupe.dedupe_items(source_items, threshold=0.7)
    except Exception:
        log.exception("upstream dedupe_items failed; falling back to raw items")
        deduped = source_items

    deduped_items = [by_id[si.item_id] for si in deduped if si.item_id in by_id]
    log.info("dedupe: %d -> %d items", len(items), len(deduped_items))

    return deduped_items[:top_n]
