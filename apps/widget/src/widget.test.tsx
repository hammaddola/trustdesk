import type { ChatEvent, TrustDeskClient, WidgetConfig } from "@trustdesk/sdk";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { whatsappLink } from "./components/HandoffPanel";
import { chatReducer, initialChat, safeHref, segments } from "./lib/chat";
import { mount } from "./loader";

const CONFIG: WidgetConfig = {
  organization: "Acme Studio (DEMO)",
  greeting: "Hi! Ask about Acme Studio.",
  default_language: "en",
  enabled_languages: ["en"],
  direction: "ltr",
  theme: {},
  handoff: { email: { enabled: true }, whatsapp: { enabled: true, number: "+15550001111" } },
  ready: true,
  captcha: null,
};

const ANSWER: ChatEvent[] = [
  { event: "conversation_started", data: { conversation_id: "c1" } },
  { event: "searching", data: {} },
  { event: "citation", data: { marker: 1, title: "Pricing", url: "https://acme.example/pricing", section: "Packages", snippet: "Starter costs $1,500.", updated_at: null } },
  { event: "token", data: { text: "The Starter package costs $1,500 [1]." } },
  { event: "confidence", data: { level: "high" } },
  { event: "completed", data: { message_id: "m1", conversation_id: "c1", status: "answered", handoff_required: false, language: "en" } },
];

const HANDOFF: ChatEvent[] = [
  { event: "conversation_started", data: { conversation_id: "c1" } },
  { event: "handoff", data: { message: "I couldn't find this, so I won't guess.", summary: "Visitor asked: x" } },
  { event: "confidence", data: { level: "low" } },
  { event: "completed", data: { message_id: "m2", conversation_id: "c1", status: "handoff", handoff_required: true, language: "en" } },
];

function fakeClient(events: ChatEvent[]): TrustDeskClient & { createLead: ReturnType<typeof vi.fn> } {
  return {
    getConfig: vi.fn(async () => CONFIG),
    sendFeedback: vi.fn(async () => undefined),
    createLead: vi.fn(async () => ({ lead_id: "l1", status: "received" as const })),
    streamChat: vi.fn(async (_body, onEvent: (e: ChatEvent) => void) => {
      for (const e of events) onEvent(e);
    }),
  } as unknown as TrustDeskClient & { createLead: ReturnType<typeof vi.fn> };
}

async function openAndAsk(client: TrustDeskClient, question: string) {
  const user = userEvent.setup();
  render(<App client={client} visitorId="00000000-0000-4000-8000-000000000001" firstVisit theme="light" />);
  await user.click(await screen.findByTestId("launcher"));
  await screen.findByText(CONFIG.greeting!);
  const input = screen.getByRole("textbox", { name: /type your question/i });
  await user.type(input, `${question}{Enter}`);
  return user;
}

describe("chat reducer & helpers", () => {
  it("streams tokens, citations and completion into one assistant message", () => {
    let s = chatReducer(initialChat, { type: "send", text: "q", userId: "u", assistantId: "a" });
    for (const e of ANSWER) s = chatReducer(s, { type: "event", assistantId: "a", event: e });
    const a = s.messages[1]!;
    expect(a.role === "assistant" && a.text).toBe("The Starter package costs $1,500 [1].");
    expect(a.role === "assistant" && a.citations).toHaveLength(1);
    expect(s.busy).toBe(false);
    expect(s.conversationId).toBe("c1");
  });

  it("splits citation markers and only allows http(s) links", () => {
    expect(segments("A [1] and [2].")).toEqual(["A ", 1, " and ", 2, "."]);
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,x")).toBeNull();
    expect(safeHref("https://a.example/x")).toBe("https://a.example/x");
  });

  it("builds a WhatsApp link with only the visitor's question", () => {
    const link = whatsappLink("+1 (555) 000-1111", "How much is a website?")!;
    expect(link.startsWith("https://wa.me/15550001111?text=")).toBe(true);
    expect(decodeURIComponent(link)).toContain("How much is a website?");
    expect(whatsappLink("12", "x")).toBeNull();
  });
});

describe("widget UI", () => {
  it("opens from the launcher, streams a cited answer with confidence, and closes on Escape", async () => {
    const client = fakeClient(ANSWER);
    const user = await openAndAsk(client, "How much is Starter?");
    const messages = screen.getByTestId("messages");
    await within(messages).findByText(/The Starter package costs \$1,500/);
    const chip = within(messages).getByRole("link", { name: /Pricing/ });
    expect(chip).toHaveAttribute("href", "https://acme.example/pricing");
    expect(chip).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByTestId("confidence")).toHaveAttribute("data-level", "high");
    expect(screen.getByRole("tooltip")).toHaveTextContent(/not a guarantee/i);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("panel")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("launcher")).toHaveFocus());
  });

  it("shows the handoff panel and only reports success after the lead is saved", async () => {
    const client = fakeClient(HANDOFF);
    const user = await openAndAsk(client, "Do you do penetration testing?");
    const panel = await screen.findByRole("region", { name: /talk to a person/i });
    within(panel).getByText(/won't guess/);
    expect(screen.getByRole("link", { name: /whatsapp/i })).toHaveAttribute("href", expect.stringContaining("wa.me/15550001111"));
    await user.click(screen.getByRole("button", { name: /send us a message/i }));
    await user.type(screen.getByPlaceholderText(/your email/i), "visitor@example.com");
    await user.click(screen.getByRole("button", { name: /send message/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/confirm/i); // consent required
    expect(client.createLead).not.toHaveBeenCalled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /send message/i }));
    await screen.findByText(/your message was received/i);
    expect(client.createLead).toHaveBeenCalledTimes(1);
    expect(client.createLead.mock.calls[0]![0]).toMatchObject({ channel: "email", email: "visitor@example.com", consent: true });
  });

  it("does not show success when saving the lead fails", async () => {
    const client = fakeClient(HANDOFF);
    client.createLead.mockRejectedValueOnce(new Error("verification failed, please try again"));
    const user = await openAndAsk(client, "x");
    const panel = await screen.findByRole("region", { name: /talk to a person/i });
    within(panel).getByText(/won't guess/);
    await user.click(screen.getByRole("button", { name: /send us a message/i }));
    await user.type(screen.getByPlaceholderText(/your email/i), "visitor@example.com");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /send message/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/verification failed/);
    expect(screen.queryByText(/your message was received/i)).not.toBeInTheDocument();
  });

  it("shows an error state with retry when config cannot load", async () => {
    const client = fakeClient(ANSWER);
    (client.getConfig as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("down"));
    const user = userEvent.setup();
    render(<App client={client} visitorId="v" firstVisit={false} theme="dark" />);
    await user.click(screen.getByTestId("launcher"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    await screen.findByText(CONFIG.greeting!);
  });
});

describe("loader", () => {
  it("mounts once inside a shadow root and keeps styles out of the host page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(CONFIG), { status: 200 })));
    const before = document.head.querySelectorAll("style").length;
    let destroy!: () => void;
    await act(async () => {
      destroy = mount({ publicKey: "td_pk_testkey12345", apiUrl: "https://api.example.com" });
    });
    const host = document.querySelector("trustdesk-widget")!;
    expect(host.shadowRoot).not.toBeNull();
    expect(host.shadowRoot!.querySelector("style")!.textContent).toContain("--td-primary");
    expect(document.head.querySelectorAll("style").length).toBe(before); // no global CSS pollution
    expect(mount({ publicKey: "td_pk_testkey12345", apiUrl: "https://api.example.com" })).toBe(destroy); // idempotent
    expect(document.querySelectorAll("trustdesk-widget")).toHaveLength(1);
    act(() => destroy());
    expect(document.querySelector("trustdesk-widget")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("rejects malformed keys instead of calling the API", () => {
    expect(() => mount({ publicKey: "sk_live_secret", apiUrl: "https://api.example.com" })).toThrow(/invalid public key/);
    expect(document.querySelector("trustdesk-widget")).toBeNull(); // nothing injected into the host page
    expect(window.__trustdesk).toBeUndefined();
  });
});
