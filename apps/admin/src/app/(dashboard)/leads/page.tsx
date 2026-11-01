import Link from "next/link";
import { revalidatePath } from "next/cache";

import { Badge, Button, Empty, ErrorBox, Input, Label, PageHeader, Select, Table, fmtDate, statusTone } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

export const metadata = { title: "Leads" };

const STATUSES = ["new", "contacted", "qualified", "closed", "spam"] as const;

async function updateStatus(form: FormData) {
  "use server";
  const status = String(form.get("status"));
  if (!STATUSES.includes(status as (typeof STATUSES)[number])) return;
  await api(`/v1/admin/leads/${String(form.get("id"))}`, { method: "PATCH", body: JSON.stringify({ status }) });
  revalidatePath("/leads");
}

export default async function LeadsPage({ searchParams }: { searchParams: Promise<{ q?: string; status?: string; page?: string }> }) {
  const sp = await searchParams;
  const page = Math.max(0, Number(sp.page ?? 0) || 0);
  const filter = new URLSearchParams();
  if (sp.q) filter.set("q", sp.q.slice(0, 200));
  if (sp.status && STATUSES.includes(sp.status as (typeof STATUSES)[number])) filter.set("status", sp.status);
  let leads: S["LeadOut"][];
  try {
    leads = await api<S["LeadOut"][]>(`/v1/admin/leads?${filter}&limit=50&offset=${page * 50}`);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }
  return (
    <>
      <PageHeader
        title="Leads"
        description="People who asked to talk to your team. Each lead was saved before the visitor was told it was received."
        actions={<a href={`/api/leads.csv?${filter}`} className="inline-flex h-9 items-center rounded-lg border border-border-strong bg-raised px-3.5 text-sm font-medium text-heading no-underline hover:border-accent">Export CSV</a>}
      />
      <form role="search" className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        <div className="min-w-60 flex-1">
          <Label htmlFor="q">Search</Label>
          <Input id="q" name="q" defaultValue={sp.q} placeholder="Name, email or message" />
        </div>
        <div>
          <Label htmlFor="status">Status</Label>
          <Select id="status" name="status" defaultValue={sp.status ?? ""}>
            <option value="">Any</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </div>
        <Button type="submit">Filter</Button>
        <Link href="/leads" className="pb-2 text-sm">Reset</Link>
      </form>
      {leads.length === 0 ? (
        <Empty title="No leads yet">When the assistant can't answer, visitors can leave their details here.</Empty>
      ) : (
        <Table head={["Contact", "Summary", "Channel", "Received", "Status"]}>
          {leads.map((l) => (
            <tr key={l.id}>
              <td className="px-4 py-3 align-top">
                <p className="font-medium text-heading">{l.name ?? "—"}</p>
                {l.email && <a href={`mailto:${l.email}`} className="text-xs">{l.email}</a>}
                {l.phone && <p className="text-xs text-muted">{l.phone}</p>}
              </td>
              <td className="max-w-md px-4 py-3 align-top text-sm">
                {l.message && <p className="whitespace-pre-wrap text-heading" dir="auto">{l.message}</p>}
                {l.summary && <p className="mt-1 whitespace-pre-wrap text-xs text-muted" dir="auto">{l.summary}</p>}
                {l.conversation_id && <Link href={`/conversations/${l.conversation_id}`} className="text-xs">View conversation →</Link>}
              </td>
              <td className="px-4 py-3 align-top"><Badge>{l.channel}</Badge></td>
              <td className="px-4 py-3 align-top text-xs text-muted">{fmtDate(l.created_at)}</td>
              <td className="px-4 py-3 align-top">
                <form action={updateStatus} className="flex items-center gap-2">
                  <input type="hidden" name="id" value={l.id} />
                  <label htmlFor={`st-${l.id}`} className="sr-only">Status</label>
                  <Select id={`st-${l.id}`} name="status" defaultValue={l.status} className="h-8 w-32">
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </Select>
                  <button className="text-xs text-accent hover:underline">Save</button>
                </form>
                <div className="mt-1"><Badge tone={statusTone(l.status)}>{l.status}</Badge></div>
              </td>
            </tr>
          ))}
        </Table>
      )}
      <nav aria-label="Pagination" className="mt-4 flex justify-between text-sm">
        {page > 0 ? <Link href={`/leads?${filter}&page=${page - 1}`}>← Newer</Link> : <span />}
        {leads.length === 50 && <Link href={`/leads?${filter}&page=${page + 1}`}>Older →</Link>}
      </nav>
    </>
  );
}
