// REST types are generated from the FastAPI OpenAPI spec (src/api.gen.ts).
// SSE event payloads are not part of OpenAPI; they are defined here and mirror
// services/ai/src/trustdesk_ai/{chat/service.py,rag/graph.py}. Keep both in sync.
import type { components } from "./api.gen";

export type { components, paths } from "./api.gen";

type Schemas = components["schemas"];
export type WidgetConfig = Schemas["WidgetConfig"];
export type ChatRequest = Schemas["ChatRequest"];
export type FeedbackRequest = Schemas["FeedbackRequest"];
export type LeadIn = Schemas["LeadIn"];
export type LeadReceipt = Schemas["LeadReceipt"];

export type Confidence = "high" | "medium" | "low";
export type AnswerStatus = "answered" | "partial" | "refused" | "handoff" | "error";

export interface CitationEvent {
  marker: number;
  title: string | null;
  url: string | null;
  section: string | null;
  snippet: string;
  updated_at: string | null;
}

export type ChatEvent =
  | { event: "conversation_started"; data: { conversation_id: string } }
  | { event: "searching"; data: Record<string, never> }
  | { event: "reranking"; data: Record<string, never> }
  | { event: "token"; data: { text: string } }
  | { event: "citation"; data: CitationEvent }
  | { event: "confidence"; data: { level: Confidence } }
  | { event: "handoff"; data: { message: string; summary: string } }
  | {
      event: "completed";
      data: {
        message_id: string;
        conversation_id: string;
        status: AnswerStatus | null;
        handoff_required: boolean;
        language: string | null;
      };
    }
  | { event: "error"; data: { message: string; request_id: string } };

export type ChatEventName = ChatEvent["event"];
