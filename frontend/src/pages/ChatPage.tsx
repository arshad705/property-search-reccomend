import { useEffect, useRef, useState } from "react";
import { openChatEventStream, sendChatMessage } from "../api/client";
import { ChatMessageBubble } from "../components/ChatMessageBubble";
import { ThinkingPanel } from "../components/ThinkingPanel";
import type { ChatMessage, ThinkingEvent } from "../types";

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Hi! Tell me what kind of HDB resale flat you're looking for — e.g. *\"4-room flat near Bishan MRT under $850k\"* — and I'll find live listings, check if they're fairly priced, and see what's nearby.",
};

// How far from the bottom (px) the user can be and still get auto-scrolled.
// Beyond this they've deliberately scrolled up to read something — don't yank them back.
const SCROLL_SNAP_THRESHOLD_PX = 120;

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [thinkingEvents, setThinkingEvents] = useState<ThinkingEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const messageIdCounter = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatHistoryRef = useRef<HTMLDivElement>(null);

  function nextId(): string {
    messageIdCounter.current += 1;
    return `msg-${messageIdCounter.current}`;
  }

  // Scroll to bottom only when the user is already near the bottom — so
  // expanding and reading a previous thinking panel isn't interrupted.
  function scrollIfNearBottom() {
    const el = chatHistoryRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom <= SCROLL_SNAP_THRESHOLD_PX) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }

  // Always scroll on new messages and isSending toggle (user just sent
  // something — always bring them to the bottom for that).
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSending]);

  // Scroll to follow live panel growth, but only if already near the bottom.
  useEffect(() => {
    if (isSending) scrollIfNearBottom();
  }, [thinkingEvents, isSending]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isSending) return;

    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: text }]);
    setInput("");
    setIsSending(true);
    setError(null);
    setThinkingEvents([]);

    // Open the SSE stream first so it is listening before the chat POST hits
    // the backend. The backend publishes the first "supervisor/start" event
    // the instant /chat/message is called — if the stream isn't open yet that
    // event is silently dropped and the thinking panel appears blank until the
    // first tool call arrives (5-15s later). Capturing it client-side as a
    // synthetic first event avoids that gap entirely without relying on timing.
    const events: ThinkingEvent[] = [
      { id: -1, agent: "supervisor", status: "start", message: "Analyzing your request and coordinating the advisor agents...", ts: Date.now() / 1000 },
    ];
    setThinkingEvents([...events]);

    const eventSource = await openChatEventStream((e) => {
      // Skip the real supervisor/start event if it arrives — the synthetic one
      // above already covers it and deduplicating avoids a double entry.
      if (e.agent === "supervisor" && e.status === "start") return;
      events.push(e);
      setThinkingEvents([...events]);
    });

    try {
      const { reply, thread_id } = await sendChatMessage(text, threadId);
      setThreadId(thread_id);
      setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: reply, thinking: events }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      eventSource.close();
      setIsSending(false);
    }
  }

  return (
    <main className="chat-page">
      <h1>Property Advisor</h1>

      <div className="chat-history" ref={chatHistoryRef}>
        {messages.map((message) => (
          <div key={message.id} className="chat-turn">
            {message.thinking && message.thinking.length > 0 && (
              <ThinkingPanel events={message.thinking} isActive={false} />
            )}
            <ChatMessageBubble {...message} />
          </div>
        ))}
        {isSending && <ThinkingPanel events={thinkingEvents} isActive={true} />}
        {error && <div className="chat-error">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <form className="chat-input-bar" onSubmit={handleSend}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. 4-room flat near Bishan MRT under $850k"
          disabled={isSending}
          autoFocus
        />
        <button type="submit" disabled={isSending || !input.trim()}>
          Send
        </button>
      </form>
    </main>
  );
}
