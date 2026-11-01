import "server-only";

import type { components } from "@trustdesk/contracts";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export type S = components["schemas"];

export const SESSION_COOKIE = "td_session";
const BASE = (process.env.AI_SERVICE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fields?: { field: string; message: string }[],
  ) {
    super(message);
  }
}

async function token(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Calls the AI service as the signed-in admin. Every permission check happens server-side in the API. */
export async function api<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  const { auth = true, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (!(rest.body instanceof FormData)) headers.set("content-type", "application/json");
  if (auth) {
    const t = await token();
    if (!t) redirect("/login");
    headers.set("authorization", `Bearer ${t}`);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...rest, headers, cache: "no-store" });
  } catch {
    throw new ApiError("The TrustDesk AI service is not reachable. Is `trustdesk serve` running?", 503);
  }
  if (res.status === 401 && auth) redirect("/login?expired=1");
  if (!res.ok) {
    let body: { error?: string; fields?: { field: string; message: string }[] } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(body.error ?? `Request failed (${res.status})`, res.status, body.fields);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? await res.json() : await res.text()) as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.fields?.length ? err.fields.map((f) => `${f.field}: ${f.message}`).join("; ") : err.message;
  }
  // Re-throw Next.js control-flow errors (redirect/notFound) instead of swallowing them.
  if (err && typeof err === "object" && "digest" in err) throw err;
  return "Something went wrong.";
}

export async function getSession(): Promise<S["SessionOut"]> {
  return api<S["SessionOut"]>("/v1/admin/auth/session");
}
