"""Quick smoke test for merge_config."""
import tomllib
from pathlib import Path

from scripts.merge_config import merge_topics

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config.example.toml"


def test_merge_adds_missing_topic(tmp_path):
    example_text = EXAMPLE.read_text(encoding="utf-8")
    lines = example_text.split("\n")
    # Find where github_trending block starts
    start = next(i for i, l in enumerate(lines) if "[topics.github_trending]" in l)
    # Remove it to simulate a live config missing that topic
    live_text = "\n".join(lines[:start]).rstrip() + "\n"

    live = tmp_path / "config.toml"
    live.write_text(live_text)
    added = merge_topics(live)
    assert added == ["github_trending"], f"expected [github_trending], got {added}"

    cfg = tomllib.loads(live.read_text(encoding="utf-8"))
    assert "github_trending" in cfg["topics"]
    assert cfg["topics"]["github_trending"]["schedule"] == "20 5,17 * * *"


def test_merge_noop_when_all_present(tmp_path):
    live = tmp_path / "config.toml"
    live.write_text(EXAMPLE.read_text(encoding="utf-8"))
    added = merge_topics(live)
    assert added == [], f"expected empty, got {added}"
