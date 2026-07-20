import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";

// rehype-raw lets stray HTML the agent sometimes emits (e.g. <br>) render
// instead of showing as literal text; rehype-sanitize strips anything unsafe
// (script tags, event handlers, javascript: URLs) since this content
// ultimately originates from third-party listing/amenity names the agent
// echoes verbatim.
const markdownComponents = {
  a: ({ href, children }: React.ComponentPropsWithoutRef<"a">) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }: React.ComponentPropsWithoutRef<"table">) => (
    <div className="table-scroll">
      <table>{children}</table>
    </div>
  ),
};

export function ChatMessageBubble({ role, content }: ChatMessage) {
  return (
    <div className={`chat-bubble ${role}`}>
      <div className="chat-bubble-role">{role === "user" ? "You" : "Property Advisor"}</div>
      <div className="chat-bubble-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw, rehypeSanitize]}
          components={markdownComponents}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
