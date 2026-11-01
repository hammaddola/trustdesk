import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/api";

const BASE = (process.env.AI_SERVICE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** Streams the CSV export through the admin server so the API token never reaches the browser. */
export async function GET(req: NextRequest) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "authentication required" }, { status: 401 });
  const qs = new URLSearchParams();
  for (const key of ["q", "status"]) {
    const v = req.nextUrl.searchParams.get(key);
    if (v) qs.set(key, v.slice(0, 200));
  }
  const res = await fetch(`${BASE}/v1/admin/leads.csv?${qs}`, { headers: { authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!res.ok) return NextResponse.json({ error: "export failed" }, { status: res.status });
  return new NextResponse(res.body, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="leads.csv"',
      "cache-control": "no-store",
    },
  });
}
