import type { TrustDeskClient, WidgetConfig } from "@trustdesk/sdk";
import { type FormEvent, useRef, useState } from "react";

import { randomId, safeHref } from "../lib/chat";
import { strings } from "../lib/i18n";
import { Captcha, type CaptchaHandle } from "./Captcha";

interface Props {
  config: WidgetConfig;
  client: TrustDeskClient;
  visitorId: string;
  conversationId: string | null;
  lastQuestion: string;
  message: string;
  lang: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function whatsappLink(number: string, question: string): string | null {
  const digits = number.replace(/[^\d]/g, "");
  if (digits.length < 7) return null;
  // Only the visitor's own question, shortened — no other personal data.
  const text = question ? `Hi! I have a question: ${question.slice(0, 200)}` : "Hi! I have a question.";
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

export function HandoffPanel({ config, client, visitorId, conversationId, lastQuestion, message, lang }: Props) {
  const t = strings(lang);
  const h = config.handoff as Record<string, { enabled?: boolean; number?: string; url?: string }>;
  const wa = h.whatsapp?.enabled && h.whatsapp.number ? whatsappLink(h.whatsapp.number, lastQuestion) : null;
  const booking = h.booking?.enabled ? safeHref(h.booking.url) : null;
  const emailEnabled = Boolean(h.email?.enabled);
  const [showForm, setShowForm] = useState(false);

  const recordIntent = (channel: "whatsapp" | "booking") => {
    // Best-effort record that the visitor chose this channel; never blocks the navigation.
    void client
      .createLead({
        channel,
        visitor_id: visitorId,
        conversation_id: conversationId,
        idempotency_key: randomId().replace(/-/g, ""),
        consent: false,
      })
      .catch(() => undefined);
  };

  return (
    <section aria-label={t.handoffTitle} className="rounded-2xl border border-border-strong bg-card p-3">
      <p dir="auto" className="mb-2 text-sm text-body">
        {message}
      </p>
      {!wa && !booking && !emailEnabled && <p className="text-sm text-muted">{t.noChannels}</p>}
      <div className="flex flex-wrap gap-2">
        {wa && (
          <a href={wa} target="_blank" rel="noopener noreferrer" onClick={() => recordIntent("whatsapp")} className={btn}>
            {t.whatsapp}
          </a>
        )}
        {booking && (
          <a href={booking} target="_blank" rel="noopener noreferrer" onClick={() => recordIntent("booking")} className={btn}>
            {t.booking}
          </a>
        )}
        {emailEnabled && !showForm && (
          <button type="button" className={btn} onClick={() => setShowForm(true)}>
            {t.email}
          </button>
        )}
      </div>
      {emailEnabled && showForm && (
        <EmailForm config={config} client={client} visitorId={visitorId} conversationId={conversationId} lang={lang} />
      )}
    </section>
  );
}

const btn =
  "inline-flex items-center rounded-full border border-primary px-3 py-1.5 text-sm font-medium text-primary transition-colors duration-200 hover:bg-primary hover:text-primary-fg";

function EmailForm({
  config,
  client,
  visitorId,
  conversationId,
  lang,
}: Omit<Props, "lastQuestion" | "message">) {
  const t = strings(lang);
  const idempotencyKey = useRef(randomId().replace(/-/g, ""));
  const captcha = useRef<CaptchaHandle>(null);
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (state !== "idle") return; // prevents double submission
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    if (!EMAIL_RE.test(email)) return setError("Please enter a valid email address.");
    if (!form.get("consent")) return setError("Please confirm we may contact you.");
    setError(null);
    setState("sending");
    try {
      await client.createLead({
        channel: "email",
        visitor_id: visitorId,
        conversation_id: conversationId,
        idempotency_key: idempotencyKey.current,
        name: String(form.get("name") ?? "").trim().slice(0, 200) || null,
        email,
        message: String(form.get("message") ?? "").trim().slice(0, 2000) || null,
        consent: true,
        captcha_token: captcha.current?.token() ?? null,
      });
      setState("sent"); // only after the server confirmed the lead was saved
    } catch (err) {
      captcha.current?.reset();
      setError(err instanceof Error ? err.message : t.error);
      setState("idle");
    }
  }

  if (state === "sent") {
    return (
      <p role="status" className="mt-3 rounded-lg bg-success/10 p-2 text-sm text-success">
        {t.sent}
      </p>
    );
  }
  const field = "w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-text placeholder:text-muted";
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-2" noValidate>
      <label className="td-sr-only" htmlFor="td-name">{t.name}</label>
      <input id="td-name" name="name" autoComplete="name" maxLength={200} placeholder={t.name} className={field} />
      <label className="td-sr-only" htmlFor="td-email">{t.emailField}</label>
      <input id="td-email" name="email" type="email" required autoComplete="email" maxLength={320} placeholder={t.emailField} className={field} />
      <label className="td-sr-only" htmlFor="td-message">{t.message}</label>
      <textarea id="td-message" name="message" rows={3} maxLength={2000} placeholder={t.message} className={field} dir="auto" />
      <label className="flex items-start gap-2 text-xs text-muted">
        <input type="checkbox" name="consent" className="mt-0.5" required />
        {t.consent}
      </label>
      {config.captcha && <Captcha ref={captcha} provider={config.captcha.provider} siteKey={config.captcha.site_key} />}
      {error && (
        <p role="alert" className="text-xs text-error">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={state === "sending"}
        className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
      >
        {state === "sending" ? t.submitting : t.submit}
      </button>
    </form>
  );
}
