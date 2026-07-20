import re

from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watsonx_orchestrate_clients.agents.agent_client import AgentClient
from ibm_watsonx_orchestrate_clients.chat.run_client import RunClient
from ibm_watsonx_orchestrate_clients.threads.threads_client import ThreadsClient

from app.config import settings

POLL_INTERVAL_SECONDS = 2
MAX_POLL_RETRIES = 90  # ~3 minutes for the full supervisor -> collaborators -> tools chain

# Confirmed live: supervisor_agent's LLM occasionally rewrites/shortens a
# 99.co listing URL when composing its reply, dropping the "/singapore/"
# path segment despite explicit instructions not to (agents/supervisor_agent.yaml)
# — that segment is load-bearing; without it 99.co returns a real 404. Prompt
# instructions alone can't guarantee 100% compliance from a stochastic LLM, so
# this is a deterministic safety net: every genuine 99.co listing URL is
# always "https://www.99.co/singapore/sale/property/...", so any occurrence
# missing that segment is unambiguously a mangled URL, safe to repair here.
_MANGLED_99CO_URL_RE = re.compile(r"https://www\.99\.co/(?!singapore/)sale/property/")


def _fix_mangled_listing_urls(reply: str) -> str:
    return _MANGLED_99CO_URL_RE.sub("https://www.99.co/singapore/sale/property/", reply)

_agent_id_cache: str | None = None


def _get_authenticator() -> IAMAuthenticator:
    return IAMAuthenticator(apikey=settings.wxo_api_key, url=settings.wxo_iam_url or None)


def _resolve_agent_id() -> str:
    global _agent_id_cache
    if _agent_id_cache:
        return _agent_id_cache

    client = AgentClient(base_url=settings.wxo_instance_url, authenticator=_get_authenticator(), is_local=False)
    matches = client.get_draft_by_name(settings.wxo_agent_name)
    if not matches:
        raise RuntimeError(f"Agent '{settings.wxo_agent_name}' not found in the active workspace")

    _agent_id_cache = matches[0]["id"]
    return _agent_id_cache


def _extract_final_reply(messages: list[dict]) -> str:
    final_message = next(
        (m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "assistant"),
        None,
    )
    if not final_message:
        raise RuntimeError("No response received from agent")

    content = final_message.get("content", "")
    if isinstance(content, list):
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and ("text" in item or item.get("response_type") == "text")
        ]
        content = "\n".join(text_parts) if text_parts else str(content)
    return content


def send_chat_message(message: str, thread_id: str | None) -> tuple[str, str]:
    authenticator = _get_authenticator()
    run_client = RunClient(base_url=settings.wxo_instance_url, authenticator=authenticator, is_local=False)
    threads_client = ThreadsClient(base_url=settings.wxo_instance_url, authenticator=authenticator, is_local=False)

    agent_id = _resolve_agent_id()
    run = run_client.create_run(message=message, agent_id=agent_id, thread_id=thread_id)
    result_thread_id = run["thread_id"]

    run_client.wait_for_run_completion(
        run["run_id"], poll_interval=POLL_INTERVAL_SECONDS, max_retries=MAX_POLL_RETRIES
    )

    messages = threads_client.get_thread_messages(result_thread_id)
    if isinstance(messages, dict) and "data" in messages:
        messages = messages["data"]

    reply = _fix_mangled_listing_urls(_extract_final_reply(messages))
    return reply, result_thread_id
