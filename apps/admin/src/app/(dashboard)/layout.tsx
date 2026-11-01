import type { ReactNode } from "react";

import { logout, switchTenant } from "@/app/auth-actions";
import { Logo } from "@/components/logo";
import { NavLinks } from "@/components/nav";
import { getSession } from "@/lib/api";

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const session = await getSession(); // validated by the API on every request; redirects to /login if invalid
  const current = session.memberships.find((m) => m.tenant_id === session.tenant_id);
  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-border bg-raised md:sticky md:top-0 md:h-screen md:border-b-0 md:border-r">
        <div className="flex h-full flex-col gap-6 p-4">
          <Logo />
          {session.mode === "platform" && session.memberships.length > 1 ? (
            <form action={switchTenant} className="flex gap-2">
              <label htmlFor="tenant" className="sr-only">Organization</label>
              <select id="tenant" name="tenant_id" defaultValue={session.tenant_id} className="h-9 flex-1 rounded-lg border border-border-strong bg-card px-2 text-sm text-heading">
                {session.memberships.map((m) => (
                  <option key={m.tenant_id} value={m.tenant_id}>{m.tenant_name}</option>
                ))}
              </select>
              <button className="text-xs text-accent">Switch</button>
            </form>
          ) : (
            <p className="truncate text-sm text-muted" title={current?.tenant_name}>{current?.tenant_name}</p>
          )}
          <NavLinks />
          <div className="mt-auto border-t border-border pt-4 text-xs text-muted">
            <p className="truncate" title={session.email}>{session.email}</p>
            <p className="capitalize">{session.role}</p>
            <form action={logout}>
              <button className="mt-2 text-accent hover:underline">Sign out</button>
            </form>
          </div>
        </div>
      </aside>
      <main className="min-w-0 p-4 md:p-8">{children}</main>
    </div>
  );
}
