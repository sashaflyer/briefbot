"""Session-wide pytest fixtures.

Reddit's module-level ``USER_AGENT`` (see ``aggregator/sources/reddit.py``) hard-fails
import when neither ``REDDIT_USER_AGENT`` nor ``REDDIT_OWNER_HANDLE`` is set.
The full test suite imports the reddit source transitively at collection time,
so we inject a benign handle at conftest *import* time (before any test module
is imported, before any fixture runs).

Tests that exercise the validation itself (``test_reddit_user_agent_requires_handle``)
explicitly ``monkeypatch.delenv`` these vars and reload the module.
"""
from __future__ import annotations

import os

# Must run at import time, not in a fixture — pytest collection imports test
# modules (which transitively import aggregator.sources.reddit) before any
# fixtures execute.
os.environ.setdefault("REDDIT_OWNER_HANDLE", "test-handle")
