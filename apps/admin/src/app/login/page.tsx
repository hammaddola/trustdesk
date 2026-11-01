import Link from "next/link";

import { login } from "@/app/auth-actions";
import { ActionForm, SubmitButton } from "@/components/forms";
import { Logo } from "@/components/logo";
import { Input, Label } from "@/components/ui";
import { type S, api } from "@/lib/api";

export const metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string }> }) {
  const { expired } = await searchParams;
  let needsSetup = false;
  try {
    needsSetup = (await api<S["SetupStatus"]>("/v1/admin/setup/status", { auth: false })).needs_setup;
  } catch {
    /* service down: the form will show the error on submit */
  }
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <Logo />
          <h1 className="mt-4 text-xl font-semibold">Sign in to TrustDesk</h1>
          <p className="mt-1 text-sm text-muted">Evidence-grounded answers for your website.</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-6">
          {expired && <p className="mb-4 text-sm text-warning">Your session expired. Please sign in again.</p>}
          {needsSetup && (
            <p className="mb-4 text-sm">
              No account exists yet. <Link href="/setup">Run first-time setup →</Link>
            </p>
          )}
          <ActionForm action={login} className="space-y-4">
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" autoComplete="username" required />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" name="password" type="password" autoComplete="current-password" required />
            </div>
            <SubmitButton pending="Signing in…">Sign in</SubmitButton>
          </ActionForm>
        </div>
      </div>
    </main>
  );
}
