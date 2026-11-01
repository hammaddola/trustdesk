"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import type { FormState } from "@/app/auth-actions";
import { api, errorMessage } from "@/lib/api";

const TAGS = ["case-study", "founder", "pricing", "faq"];

function tagsFrom(form: FormData): string[] {
  return form.getAll("tags").map(String).filter((t) => TAGS.includes(t));
}

export async function addSource(_: FormState, form: FormData): Promise<FormState> {
  try {
    await api("/v1/admin/sources", {
      method: "POST",
      body: JSON.stringify({
        kind: form.get("kind") === "sitemap" ? "sitemap" : "website",
        url: String(form.get("url") ?? "").trim(),
        max_pages: Number(form.get("max_pages") ?? 200),
        tags: tagsFrom(form),
      }),
    });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  revalidatePath("/sources");
  return { ok: "Source added. Crawling has started — progress updates below." };
}

export async function uploadDocument(_: FormState, form: FormData): Promise<FormState> {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) return { error: "Choose a PDF or DOCX file." };
  const body = new FormData();
  body.set("file", file, file.name);
  body.set("tags", tagsFrom(form).join(","));
  try {
    await api("/v1/admin/sources/upload", { method: "POST", body });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  revalidatePath("/sources");
  return { ok: `Uploaded ${file.name}. Indexing has started.` };
}

export async function reindex(form: FormData): Promise<void> {
  await api(`/v1/admin/sources/${String(form.get("id"))}/reindex`, { method: "POST" });
  revalidatePath("/sources");
  revalidatePath(`/sources/${String(form.get("id"))}`);
}

export async function setSourceEnabled(form: FormData): Promise<void> {
  const id = String(form.get("id"));
  await api(`/v1/admin/sources/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: form.get("enabled") === "true" }) });
  revalidatePath("/sources");
  revalidatePath(`/sources/${id}`);
}

export async function setSourceTags(_: FormState, form: FormData): Promise<FormState> {
  const id = String(form.get("id"));
  try {
    await api(`/v1/admin/sources/${id}`, { method: "PATCH", body: JSON.stringify({ tags: tagsFrom(form) }) });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  revalidatePath(`/sources/${id}`);
  return { ok: "Tags saved." };
}

export async function deleteSource(form: FormData): Promise<void> {
  await api(`/v1/admin/sources/${String(form.get("id"))}`, { method: "DELETE" });
  revalidatePath("/sources");
  redirect("/sources");
}

export async function setDocumentEnabled(form: FormData): Promise<void> {
  await api(`/v1/admin/documents/${String(form.get("doc"))}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled: form.get("enabled") === "true" }),
  });
  revalidatePath(`/sources/${String(form.get("id"))}`);
}
