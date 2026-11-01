import Link from "next/link";
import { notFound } from "next/navigation";

import { AutoRefresh, ConfirmButton } from "@/components/auto-refresh";
import { ActionForm, SubmitButton } from "@/components/forms";
import { Badge, Button, Card, ErrorBox, PageHeader, Table, fmtDate, statusTone } from "@/components/ui";
import { ApiError, type S, api, errorMessage } from "@/lib/api";

import { deleteSource, reindex, setDocumentEnabled, setSourceEnabled, setSourceTags } from "../actions";
import { TagPicker } from "@/components/tag-picker";

export const metadata = { title: "Source" };
const RUNNING = ["pending", "crawling", "parsing", "chunking", "embedding"];

export default async function SourceDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let d: S["SourceDetail"];
  try {
    d = await api<S["SourceDetail"]>(`/v1/admin/sources/${encodeURIComponent(id)}`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) notFound();
    return <ErrorBox message={errorMessage(err)} />;
  }
  const s = d.source;
  const running = d.jobs.some((j) => RUNNING.includes(j.status));
  return (
    <>
      <p className="mb-2 text-sm"><Link href="/sources">← Sources</Link></p>
      <PageHeader
        title={s.root_url ?? s.title ?? "Uploaded document"}
        description={`${s.kind} · added ${fmtDate(s.created_at)}${s.enabled ? "" : " · disabled (not used for answers)"}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <form action={reindex}>
              <input type="hidden" name="id" value={s.id} />
              <Button variant="secondary" disabled={running}>Re-index</Button>
            </form>
            <form action={setSourceEnabled}>
              <input type="hidden" name="id" value={s.id} />
              <input type="hidden" name="enabled" value={String(!s.enabled)} />
              <Button variant="secondary">{s.enabled ? "Disable" : "Enable"}</Button>
            </form>
            <form action={deleteSource}>
              <input type="hidden" name="id" value={s.id} />
              <ConfirmButton
                message="Delete this source and all of its indexed content? Past answers keep their evidence snapshots."
                className="inline-flex h-9 items-center rounded-lg border border-danger/40 px-3.5 text-sm font-medium text-danger hover:bg-danger/10"
              >
                Delete
              </ConfirmButton>
            </form>
          </div>
        }
      />
      <AutoRefresh active={running} />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title={`Documents (${d.documents.length})`}>
          {d.documents.length === 0 ? (
            <p className="text-sm text-muted">No documents yet{running ? " — crawling…" : ""}.</p>
          ) : (
            <Table head={["Document", "Status", "Version", "Freshness", ""]}>
              {d.documents.map((doc) => (
                <tr key={doc.id} className={doc.enabled ? "" : "opacity-60"}>
                  <td className="max-w-xs px-4 py-3">
                    <p className="truncate font-medium text-heading">{doc.title ?? doc.url ?? "Untitled"}</p>
                    {doc.url && <a href={doc.url} target="_blank" rel="noopener noreferrer" className="block truncate text-xs">{doc.url}</a>}
                    {doc.last_error && <p className="mt-1 text-xs text-danger">{doc.last_error}</p>}
                  </td>
                  <td className="px-4 py-3"><Badge tone={statusTone(doc.status)}>{doc.status}</Badge></td>
                  <td className="px-4 py-3 text-xs">{doc.version_no ? `v${doc.version_no} · ${doc.chunk_count} chunks` : "—"}</td>
                  <td className="px-4 py-3 text-xs text-muted">
                    Indexed {fmtDate(doc.version_indexed_at)}
                    {doc.source_last_modified && <><br />Page updated {fmtDate(doc.source_last_modified)}</>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <form action={setDocumentEnabled}>
                      <input type="hidden" name="id" value={s.id} />
                      <input type="hidden" name="doc" value={doc.id} />
                      <input type="hidden" name="enabled" value={String(!doc.enabled)} />
                      <button className="text-xs text-accent hover:underline">{doc.enabled ? "Disable" : "Enable"}</button>
                    </form>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Tags">
            <ActionForm action={setSourceTags} className="space-y-3">
              <input type="hidden" name="id" value={s.id} />
              <TagPicker selected={s.tags} />
              <SubmitButton variant="secondary">Save tags</SubmitButton>
            </ActionForm>
          </Card>
          <Card title="Indexing history">
            <ul className="space-y-3 text-sm">
              {d.jobs.map((j) => (
                <li key={j.id}>
                  <div className="flex items-center gap-2">
                    <Badge tone={statusTone(j.status)}>{j.status}</Badge>
                    <span className="text-xs text-muted">{fmtDate(j.created_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {Object.entries(j.progress).map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`).join(" · ") || j.kind}
                  </p>
                  {j.error_message && <p className="text-xs text-danger">{j.error_message}</p>}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
