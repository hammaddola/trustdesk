import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { ActionForm, SubmitButton } from "@/components/forms";
import { TagPicker } from "@/components/tag-picker";
import { Badge, Card, Empty, ErrorBox, Input, Label, PageHeader, Select, Table, fmtDate, statusTone } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

import { addSource, uploadDocument } from "./actions";

export const metadata = { title: "Sources" };

const RUNNING = ["pending", "crawling", "parsing", "chunking", "embedding"];

export default async function SourcesPage() {
  let sources: S["SourceOut"][];
  let settings: S["SettingsOut"];
  try {
    [sources, settings] = await Promise.all([api<S["SourceOut"][]>("/v1/admin/sources"), api<S["SettingsOut"]>("/v1/admin/settings")]);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }
  const running = sources.some((s) => s.latest_job && RUNNING.includes(s.latest_job.status));
  return (
    <>
      <PageHeader title="Sources" description="The only content your assistant may answer from. Changes take effect once indexing finishes." />
      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card title="Add website or sitemap">
          <ActionForm action={addSource} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-[120px_1fr]">
              <div>
                <Label htmlFor="kind">Type</Label>
                <Select id="kind" name="kind" defaultValue="website">
                  <option value="website">Website</option>
                  <option value="sitemap">Sitemap</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="url">URL</Label>
                <Input id="url" name="url" type="url" required placeholder="https://www.example.com" />
              </div>
            </div>
            <p className="text-xs text-muted">
              Allowed domains: {settings.allowed_domains.join(", ") || "none yet"} (<Link href="/settings#domains">edit</Link>). Private and
              local addresses are always blocked.
            </p>
            <div>
              <Label htmlFor="max_pages">Maximum pages</Label>
              <Input id="max_pages" name="max_pages" type="number" min={1} max={2000} defaultValue={200} className="w-32" />
            </div>
            <TagPicker />
            <SubmitButton pending="Adding…">Add and crawl</SubmitButton>
          </ActionForm>
        </Card>
        <Card title="Upload a document">
          <ActionForm action={uploadDocument} className="space-y-3">
            <div>
              <Label htmlFor="file" hint="PDF or DOCX, up to 20 MB. Scanned PDFs without text are not supported.">File</Label>
              <input id="file" name="file" type="file" accept=".pdf,.docx" required
                className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-accent file:px-3 file:py-2 file:text-sm file:font-medium file:text-accent-fg" />
            </div>
            <TagPicker />
            <SubmitButton pending="Uploading…">Upload and index</SubmitButton>
          </ActionForm>
        </Card>
      </div>

      <div className="mb-2 flex justify-end">
        <AutoRefresh active={running} />
      </div>
      {sources.length === 0 ? (
        <Empty title="No sources yet">Add your website or upload a document to give the assistant something to answer from.</Empty>
      ) : (
        <Table head={["Source", "Status", "Documents", "Tags", "Last crawled", ""]}>
          {sources.map((s) => (
            <tr key={s.id} className={s.enabled ? "" : "opacity-60"}>
              <td className="max-w-xs px-4 py-3">
                <Link href={`/sources/${s.id}`} className="block truncate font-medium">
                  {s.root_url ?? s.title ?? "Uploaded document"}
                </Link>
                <span className="text-xs text-muted">{s.kind}{s.enabled ? "" : " · disabled"}</span>
              </td>
              <td className="px-4 py-3">
                <Badge tone={statusTone(s.latest_job?.status)}>{s.latest_job?.status ?? "—"}</Badge>
                {s.latest_job?.error_message && <p className="mt-1 max-w-xs text-xs text-danger">{s.latest_job.error_message}</p>}
              </td>
              <td className="px-4 py-3 text-sm">
                {s.indexed_count}/{s.document_count} indexed
                {s.failed_count > 0 && <span className="text-danger"> · {s.failed_count} failed</span>}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1">{s.tags.map((t) => <Badge key={t}>{t}</Badge>)}</div>
              </td>
              <td className="px-4 py-3 text-xs text-muted">{fmtDate(s.last_crawled_at)}</td>
              <td className="px-4 py-3 text-right">
                <Link href={`/sources/${s.id}`} className="text-sm">Details →</Link>
              </td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
