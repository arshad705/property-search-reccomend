import asyncio
import json

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.services import event_bus

router = APIRouter()

# Comfortably above orchestrate_service.py's own worst case
# (MAX_POLL_RETRIES * POLL_INTERVAL_SECONDS = 90*2 = 180s) so this never
# closes the stream mid-run — EventSource auto-reconnects on close, which
# would call start_session() again and silently reset the queue mid-flight.
STREAM_SAFETY_TIMEOUT_S = 220


@router.get("/chat/events", include_in_schema=False)
async def chat_events(request: Request) -> StreamingResponse:
    queue = event_bus.start_session()  # before StreamingResponse — closes the onopen race
    return StreamingResponse(_stream(request, queue), media_type="text/event-stream")


async def _stream(request: Request, queue: asyncio.Queue):
    started = asyncio.get_event_loop().time()
    while True:
        if await request.is_disconnected():
            break
        if asyncio.get_event_loop().time() - started > STREAM_SAFETY_TIMEOUT_S:
            break
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        yield f"data: {json.dumps(event)}\n\n"
