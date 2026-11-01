import Link from "next/link";
import { notFound } from "next/navigation";

import { CitationList, TraceView } from "@/components/trace";
import { Badge, ErrorBox, PageHeader, fmtDate, statusTone } from "@/components/ui";
import { ApiError, type S, api, errorMessage } from "@/lib/api";

export const metadata = { title: "Conversation" };

export default async function ConversationDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let d: S["ConversationDetail"];
  try {
    d = await api<S["ConversationDetail"]>(`/v1/admin/conversations/${encodeURIComponent(id)}`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) notFound();
    return <ErrorBox message={errorMessage(err)} />;
  }
  const c = d.conversation;
  return (
    <>
      <p className="mb-2 text-sm"><Link href="/conversations">← Conversations</Link></p>
      <PageHeader
        title="Conversation"
        description={`${c.channel === "playground" ? "Playground test" : "Website widget"} · started ${fmtDate(c.started_at)} · ${c.message_count} messages${c.language ? ` · ${c.language}` : ""}`}
        actions={<Badge tone={statusTone(c.status)}>{c.handoff ? "handed off" : c.status}</Badge>}
      />
      <ol className="space-y-4">
        {d.messages.map((m) =>
          m.role === "user" ? (
            <li key={m.id} className="ml-auto max-w-2xl rounded-xl bg-accent/15 px-4 py-3 text-heading">
              <p className="mb-1 text-xs text-muted">Visitor · {fmtDate(m.created_at)}</p>
              <p className="whitespace-pre-wrap" dir="auto">{m.content}</p>
            </li>
          ) : (
            <li key={m.id} className="max-w-4xl rounded-xl border border-border bg-card p-4">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                <span>Assistant · {fmtDate(m.created_at)}</span>
                {m.answer_status && <Badge tone={statusTone(m.answer_status)}>{m.answer_status}</Badge>}
                {m.confidence && <Badge tone={statusTone(m.confidence)}>{m.confidence} confidence</Badge>}
                {m.handoff_required && <Badge tone="warning">handoff offered</Badge>}
                {m.feedback && (
                  <Badge tone={(m.feedback as { rating?: string }).rating === "helpful" ? "success" : "danger"}>
                    visitor: {String((m.feedback as { rating?: string }).rating).replace("_", " ")}
                  </Badge>
                )}
              </div>
              <p className="whitespace-pre-wrap text-body" dir="auto">{m.content || <em className="text-muted">No answer — the assistant handed off instead of guessing.</em>}</p>
              {(m.feedback as { comment?: string } | null)?.comment && (
                <p className="mt-2 text-xs text-muted">Feedback comment: {(m.feedback as { comment?: string }).comment}</p>
              )}
              {m.citations.length > 0 && (
                <div className="mt-4">
                  <h3 className="mb-2 text-sm font-medium">Citations</h3>
                  <CitationList citations={m.citations} />
                </div>
              )}
              {m.retrieval_trace && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-sm text-accent">Why this answer? (retrieval, scores, decision)</summary>
                  <div className="mt-3"><TraceView trace={m.retrieval_trace} /></div>
                </details>
              )}
            </li>
          ),
        )}
      </ol>
    </>
  );
}
