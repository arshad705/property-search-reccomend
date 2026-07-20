import type { ChatApiResponse, ThinkingEvent } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

// Opens the live tool-call event stream. Resolves once the connection is
// actually open — callers should await this before triggering the chat
// request, so no event can be published before anything is listening.
export function openChatEventStream(onEvent: (event: ThinkingEvent) => void): Promise<EventSource> {
  return new Promise((resolve) => {
    const source = new EventSource(`${API_BASE_URL}/chat/events`);
    source.onmessage = (msg) => onEvent(JSON.parse(msg.data));
    source.onopen = () => resolve(source);
  });
}

export async function sendChatMessage(
  message: string,
  threadId: string | null,
): Promise<ChatApiResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Chat request failed with status ${response.status}`);
  }

  return response.json() as Promise<ChatApiResponse>;
}
