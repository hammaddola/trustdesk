import { redirect } from "next/navigation";

import { setup } from "@/app/auth-actions";
import { Logo } from "@/components/logo";
import { ActionForm, SubmitButton } from "@/components/forms";
import { Input, Label } from "@/components/ui";
import { type S, api } from "@/lib/api";

export const metadata = { title: "First-time setup" };

const STEPS = ["Organization & account", "Add website and documents", "Brand & greeting", "Handoff channels", "Test in Playground", "Copy embed code"];

export default async function SetupPage() {
  const status = await api<S["SetupStatus"]>("/v1/admin/setup/status", { auth: false }).catch(() => null);
  if (status && !status.needs_setup) redirect("/login");
  return (
    <main className="mx-auto grid min-h-screen max-w-4xl items-center gap-10 p-6 md:grid-cols-[1fr_1.3fr]">
      <div>
        <Logo />
        <h1 className="mt-6 text-2xl font-semibold">Set up your assistant</h1>
        <p className="mt-2 text-sm text-muted">
          TrustDesk answers only from content you approve. Step 1 creates your organization and owner account; the
          dashboard then guides you through the rest.
        </p>
        <ol className="mt-6 space-y-2 text-sm">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-3">
              <span className={`grid h-6 w-6 place-items-center rounded-full text-xs ${i === 0 ? "bg-accent text-accent-fg" : "border border-border-strong text-muted"}`}>
                {i + 1}
              </span>
              <span className={i === 0 ? "text-heading" : "text-muted"}>{s}</span>
            </li>
          ))}
        </ol>
      </div>
      <div className="rounded-xl border border-border bg-card p-6">
        {!status && <p className="mb-4 text-sm text-danger">The TrustDesk AI service is not reachable.</p>}
        <ActionForm action={setup} className="space-y-4">
          <div>
            <Label htmlFor="setup_token" hint="The TRUSTDESK_SETUP_TOKEN value from your server's .env file.">
              Setup token
            </Label>
            <Input id="setup_token" name="setup_token" type="password" required autoComplete="off" />
          </div>
          <div>
            <Label htmlFor="organization_name">Organization name</Label>
            <Input id="organization_name" name="organization_name" required maxLength={200} />
          </div>
          <div>
            <Label htmlFor="website_url" hint="Its domain becomes the first allowed crawl domain and widget origin.">
              Website URL
            </Label>
            <Input id="website_url" name="website_url" type="url" placeholder="https://www.example.com" required />
          </div>
          <div>
            <Label htmlFor="email">Your email</Label>
            <Input id="email" name="email" type="email" autoComplete="email" required />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="password" hint="At least 12 characters.">Password</Label>
              <Input id="password" name="password" type="password" minLength={12} autoComplete="new-password" required />
            </div>
            <div>
              <Label htmlFor="confirm">Confirm password</Label>
              <Input id="confirm" name="confirm" type="password" minLength={12} autoComplete="new-password" required />
            </div>
          </div>
          <SubmitButton pending="Creating…">Create organization</SubmitButton>
        </ActionForm>
      </div>
    </main>
  );
}
