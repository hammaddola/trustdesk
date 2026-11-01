import type { TrustDeskClient, WidgetConfig } from "@trustdesk/sdk";
import { AnimatePresence, LazyMotion, MotionConfig, domAnimation, m } from "framer-motion";
import { type FormEvent, useCallback, useEffect, useReducer, useRef, useState } from "react";

import { AssistantBubble, UserBubble } from "./components/Message";
import { HandoffPanel } from "./components/HandoffPanel";
import { type AssistantMessage, chatReducer, initialChat, randomId } from "./lib/chat";
import { isRtl, strings } from "./lib/i18n";

export interface AppProps {
  client: TrustDeskClient;
  visitorId: string;
  firstVisit: boolean;
  theme: "light" | "dark";
}

type Load = { state: "loading" } | { state: "ready"; config: WidgetConfig } | { state: "error" };

export function App({ client, visitorId, firstVisit, theme }: AppProps) {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [chat, dispatch] = useReducer(chatReducer, initialChat);
  const [draft, setDraft] = useState("");
  const [announce, setAnnounce] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchConfig = useCallback(() => {
    setLoad({ state: "loading" });
    client.getConfig().then(
      (config) => setLoad({ state: "ready", config }),
      () => setLoad({ state: "error" }),
    );
  }, [client]);

  useEffect(fetchConfig, [fetchConfig]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const config = load.state === "ready" ? load.config : null;
  const lang = config?.default_language ?? "en";
  const t = strings(lang);

  const close = useCallback(() => {
    setOpen(false);
    requestAnimationFrame(() => launcherRef.current?.focus());
  }, []);

  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [chat.messages]);

  const lastAssistant = [...chat.messages].reverse().find((x): x is AssistantMessage => x.role === "assistant");
  useEffect(() => {
    // Announce completed answers once (streaming tokens into a live region would be very noisy).
    if (lastAssistant?.done) setAnnounce(lastAssistant.error ?? lastAssistant.handoff?.message ?? lastAssistant.text);
  }, [lastAssistant?.done, lastAssistant?.error, lastAssistant?.handoff, lastAssistant?.text]);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || chat.busy) return;
    const assistantId = randomId();
    dispatch({ type: "send", text, userId: randomId(), assistantId });
    setDraft("");
    abortRef.current = new AbortController();
    try {
      await client.streamChat(
        { message: text, visitor_id: visitorId, conversation_id: chat.conversationId },
        (event) => dispatch({ type: "event", assistantId, event }),
        abortRef.current.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        dispatch({ type: "failed", assistantId, message: err instanceof Error ? err.message : t.error });
      }
    }
  }

  const lastQuestion = [...chat.messages].reverse().find((x) => x.role === "user")?.text ?? "";
  const phaseText = { idle: "", searching: t.searching, reranking: t.reranking, writing: t.writing }[chat.phase];
  const position = (config?.theme as { position?: string } | undefined)?.position === "left" ? "start" : "end";

  return (
    <LazyMotion features={domAnimation} strict>
    <MotionConfig reducedMotion="user">
      <div className="td-root" data-theme={theme} dir={isRtl(lang) ? "rtl" : "ltr"} onKeyDown={(e) => e.key === "Escape" && open && close()}>
        <AnimatePresence>
          {open && (
            <m.div
              role="dialog"
              aria-modal="false"
              aria-labelledby="td-title"
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              data-testid="panel"
              className={`fixed inset-0 z-[2147483646] flex flex-col bg-bg/95 text-text backdrop-blur-md sm:inset-auto sm:bottom-24 ${position === "end" ? "sm:end-5" : "sm:start-5"} sm:h-[min(640px,calc(100vh-8rem))] sm:w-[400px] sm:rounded-panel sm:border sm:border-border sm:shadow-2xl`}
            >
              <header className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
                <div>
                  <h2 id="td-title" className="text-base font-semibold">
                    {config?.organization ?? t.title}
                  </h2>
                  {config && <p className="text-xs text-muted">{t.subtitle.replace("{org}", config.organization)}</p>}
                </div>
                <button type="button" onClick={close} aria-label={t.close} className="rounded-full p-1.5 text-muted hover:bg-surface hover:text-text">
                  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </header>

              <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4" data-testid="messages">
                {load.state === "loading" && (
                  <div className="space-y-2" aria-hidden="true">
                    <div className="td-skeleton h-4 w-3/4 rounded" />
                    <div className="td-skeleton h-4 w-1/2 rounded" />
                  </div>
                )}
                {load.state === "error" && (
                  <div role="alert" className="text-sm text-error">
                    {t.unavailable}{" "}
                    <button type="button" className="underline" onClick={fetchConfig}>
                      {t.retry}
                    </button>
                  </div>
                )}
                {config && chat.messages.length === 0 && (
                  <p dir="auto" className="rounded-2xl border border-border bg-surface px-3.5 py-2 text-sm text-body">
                    {config.greeting ?? t.launcher}
                  </p>
                )}
                {chat.messages.map((msg) =>
                  msg.role === "user" ? (
                    <UserBubble key={msg.id} text={msg.text} />
                  ) : (
                    <div key={msg.id} className="space-y-2">
                      {!msg.done && !msg.text && (
                        <div className="td-skeleton h-8 w-40 rounded-2xl" aria-hidden="true" />
                      )}
                      <AssistantBubble
                        m={msg}
                        lang={lang}
                        onFeedback={(rating) =>
                          msg.messageId ? client.sendFeedback({ message_id: msg.messageId, visitor_id: visitorId, rating }) : Promise.resolve()
                        }
                      />
                      {msg.handoff && config && (
                        <HandoffPanel
                          config={config}
                          client={client}
                          visitorId={visitorId}
                          conversationId={chat.conversationId}
                          lastQuestion={lastQuestion}
                          message={msg.handoff.message}
                          lang={msg.language ?? lang}
                        />
                      )}
                    </div>
                  ),
                )}
              </div>

              <p role="status" aria-live="polite" className="min-h-5 px-4 text-xs text-muted">
                {phaseText}
              </p>
              <p aria-live="polite" className="td-sr-only">
                {announce}
              </p>

              <form onSubmit={send} className="flex items-end gap-2 border-t border-border p-3">
                <label htmlFor="td-input" className="td-sr-only">
                  {t.placeholder}
                </label>
                <textarea
                  id="td-input"
                  ref={inputRef}
                  rows={1}
                  dir="auto"
                  value={draft}
                  maxLength={2000}
                  disabled={!config}
                  placeholder={t.placeholder}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  className="max-h-32 min-h-10 flex-1 resize-none rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text placeholder:text-muted"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || chat.busy || !config}
                  className="h-10 rounded-xl bg-primary px-4 text-sm font-medium text-primary-fg transition-opacity duration-200 disabled:opacity-50"
                >
                  {t.send}
                </button>
              </form>
              <p className="px-4 pb-2 text-center text-[11px] text-muted">{t.poweredBy}</p>
            </m.div>
          )}
        </AnimatePresence>

        {!open && (
          <button
            ref={launcherRef}
            type="button"
            onClick={() => setOpen(true)}
            aria-label={t.open}
            aria-expanded={open}
            data-testid="launcher"
            className={`fixed bottom-5 z-[2147483646] flex items-center gap-2 rounded-full bg-primary px-4 py-3 text-sm font-medium text-primary-fg shadow-lg transition-transform duration-200 hover:scale-[1.03] ${position === "end" ? "end-5" : "start-5"} ${firstVisit ? "td-pulse" : ""}`}
          >
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
            </svg>
            {(config?.theme as { launcher_text?: string } | undefined)?.launcher_text ?? t.launcher}
          </button>
        )}
      </div>
    </MotionConfig>
    </LazyMotion>
  );
}
