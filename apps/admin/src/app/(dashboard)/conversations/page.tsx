import Link from "next/link";

import { Badge, Button, Empty, ErrorBox, Input, Label, PageHeader, Select, Table, fmtDate, statusTone } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

export const metadata = { title: "Conversations" };

type Search = { q?: string; since?: string; until?: string; confidence?: string; handoff?: string; channel?: string; page?: string };

export default async function ConversationsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const page = Math.max(0, Number(sp.page ?? 0) || 0);
  const qs = new URLSearchParams({ limit: "50", offset: String(page * 50), channel: sp.channel === "playground" ? "playground" : "widget" });
  if (sp.q) qs.set("q", sp.q.slice(0, 200));
  if (sp.since) qs.set("since", `${sp.since}T00:00:00Z`);
  if (sp.until) qs.set("until", `${sp.until}T23:59:59Z`);
  if (sp.confidence && ["high", "medium", "low"].includes(sp.confidence)) qs.set("confidence", sp.confidence);
  if (sp.handoff === "true" || sp.handoff === "false") qs.set("handoff", sp.handoff);
  let rows: S["ConversationRow"][];
  try {
    rows = await api<S["ConversationRow"][]>(`/v1/admin/conversations?${qs}`);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }
  const pageLink = (p: number) => `/conversations?${new URLSearchParams({ ...sp, page: String(p) } as Record<string, string>)}`;
  return (
    <>
      <PageHeader title="Conversations" description="What visitors asked, what the assistant answered, and which sources it cited." />
      <form className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-6" role="search">
        <div className="lg:col-span-2">
          <Label htmlFor="q">Search messages</Label>
          <Input id="q" name="q" defaultValue={sp.q} placeholder="e.g. pricing" />
        </div>
        <div>
          <Label htmlFor="since">From</Label>
          <Input id="since" name="since" type="date" defaultValue={sp.since} />
        </div>
        <div>
          <Label htmlFor="until">To</Label>
          <Input id="until" name="until" type="date" defaultValue={sp.until} />
        </div>
        <div>
          <Label htmlFor="confidence">Confidence</Label>
          <Select id="confidence" name="confidence" defaultValue={sp.confidence ?? ""}>
            <option value="">Any</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </Select>
        </div>
        <div>
          <Label htmlFor="handoff">Handoff</Label>
          <Select id="handoff" name="handoff" defaultValue={sp.handoff ?? ""}>
            <option value="">Any</option>
            <option value="true">Handed off</option>
            <option value="false">Not handed off</option>
          </Select>
        </div>
        <div>
          <Label htmlFor="channel">Channel</Label>
          <Select id="channel" name="channel" defaultValue={sp.channel ?? "widget"}>
            <option value="widget">Website widget</option>
            <option value="playground">Playground tests</option>
          </Select>
        </div>
        <div className="flex items-end gap-2 lg:col-span-5">
          <Button type="submit">Apply filters</Button>
          <Link href="/conversations" className="text-sm">Reset</Link>
        </div>
      </form>
      {rows.length === 0 ? (
        <Empty title="No conversations match">Try different filters, or wait for visitors to use the widget.</Empty>
      ) : (
        <Table head={["First question", "Messages", "Lowest confidence", "Status", "Last activity"]}>
          {rows.map((c) => (
            <tr key={c.id}>
              <td className="max-w-md px-4 py-3">
                <Link href={`/conversations/${c.id}`} className="line-clamp-2" dir="auto">{c.first_question ?? "(no question)"}</Link>
                {c.language && <span className="text-xs text-muted">{c.language}</span>}
              </td>
              <td className="px-4 py-3 text-sm">{c.message_count}</td>
              <td className="px-4 py-3">{c.lowest_confidence ? <Badge tone={statusTone(c.lowest_confidence)}>{c.lowest_confidence}</Badge> : "—"}</td>
              <td className="px-4 py-3"><Badge tone={statusTone(c.status)}>{c.handoff ? "handed off" : c.status}</Badge></td>
              <td className="px-4 py-3 text-xs text-muted">{fmtDate(c.last_message_at)}</td>
            </tr>
          ))}
        </Table>
      )}
      <nav aria-label="Pagination" className="mt-4 flex justify-between text-sm">
        {page > 0 ? <Link href={pageLink(page - 1)}>← Newer</Link> : <span />}
        {rows.length === 50 && <Link href={pageLink(page + 1)}>Older →</Link>}
      </nav>
    </>
  );
}
