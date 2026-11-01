import { Badge, statusTone } from "./ui";

/** Renders a message's retrieval trace: candidates with scores, the answerability decision and
 *  per-sentence verification. Internal admin view only (never shown to visitors). */

type Cand = { chunk_id: string; title: string | null; section: string | null; url: string | null; vector: number | null; fts: number | null; rrf: number; rerank: number | null; preview: string };
type Trace = {
  rewritten_query?: string | null;
  fused?: Cand[];
  top?: Cand[];
  reranked?: boolean | null;
  gate?: { answerable: boolean; reasons: string[]; signals: Record<string, unknown> } | null;
  verification?: { sentence: string; kept: boolean; reason: string }[];
  timings_ms?: Record<string, number>;
};

const n = (v: number | null | undefined, digits = 3) => (v == null ? "—" : v.toFixed(digits));

export function TraceView({ trace }: { trace: unknown }) {
  const t = (trace ?? {}) as Trace;
  const topIds = new Set((t.top ?? []).map((c) => c.chunk_id));
  return (
    <div className="space-y-5 text-sm">
      {t.rewritten_query && (
        <p><span className="text-muted">Search query: </span><span className="text-heading" dir="auto">{t.rewritten_query}</span></p>
      )}
      {t.gate && (
        <div>
          <h4 className="mb-1 font-medium text-heading">
            Answerability decision: <Badge tone={t.gate.answerable ? "success" : "warning"}>{t.gate.answerable ? "answerable" : "refused before generation"}</Badge>
          </h4>
          <ul className="list-disc space-y-0.5 pl-5 text-body">{t.gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {Object.entries(t.gate.signals).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 border-b border-border py-0.5">
                <dt className="text-muted">{k.replaceAll("_", " ")}</dt>
                <dd className="text-heading">{v == null ? "—" : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {(t.fused?.length ?? 0) > 0 && (
        <div>
          <h4 className="mb-1 font-medium text-heading">Retrieved chunks ({t.fused!.length}) — {t.reranked ? "reranked" : "RRF order (no reranker)"}</h4>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="bg-raised text-muted">
                <tr>{["Source", "Vector", "Full-text", "RRF", "Rerank", "Used"].map((h) => <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-border">
                {t.fused!.map((c) => {
                  const top = (t.top ?? []).find((x) => x.chunk_id === c.chunk_id);
                  return (
                    <tr key={c.chunk_id} className={topIds.has(c.chunk_id) ? "bg-accent/5" : ""}>
                      <td className="max-w-sm px-3 py-2">
                        <p className="truncate font-medium text-heading">{c.title ?? "Untitled"}{c.section ? ` · ${c.section}` : ""}</p>
                        <p className="line-clamp-2 text-muted" dir="auto">{c.preview}</p>
                      </td>
                      <td className="px-3 py-2">{n(c.vector)}</td>
                      <td className="px-3 py-2">{n(c.fts)}</td>
                      <td className="px-3 py-2">{n(c.rrf, 4)}</td>
                      <td className="px-3 py-2">{n(top?.rerank ?? c.rerank)}</td>
                      <td className="px-3 py-2">{topIds.has(c.chunk_id) ? "top 5" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {(t.verification?.length ?? 0) > 0 && (
        <div>
          <h4 className="mb-1 font-medium text-heading">Sentence verification</h4>
          <ul className="space-y-1">
            {t.verification!.map((v, i) => (
              <li key={i} className="flex gap-2">
                <Badge tone={v.kept ? "success" : "danger"}>{v.kept ? "kept" : "removed"}</Badge>
                <span className="min-w-0 flex-1" dir="auto">{v.sentence}</span>
                <span className="text-xs text-muted">{v.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {t.timings_ms && (
        <p className="text-xs text-muted">
          Timings: {Object.entries(t.timings_ms).map(([k, v]) => `${k} ${v} ms`).join(" · ")}
        </p>
      )}
    </div>
  );
}

export function CitationList({ citations }: { citations: { marker: number; title: string | null; url: string | null; section: string | null; supporting_span?: string | null; evidence_snapshot?: string; evidence?: string; support_score?: number | null }[] }) {
  if (!citations.length) return null;
  return (
    <ol className="space-y-2">
      {citations.map((c) => (
        <li key={c.marker} className="rounded-lg border border-border bg-raised p-3 text-sm">
          <p className="font-medium text-heading">
            [{c.marker}] {c.title ?? "Untitled"}{c.section && c.section !== c.title ? ` · ${c.section}` : ""}
            {c.support_score != null && <span className="ml-2 text-xs font-normal text-muted">support {c.support_score.toFixed(2)}</span>}
          </p>
          {c.url && /^https?:\/\//.test(c.url) && <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-xs">{c.url}</a>}
          {c.supporting_span && <blockquote className="mt-2 border-l-2 border-accent pl-3 text-body" dir="auto">{c.supporting_span}</blockquote>}
          {(c.evidence_snapshot ?? c.evidence) && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-muted">Full evidence snapshot</summary>
              <p className="mt-1 whitespace-pre-wrap text-xs text-body" dir="auto">{c.evidence_snapshot ?? c.evidence}</p>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}
