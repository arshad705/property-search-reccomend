export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  // Present on assistant messages that involved tool calls — kept permanently
  // so the "Thought for Ns" summary stays attached to that specific message
  // in history and can be re-expanded later, matching Claude/ChatGPT's UX.
  thinking?: ThinkingEvent[];
}

export interface ChatApiResponse {
  reply: string;
  thread_id: string;
}

export interface ThinkingEvent {
  id: number;
  agent: "supervisor" | "listings" | "valuation" | "geospatial";
  status: "start" | "done";
  message: string;
  ts: number;
}
