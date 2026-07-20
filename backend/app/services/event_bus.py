import asyncio
import itertools
import time
from typing import Optional

_loop: Optional[asyncio.AbstractEventLoop] = None
_queue: Optional[asyncio.Queue] = None
_seq = itertools.count()


def start_session() -> asyncio.Queue:
    """Call synchronously from the /chat/events endpoint's function body —
    NOT from inside its generator — so the queue exists before the
    StreamingResponse (and therefore HTTP headers) are sent to the browser.
    Single global session: not safe for multiple concurrent users/tabs,
    accepted tradeoff for this single-session app. A dropped/reconnected
    SSE connection resets this queue — any tool-call events published in
    the gap are silently lost, an accepted limitation of this design.
    """
    global _loop, _queue
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue()
    return _queue


def publish(agent: str, status: str, message: str) -> None:
    """Thread-safe — called from FastAPI's sync threadpool workers (the
    /tools/* handlers). No-op if no SSE client is currently connected.
    """
    if _loop is None or _queue is None:
        return
    event = {"id": next(_seq), "agent": agent, "status": status, "message": message, "ts": time.time()}
    _loop.call_soon_threadsafe(_queue.put_nowait, event)
