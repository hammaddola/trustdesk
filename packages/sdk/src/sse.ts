import type { ChatEvent, ChatEventName } from "@trustdesk/contracts";

const KNOWN: ReadonlySet<ChatEventName> = new Set<ChatEventName>([
  "conversation_started",
  "searching",
  "reranking",
  "token",
  "citation",
  "confidence",
  "handoff",
  "completed",
  "error",
]);

/** Incremental SSE parser (WHATWG event-stream format). Comments (heartbeats) and unknown events are ignored. */
export class SSEParser {
  private buffer = "";

  feed(chunk: string): ChatEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const out: ChatEvent[] = [];
    let boundary: number;
    while ((boundary = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const parsed = parseBlock(block);
      if (parsed) out.push(parsed);
    }
    return out;
  }
}

function parseBlock(block: string): ChatEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!KNOWN.has(event as ChatEventName) || data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) } as ChatEvent;
  } catch {
    return null;
  }
}
