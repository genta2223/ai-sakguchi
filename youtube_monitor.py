"""
youtube_monitor.py — YouTube Live Chat Monitor for Streamlit Cloud
Runs in a background thread, pushes new comments to a shared queue.
Uses pytchat for simple, API-key-free chat polling.
"""
import logging
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue

import pytchat
import streamlit as st

from brain import filter_inappropriate_comments

logger = logging.getLogger(__name__)

COMMENT_THROTTLE_INTERVAL = 10  # seconds between processing comments


@dataclass
class ChatItem:
    """A single chat message from any source."""
    message_text: str
    author_name: str
    source: str = "youtube"  # "youtube" or "direct"
    created_at: datetime = field(default_factory=datetime.now)


def _monitor_loop(video_id: str, queue: Queue, stop_event: threading.Event):
    """
    Background thread function: poll YouTube live chat and enqueue valid messages.
    """
    logger.info(f"[YT Monitor] Starting for video_id={video_id}")

    while not stop_event.is_set():
        try:
            chat = pytchat.create(video_id=video_id)

            if not chat.is_alive():
                logger.warning("[YT Monitor] Stream not alive. Retrying in 30s...")
                stop_event.wait(30)
                continue

            logger.info("[YT Monitor] Connected to live chat.")
            last_comment_time = 0

            while chat.is_alive() and not stop_event.is_set():
                chat_data = chat.get()
                if chat_data.items:
                    now = time.time()
                    if now - last_comment_time < COMMENT_THROTTLE_INTERVAL:
                        stop_event.wait(2)
                        continue

                    message_texts = [c.message for c in chat_data.items]

                    # Filter (synchronous call inside thread)
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        valid_texts = loop.run_until_complete(
                            _async_filter(message_texts)
                        )
                        loop.close()
                    except Exception:
                        valid_texts = message_texts[:1]

                    for c in chat_data.items:
                        if c.message in valid_texts:
                            item = ChatItem(
                                message_text=c.message,
                                author_name=c.author.name,
                                source="youtube",
                            )
                            queue.put(item)
                            last_comment_time = time.time()
                            logger.info(f"[YT Monitor] Queued: {c.author.name}: {c.message[:30]}...")
                            break  # One comment per cycle

                stop_event.wait(2)

            logger.warning("[YT Monitor] Chat ended. Reconnecting in 30s...")
            stop_event.wait(30)

        except Exception as e:
            logger.error(f"[YT Monitor] Error: {e}", exc_info=True)
            stop_event.wait(30)


async def _async_filter(messages):
    """Wrapper to call async filter from sync context."""
    return filter_inappropriate_comments(messages)


def start_youtube_monitor(video_id: str, queue: Queue) -> tuple[threading.Thread, threading.Event]:
    """
    Start YouTube chat monitor in a background thread.

    Returns:
        (thread, stop_event) — call stop_event.set() to stop the monitor.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_monitor_loop,
        args=(video_id, queue, stop_event),
        daemon=True,
        name="youtube-monitor",
    )
    thread.start()
    logger.info("[YT Monitor] Thread started.")
    return thread, stop_event
