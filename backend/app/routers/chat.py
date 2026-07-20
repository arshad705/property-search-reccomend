from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services import event_bus
from app.services.orchestrate_service import send_chat_message

router = APIRouter()


@router.post(
    "/chat/message",
    response_model=ChatResponse,
    description="Send a free-text message to the supervisor_agent running in watsonx Orchestrate and return its reply.",
    include_in_schema=False,  # frontend-only endpoint, not meant to be imported as an agent tool
)
def send_chat_message_endpoint(request: ChatRequest) -> ChatResponse:
    # Published the moment the request lands, so the thinking panel has a real
    # first line immediately. Without this, the first visible event only
    # arrives when Orchestrate makes its first tool call — 5-15s of bare
    # "Thinking..." on a fresh chat while the supervisor's LLM parses the
    # request and transfers to a collaborator.
    event_bus.publish("supervisor", "start", "Analyzing your request and coordinating the advisor agents...")
    try:
        reply, thread_id = send_chat_message(request.message, request.thread_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(reply=reply, thread_id=thread_id)
