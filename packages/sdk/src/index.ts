import type { ChatEvent, ChatRequest, FeedbackRequest, LeadIn, LeadReceipt, WidgetConfig } from "@trustdesk/contracts";

import { SSEParser } from "./sse";

export { SSEParser } from "./sse";
export type * from "@trustdesk/contracts";

export class TrustDeskError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "TrustDeskError";
  }
}

export interface ClientOptions {
  /** Base URL of the TrustDesk AI service, e.g. https://api.example.com */
  apiUrl: string;
  /** Publishable widget key (td_pk_...). Never a secret key. */
  publicKey: string;
  fetch?: typeof fetch;
}

export function createClient({ apiUrl, publicKey, fetch: fetchImpl = globalThis.fetch.bind(globalThis) }: ClientOptions) {
  if (!/^td_pk_[A-Za-z0-9_-]{8,58}$/.test(publicKey)) throw new Error("TrustDesk: invalid public key");
  const base = `${apiUrl.replace(/\/+$/, "")}/v1/public/${encodeURIComponent(publicKey)}`;

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetchImpl(`${base}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
      credentials: "omit",
    });
    if (!res.ok) throw await toError(res);
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  return {
    getConfig: () => request<WidgetConfig>("/config"),

    sendFeedback: (body: FeedbackRequest) => request<void>("/feedback", { method: "POST", body: JSON.stringify(body) }),

    createLead: (body: LeadIn) => request<LeadReceipt>("/leads", { method: "POST", body: JSON.stringify(body) }),

    /** Streams a chat turn. Aborting `signal` closes the connection; the server then cancels generation. */
    async streamChat(body: ChatRequest, onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
      const res = await fetchImpl(`${base}/chat/stream`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify(body),
        credentials: "omit",
        signal: signal ?? null,
      });
      if (!res.ok || !res.body) throw await toError(res);
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SSEParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const event of parser.feed(value)) onEvent(event);
      }
    },
  };
}

export type TrustDeskClient = ReturnType<typeof createClient>;

async function toError(res: Response): Promise<TrustDeskError> {
  let message = "The assistant is unavailable right now.";
  let requestId: string | undefined;
  try {
    const body = (await res.json()) as { error?: unknown; request_id?: unknown };
    if (typeof body.error === "string") message = body.error;
    if (typeof body.request_id === "string") requestId = body.request_id;
  } catch {
    /* non-JSON error body: keep the generic message */
  }
  return new TrustDeskError(message, res.status, requestId);
}
