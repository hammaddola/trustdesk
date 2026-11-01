import type { CitationEvent } from "@trustdesk/sdk";
import { useState } from "react";

import { type AssistantMessage, hostname, safeHref, segments } from "../lib/chat";
import { strings } from "../lib/i18n";
import { ConfidenceMeter } from "./ConfidenceMeter";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p dir="auto" className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-ee-md bg-primary px-3.5 py-2 text-primary-fg">
        {text}
      </p>
    </div>
  );
}

function CitationChip({ c }: { c: CitationEvent }) {
  const href = safeHref(c.url);
  const label = c.title || hostname(c.url) || `Source ${c.marker}`;
  const updated = c.updated_at ? new Date(c.updated_at).toLocaleDateString() : null;
  const content = (
    <>
      <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1 text-xs font-semibold text-primary">
        {c.marker}
      </span>
      <span dir="auto" className="truncate">
        {label}
        {c.section && c.section !== label ? ` · ${c.section}` : ""}
      </span>
    </>
  );
  const cls =
    "flex max-w-full items-center gap-1.5 rounded-full border border-border-strong bg-card px-2 py-1 text-xs text-body transition-colors duration-200 hover:border-primary";
  const title = [c.snippet, updated ? `Updated ${updated}` : null].filter(Boolean).join(" — ");
  return href ? (
    <a className={cls} href={href} target="_blank" rel="noopener noreferrer nofollow" title={title}>
      {content}
    </a>
  ) : (
    <span className={cls} title={title}>
      {content}
    </span>
  );
}

export function AssistantBubble({
  m,
  lang,
  onFeedback,
}: {
  m: AssistantMessage;
  lang: string;
  onFeedback: (rating: "helpful" | "not_helpful") => Promise<void>;
}) {
  const t = strings(m.language ?? lang);
  const [rated, setRated] = useState(false);
  const rate = async (r: "helpful" | "not_helpful") => {
    setRated(true);
    await onFeedback(r).catch(() => setRated(false));
  };
  if (m.error) {
    return (
      <p role="alert" className="rounded-2xl border border-error/30 bg-error/5 px-3.5 py-2 text-sm text-error">
        {m.error}
      </p>
    );
  }
  const parts = segments(m.text);
  return (
    <div className="flex flex-col items-start gap-2">
      {m.text && (
        <div dir="auto" className="max-w-[92%] whitespace-pre-wrap rounded-2xl rounded-es-md border border-border bg-surface px-3.5 py-2 text-body">
          {parts.map((p, i) =>
            typeof p === "number" ? (
              <sup key={i} className="mx-0.5 text-[0.7em] font-semibold text-primary" aria-label={`source ${p}`}>
                [{p}]
              </sup>
            ) : (
              <span key={i}>{p}</span>
            ),
          )}
        </div>
      )}
      {m.citations.length > 0 && (
        <div className="flex max-w-full flex-col gap-1">
          <span className="text-xs font-medium text-muted">{t.sources}</span>
          <ul className="flex max-w-full flex-wrap gap-1.5">
            {m.citations.map((c) => (
              <li key={c.marker} className="max-w-full">
                <CitationChip c={c} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.done && m.confidence && m.text && (
        <div className="flex flex-wrap items-center gap-3">
          <ConfidenceMeter level={m.confidence} lang={m.language ?? lang} />
          {m.messageId &&
            (rated ? (
              <span className="text-xs text-muted">{t.thanks}</span>
            ) : (
              <span className="flex gap-1">
                <button type="button" onClick={() => rate("helpful")} className="rounded px-1.5 text-xs text-muted hover:text-text" aria-label={t.helpful}>
                  👍
                </button>
                <button type="button" onClick={() => rate("not_helpful")} className="rounded px-1.5 text-xs text-muted hover:text-text" aria-label={t.notHelpful}>
                  👎
                </button>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
