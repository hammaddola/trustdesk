import Link from "next/link";

import { Badge, Card, Empty, ErrorBox, PageHeader, fmtDate, statusTone } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

export const metadata = { title: "Insights" };

/** Phase 1 insights: questions the assistant could not (fully) answer, i.e. knowledge gaps to fill.
 *  Grouping similar questions and the weekly ranked gap report are Phase 2. */
export default async function InsightsPage() {
  let handedOff: S["ConversationRow"][];
  let lowConfidence: S["ConversationRow"][];
  try {
    [handedOff, lowConfidence] = await Promise.all([
      api<S["ConversationRow"][]>("/v1/admin/conversations?handoff=true&limit=100"),
      api<S["ConversationRow"][]>("/v1/admin/conversations?confidence=low&limit=100"),
    ]);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }
  const lowOnly = lowConfidence.filter((c) => !handedOff.some((h) => h.id === c.id));
  const List = ({ rows }: { rows: S["ConversationRow"][] }) => (
    <ul className="divide-y divide-border">
      {rows.map((c) => (
        <li key={c.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
          <Link href={`/conversations/${c.id}`} className="min-w-0 flex-1 truncate" dir="auto">{c.first_question ?? "(no question)"}</Link>
          {c.lowest_confidence && <Badge tone={statusTone(c.lowest_confidence)}>{c.lowest_confidence}</Badge>}
          <span className="text-xs text-muted">{fmtDate(c.last_message_at)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <>
      <PageHeader
        title="Insights"
        description="Knowledge gaps: questions your sources could not answer well. Add or improve content in Sources to close them."
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`Not answered — handed to a person (${handedOff.length})`}>
          {handedOff.length ? <List rows={handedOff} /> : <Empty title="No unanswered questions yet" />}
        </Card>
        <Card title={`Answered with limited evidence (${lowOnly.length})`}>
          {lowOnly.length ? <List rows={lowOnly} /> : <Empty title="No low-confidence answers yet" />}
        </Card>
      </div>
      <p className="mt-6 text-xs text-muted">Grouping of similar questions and a weekly ranked report are planned for a later phase.</p>
    </>
  );
}
