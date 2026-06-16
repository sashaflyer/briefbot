"""One-shot patch: drop 7 known-dead RSS feeds from config.toml.

Run on the VPS as news-bot:

    sudo -u news-bot /opt/news-aggregator/.venv/bin/python /tmp/drop_dead_feeds.py \
        --config /opt/news-aggregator/config.toml

Writes config.toml.bak first, then removes the listed URLs from every
[topics.*].rss_feeds list, then prints a summary. Idempotent: re-running
after the first run is a no-op (no matches → no changes).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path

DEAD_FEEDS = [
    "https://lcamtuf.substack.com/feed",
    "https://www.joanwestenberg.com/rss",
    "https://rachelbythebay.com/w/atom.xml",
    "https://garymarcus.substack.com/feed",
    "https://worksonmymachine.substack.com/feed",
    "https://blog.pixelmelt.dev/rss/",
    "https://gwern.substack.com/feed",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    path = Path(args.config)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    dead = set(DEAD_FEEDS)
    removed_total = 0
    affected_topics: list[str] = []

    for name, topic in raw.get("topics", {}).items():
        feeds = topic.get("rss_feeds") or []
        kept = [u for u in feeds if u not in dead]
        if len(kept) != len(feeds):
            topic["rss_feeds"] = kept
            removed_total += len(feeds) - len(kept)
            affected_topics.append(name)

    if removed_total == 0:
        print("No dead feeds found — already clean.")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)

    text = path.read_text(encoding="utf-8")

    def sub(m: re.Match) -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        kept_lines = []
        for line in body.splitlines(keepends=True):
            stripped = line.split("#", 1)[0]
            urls = _QUOTED.findall(stripped)
            if not urls:
                kept_lines.append(line)
                continue
            if all(u in dead for u in urls):
                continue
            new_line, _ = _drop_dead_from_line(line, dead)
            kept_lines.append(new_line)
        return f"{head}{''.join(kept_lines)}{tail}"

    new_text = re.sub(
        r"(?ms)(rss_feeds\s*=\s*\[)([^\]]*?)(\])",
        sub, text,
    )
    path.write_text(new_text, encoding="utf-8")
    print(f"Removed {removed_total} dead feed(s) from topics: {affected_topics}")
    print(f"Backup: {backup}")
    print(f"Patched: {path}")
    return 0


_QUOTED = re.compile(r"""['"]([^'"]+?)['"]""")


def _drop_dead_from_line(line: str, dead: set[str]) -> tuple[str, int]:
    parts: list[str] = []
    removed = 0
    last = 0
    for m in _QUOTED.finditer(line):
        if m.group(1) in dead:
            parts.append(line[last:m.start()])
            last = m.end()
            removed += 1
    parts.append(line[last:])
    return "".join(parts), removed


if __name__ == "__main__":
    sys.exit(main())
