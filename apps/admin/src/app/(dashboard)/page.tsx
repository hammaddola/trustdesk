import Link from "next/link";

import { Badge, Card, Empty, ErrorBox, PageHeader, fmtDate, statusTone } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

export const metadata = { title: "Overview" };

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

export default async function OverviewPage({ searchParams }: { searchParams: Promise<{ days?: string; welcome?: string }> }) {
  const { days = "30", welcome } = await searchParams;
  const period = ["7", "30", "90"].includes(days) ? days : "30";
  let data: S["Overview"];
  let settings: S["SettingsOut"];
  try {
    [data, settings] = await Promise.all([
      api<S["Overview"]>(`/v1/admin/overview?days=${period}`),
      api<S["SettingsOut"]>("/v1/admin/settings"),
    ]);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }

  const checklist = [
    { done: data.indexed_documents > 0, label: "Add your website or documents", href: "/sources" },
    { done: Object.values(settings.handoff_channels).some((c) => (c as { enabled?: boolean })?.enabled), label: "Set up a handoff channel", href: "/settings#handoff" },
    { done: settings.allowed_origins.length > 0, label: "Allow your website's origin for the widget", href: "/settings#widget" },
    { done: settings.setup_completed, label: "Test answers in the Playground, then mark setup complete", href: "/playground" },
  ];
  const stats: Array<[string, string, string?]> = [
    ["Conversations", String(data.conversations)],
    ["Questions", String(data.questions)],
    ["Answered", String(data.answered), "answered or partially answered"],
    ["Handoffs", String(data.handoffs), "visitor offered a human"],
    ["Citation coverage", pct(data.citation_coverage), "answers with ≥1 verified source"],
    ["Helpful rate", pct(data.helpful_rate), `${data.feedback_count} ratings`],
    ["Indexed documents", String(data.indexed_documents)],
    ["Failed indexing jobs", String(data.failed_jobs)],
  ];

  return (
    <>
      <PageHeader
        title="Overview"
        description="Real activity from your website widget. Playground tests are excluded."
        actions={
          <nav aria-label="Period" className="flex gap-1 rounded-lg border border-border p-1 text-sm">
            {["7", "30", "90"].map((d) => (
              <Link key={d} href={`/?days=${d}`} aria-current={d === period ? "page" : undefined}
                className={`rounded-md px-2.5 py-1 no-underline ${d === period ? "bg-accent text-accent-fg" : "text-body hover:text-heading"}`}>
                {d} days
              </Link>
            ))}
          </nav>
        }
      />
      {welcome && (
        <p className="mb-6 rounded-lg border border-accent/40 bg-accent/10 px-4 py-3 text-sm text-heading">
          Your organization is ready. Follow the checklist below to finish setup.
        </p>
      )}
      {!settings.setup_completed && (
        <Card title="Getting started" className="mb-6">
          <ol className="space-y-2">
            {checklist.map((c, i) => (
              <li key={c.label} className="flex items-center gap-3 text-sm">
                <span aria-hidden="true" className={`grid h-6 w-6 place-items-center rounded-full text-xs ${c.done ? "bg-success/20 text-success" : "border border-border-strong text-muted"}`}>
                  {c.done ? "✓" : i + 1}
                </span>
                <Link href={c.href} className={c.done ? "text-muted line-through" : ""}>{c.label}</Link>
                <span className="sr-only">{c.done ? "(done)" : "(to do)"}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map(([label, value, hint]) => (
          <div key={label} className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-muted">{label}</p>
            <p className="mt-1 text-2xl font-semibold text-heading">{value}</p>
            {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
          </div>
        ))}
      </div>
      {settings.budget_warning && (
        <p className="mt-6 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
          Spending this month (${settings.spend_this_month_usd.toFixed(2)}) has passed your warning level.
        </p>
      )}
      <Card title="Recent answers" className="mt-6">
        {data.recent.length === 0 ? (
          <Empty title="No conversations yet">Answers appear here once visitors use the widget.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {data.recent.map((r) => (
              <li key={String(r.message_id)} className="flex flex-wrap items-center gap-3 py-3 text-sm">
                <Badge tone={statusTone(String(r.status))}>{String(r.status ?? "—")}</Badge>
                {r.confidence ? <Badge tone={statusTone(String(r.confidence))}>{String(r.confidence)}</Badge> : null}
                <Link href={`/conversations/${String(r.conversation_id)}`} className="min-w-0 flex-1 truncate text-body hover:text-heading">
                  {String(r.preview || "(handed off without an answer)")}
                </Link>
                <span className="text-xs text-muted">{fmtDate(String(r.created_at))}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
