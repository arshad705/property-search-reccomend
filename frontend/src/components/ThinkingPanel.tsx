import { useState } from "react";
import type { ThinkingEvent } from "../types";

interface ThinkingPanelProps {
  events: ThinkingEvent[];
  isActive: boolean;
}

const AGENT_LABEL: Record<ThinkingEvent["agent"], string> = {
  supervisor: "Advisor",
  listings: "Listings",
  valuation: "Valuation",
  geospatial: "Geospatial",
};

export function ThinkingPanel({ events, isActive }: ThinkingPanelProps) {
  const [expanded, setExpanded] = useState(false);

  if (events.length === 0 && !isActive) return null;

  const latest = events[events.length - 1];
  const elapsedSeconds = events.length > 0 ? Math.max(1, Math.round(events[events.length - 1].ts - events[0].ts)) : 0;
  const summaryText = isActive ? (latest?.message ?? "Thinking...") : `Thought for ${elapsedSeconds}s`;

  return (
    <div className={`thinking-panel ${isActive ? "active" : "done"}`}>
      <button
        type="button"
        className="thinking-panel-toggle"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        <span className={`thinking-chevron ${expanded ? "open" : ""}`} aria-hidden="true">
          ▸
        </span>
        <span className="thinking-summary">{summaryText}</span>
      </button>

      <div className={`thinking-trace-wrapper ${expanded ? "open" : ""}`}>
        <div className="thinking-trace-inner">
          <ul className="thinking-trace">
            {events.map((event) => (
              <li key={event.id} className={`thinking-trace-item ${event.status}`}>
                <span className="thinking-agent-label">{AGENT_LABEL[event.agent]}</span>
                <span className="thinking-trace-message">{event.message}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
