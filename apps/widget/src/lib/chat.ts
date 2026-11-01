import type { ChatEvent, CitationEvent, Confidence } from "@trustdesk/sdk";

export type Phase = "idle" | "searching" | "reranking" | "writing";

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  text: string;
  citations: CitationEvent[];
  confidence: Confidence | null;
  handoff: { message: string } | null;
  messageId: string | null; // server id, for feedback
  done: boolean;
  error: string | null;
  language: string | null;
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
  phase: Phase;
  busy: boolean;
}

export const initialChat: ChatState = { conversationId: null, messages: [], phase: "idle", busy: false };

export type ChatAction =
  | { type: "send"; text: string; userId: string; assistantId: string }
  | { type: "event"; assistantId: string; event: ChatEvent }
  | { type: "failed"; assistantId: string; message: string };

function updateAssistant(state: ChatState, id: string, fn: (m: AssistantMessage) => AssistantMessage): ChatMessage[] {
  return state.messages.map((m) => (m.id === id && m.role === "assistant" ? fn(m) : m));
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send":
      return {
        ...state,
        busy: true,
        phase: "idle",
        messages: [
          ...state.messages,
          { id: action.userId, role: "user", text: action.text },
          {
            id: action.assistantId,
            role: "assistant",
            text: "",
            citations: [],
            confidence: null,
            handoff: null,
            messageId: null,
            done: false,
            error: null,
            language: null,
          },
        ],
      };
    case "failed":
      return {
        ...state,
        busy: false,
        phase: "idle",
        messages: updateAssistant(state, action.assistantId, (m) => ({ ...m, done: true, error: action.message })),
      };
    case "event": {
      const { event: e, assistantId: id } = action;
      switch (e.event) {
        case "conversation_started":
          return { ...state, conversationId: e.data.conversation_id };
        case "searching":
          return { ...state, phase: "searching" };
        case "reranking":
          return { ...state, phase: "reranking" };
        case "token":
          return { ...state, phase: "writing", messages: updateAssistant(state, id, (m) => ({ ...m, text: m.text + e.data.text })) };
        case "citation":
          return { ...state, messages: updateAssistant(state, id, (m) => ({ ...m, citations: [...m.citations, e.data] })) };
        case "confidence":
          return { ...state, messages: updateAssistant(state, id, (m) => ({ ...m, confidence: e.data.level })) };
        case "handoff":
          return { ...state, messages: updateAssistant(state, id, (m) => ({ ...m, handoff: { message: e.data.message } })) };
        case "completed":
          return {
            ...state,
            busy: false,
            phase: "idle",
            conversationId: e.data.conversation_id,
            messages: updateAssistant(state, id, (m) => ({
              ...m,
              done: true,
              messageId: e.data.message_id,
              language: e.data.language,
              text: m.text.trim(),
            })),
          };
        case "error":
          return {
            ...state,
            busy: false,
            phase: "idle",
            messages: updateAssistant(state, id, (m) => ({ ...m, done: true, error: e.data.message })),
          };
      }
    }
  }
  return state;
}

/** Split answer text into plain segments and [n] citation markers. */
export function segments(text: string): Array<string | number> {
  const out: Array<string | number> = [];
  const re = /\[(\d{1,2})\]/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(Number(m[1]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Only http(s) links are ever rendered (no javascript:, data:, etc.). */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function hostname(url: string | null): string {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, "") : "";
  } catch {
    return "";
  }
}

export function randomId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
