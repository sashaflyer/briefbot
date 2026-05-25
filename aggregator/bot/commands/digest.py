"""/digest <topic_id> command handler. Runs a real digest on demand."""
from __future__ import annotations

import logging
from html import escape as _html_escape

from telegram import Update
from telegram.ext import ContextTypes

from aggregator.bot._authz import is_authorized
from aggregator.bot.digest_lock import lock_for
from aggregator.pipeline import run_digest

log = logging.getLogger(__name__)

_ERROR_MSG_MAX = 300


async def handle_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update, context):
        return

    cfg = context.bot_data["cfg"]
    storage = context.bot_data["storage"]
    args = list(context.args or [])

    if not args or args[0] not in cfg.topics:
        topics_list = ", ".join(sorted(cfg.topics.keys()))
        await update.message.reply_text(
            f"Usage: /digest <topic_id>\nConfigured topics: {topics_list}"
        )
        return

    topic_id = args[0]
    lock = lock_for(topic_id)
    # Check-then-acquire is non-atomic in general, but the Telegram polling
    # loop processes one update at a time, so two /digest invocations cannot
    # both pass this check. The lock's real purpose is the scheduler/handler
    # race, not parallel /digest calls.
    if lock.locked():
        await update.message.reply_text(
            f"Digest for {topic_id} is already running. Try again shortly."
        )
        return

    await update.message.reply_text(f"Running digest for {topic_id}…")
    async with lock:
        try:
            await run_digest(topic_id, cfg, storage, trigger="manual")
        except Exception as e:
            log.exception("/digest for %s failed", topic_id)
            msg = (str(e) or "")[:_ERROR_MSG_MAX]
            await update.message.reply_text(
                f"Digest failed: <b>{type(e).__name__}</b>: {_html_escape(msg)}",
                parse_mode="HTML",
            )
