"""Tests for the one-shot drop_dead_feeds VPS patch script."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import drop_dead_feeds  # noqa: E402


def _write_cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_removes_dead_feeds_from_ai_blogs(tmp_path):
    cfg = _write_cfg(tmp_path,
        '[topics.ai_blogs]\nkind = "general"\nsources = ["rss"]\n'
        'rss_feeds = [\n  "https://simonwillison.net/atom/everything/",\n'
        '  "https://lcamtuf.substack.com/feed",\n'
        '  "https://gwern.substack.com/feed",\n'
        '  "https://krebsonsecurity.com/feed/",\n'
        ']\n'
        'prompt_template = "ai_blogs.md"\ntop_n = 25\nschedule = "5 5,17 * * *"\n')
    # call directly with a patched sys.argv
    import sys as _s
    old = _s.argv
    _s.argv = ["drop_dead_feeds", "--config", str(cfg)]
    try:
        drop_dead_feeds.main()
    finally:
        _s.argv = old
    new = cfg.read_text(encoding="utf-8")
    assert "lcamtuf" not in new
    assert "gwern" not in new
    assert "simonwillison" in new
    assert "krebsonsecurity" in new
    assert (tmp_path / "config.toml.bak").exists()


def test_idempotent_when_no_dead_feeds(tmp_path, capsys):
    cfg = _write_cfg(tmp_path,
        '[topics.ai_blogs]\nkind = "general"\nsources = ["rss"]\n'
        'rss_feeds = ["https://simonwillison.net/atom/everything/"]\n'
        'prompt_template = "ai_blogs.md"\ntop_n = 25\nschedule = "5 5,17 * * *"\n')
    import sys as _s
    old = _s.argv
    _s.argv = ["drop_dead_feeds", "--config", str(cfg)]
    try:
        drop_dead_feeds.main()
    finally:
        _s.argv = old
    out = capsys.readouterr().out
    assert "already clean" in out
    assert not (tmp_path / "config.toml.bak").exists()


def test_preserves_other_topics(tmp_path):
    cfg = _write_cfg(tmp_path,
        '[topics.crypto_general]\nkind = "general"\nsources = ["rss"]\n'
        'rss_feeds = ["https://cointelegraph.com/rss"]\n'
        'prompt_template = "general_crypto.md"\ntop_n = 15\nschedule = "10 5,17 * * *"\n'
        '[topics.ai_blogs]\nkind = "general"\nsources = ["rss"]\n'
        'rss_feeds = ["https://gwern.substack.com/feed", "https://krebsonsecurity.com/feed/"]\n'
        'prompt_template = "ai_blogs.md"\ntop_n = 25\nschedule = "5 5,17 * * *"\n')
    import sys as _s
    old = _s.argv
    _s.argv = ["drop_dead_feeds", "--config", str(cfg)]
    try:
        drop_dead_feeds.main()
    finally:
        _s.argv = old
    new = cfg.read_text(encoding="utf-8")
    assert "cointelegraph.com" in new
    assert "krebsonsecurity" in new
    assert "gwern" not in new
