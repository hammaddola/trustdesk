import { revalidatePath } from "next/cache";

import type { FormState } from "@/app/auth-actions";
import { CopyButton } from "@/components/copy-button";
import { ActionForm, SubmitButton } from "@/components/forms";
import { Card, ErrorBox, Input, Label, PageHeader, Select, inputClass } from "@/components/ui";
import { type S, api, errorMessage, getSession } from "@/lib/api";

export const metadata = { title: "Settings" };

const lines = (v: FormDataEntryValue | null) =>
  String(v ?? "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
const optional = (v: FormDataEntryValue | null) => String(v ?? "").trim() || null;

async function save(_: FormState, form: FormData): Promise<FormState> {
  "use server";
  const budget = optional(form.get("monthly_budget_usd"));
  const body = {
    organization_name: String(form.get("organization_name") ?? "").trim(),
    description: optional(form.get("description")),
    industry: optional(form.get("industry")),
    audience: optional(form.get("audience")),
    founder_name: optional(form.get("founder_name")),
    founder_role: optional(form.get("founder_role")),
    website_urls: lines(form.get("website_urls")),
    allowed_domains: lines(form.get("allowed_domains")),
    allowed_origins: lines(form.get("allowed_origins")),
    default_language: String(form.get("default_language") ?? "en"),
    timezone: String(form.get("timezone") ?? "UTC").trim() || "UTC",
    llm_provider: optional(form.get("llm_provider")),
    llm_model: optional(form.get("llm_model")),
    reranker_provider: optional(form.get("reranker_provider")),
    confidence_threshold: Number(form.get("confidence_threshold")),
    max_answer_tokens: Number(form.get("max_answer_tokens")),
    monthly_budget_usd: budget === null ? null : Number(budget),
    budget_warning_pct: Number(form.get("budget_warning_pct") ?? 80),
    budget_hard_limit: form.get("budget_hard_limit") === "on",
    greeting: optional(form.get("greeting")),
    widget_theme: {
      primary: optional(form.get("primary")),
      accent: optional(form.get("accent")),
      mode: String(form.get("mode") ?? "auto"),
      position: String(form.get("position") ?? "right"),
      launcher_text: optional(form.get("launcher_text")),
    },
    handoff_channels: {
      email: { enabled: form.get("email_enabled") === "on", to: optional(form.get("email_to")) },
      whatsapp: { enabled: form.get("whatsapp_enabled") === "on", number: optional(form.get("whatsapp_number")) },
      booking: { enabled: form.get("booking_enabled") === "on", url: optional(form.get("booking_url")) },
    },
    mark_setup_complete: form.get("mark_setup_complete") === "on" ? true : undefined,
  };
  try {
    await api("/v1/admin/settings", { method: "PATCH", body: JSON.stringify(body) });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  revalidatePath("/", "layout");
  return { ok: "Settings saved. The widget picks up changes within 30 seconds." };
}

type Handoff = { email?: { enabled?: boolean; to?: string }; whatsapp?: { enabled?: boolean; number?: string }; booking?: { enabled?: boolean; url?: string } };
type Theme = { primary?: string; accent?: string; mode?: string; position?: string; launcher_text?: string };

export default async function SettingsPage() {
  let s: S["SettingsOut"];
  let role: string;
  try {
    [s, { role }] = await Promise.all([api<S["SettingsOut"]>("/v1/admin/settings"), getSession()]);
  } catch (err) {
    return <ErrorBox message={errorMessage(err)} />;
  }
  const readOnly = role !== "owner";
  const h = s.handoff_channels as Handoff;
  const t = s.widget_theme as Theme;
  const cdn = (process.env.WIDGET_CDN_URL ?? "https://YOUR-CDN").replace(/\/+$/, "");
  const apiUrl = (process.env.PUBLIC_AI_SERVICE_URL ?? process.env.AI_SERVICE_URL ?? "https://YOUR-API").replace(/\/+$/, "");
  const embed = `<script src="${cdn}/trustdesk.js" data-tenant="${s.public_key}" data-api="${apiUrl}" defer></script>`;
  const area = `${inputClass} h-auto py-2`;

  return (
    <>
      <PageHeader title="Settings" description={readOnly ? "Only owners can change settings. You have read-only access." : "Changes apply to this organization only."} />
      <Card title="Install the widget" className="mb-6">
        <p className="mb-2 text-sm">Paste this before <code>&lt;/body&gt;</code> on every page. The key is public and safe to embed; it is not a secret.</p>
        <pre className="overflow-x-auto rounded-lg border border-border bg-raised p-3 text-xs text-heading"><code>{embed}</code></pre>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
          <CopyButton text={embed} />
          <span>WordPress: add via a header/footer code plugin · Webflow/Wix/Squarespace: Custom code → Footer · Shopify: theme.liquid before &lt;/body&gt;.</span>
        </div>
        <p className="mt-2 text-xs text-muted">The page’s origin must be listed in “Allowed widget origins” below.</p>
      </Card>

      <ActionForm action={save} className="space-y-6">
        <fieldset disabled={readOnly} className="space-y-6">
          <Card title="Organization">
            <div className="grid gap-4 md:grid-cols-2">
              <div><Label htmlFor="organization_name">Name</Label><Input id="organization_name" name="organization_name" defaultValue={s.organization_name} required maxLength={200} /></div>
              <div><Label htmlFor="industry">Industry</Label><Input id="industry" name="industry" defaultValue={s.industry ?? ""} maxLength={100} /></div>
              <div className="md:col-span-2"><Label htmlFor="description">One-line description</Label><Input id="description" name="description" defaultValue={s.description ?? ""} maxLength={500} /></div>
              <div><Label htmlFor="audience">Target customers</Label><Input id="audience" name="audience" defaultValue={s.audience ?? ""} maxLength={200} /></div>
              <div><Label htmlFor="timezone">Timezone</Label><Input id="timezone" name="timezone" defaultValue={s.timezone} maxLength={64} /></div>
              <div><Label htmlFor="founder_name" hint="Optional. Enables “Ask the Founder” in a later phase.">Founder / spokesperson</Label><Input id="founder_name" name="founder_name" defaultValue={s.founder_name ?? ""} maxLength={200} /></div>
              <div><Label htmlFor="founder_role">Their role</Label><Input id="founder_role" name="founder_role" defaultValue={s.founder_role ?? ""} maxLength={200} /></div>
            </div>
          </Card>

          <Card title="Website & security" >
            <div id="domains" className="grid gap-4 md:grid-cols-3">
              <div><Label htmlFor="website_urls" hint="One per line.">Website URLs</Label><textarea id="website_urls" name="website_urls" rows={3} defaultValue={s.website_urls.join("\n")} className={area} /></div>
              <div><Label htmlFor="allowed_domains" hint="Crawling is restricted to these domains (and subdomains).">Allowed crawl domains</Label><textarea id="allowed_domains" name="allowed_domains" rows={3} defaultValue={s.allowed_domains.join("\n")} className={area} /></div>
              <div id="widget"><Label htmlFor="allowed_origins" hint="Exact origins like https://www.example.com. Wildcards are not allowed.">Allowed widget origins</Label><textarea id="allowed_origins" name="allowed_origins" rows={3} defaultValue={s.allowed_origins.join("\n")} className={area} /></div>
            </div>
          </Card>

          <Card title="Answers">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <Label htmlFor="llm_provider" hint="Blank = server default. API keys are configured on the server, never here.">Model provider</Label>
                <Select id="llm_provider" name="llm_provider" defaultValue={s.llm_provider ?? ""}>
                  <option value="">Server default</option>
                  <option value="ollama">Ollama (local)</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic Claude</option>
                  <option value="openai_compat">OpenAI-compatible</option>
                </Select>
              </div>
              <div><Label htmlFor="llm_model">Model name</Label><Input id="llm_model" name="llm_model" defaultValue={s.llm_model ?? ""} placeholder="Server default" maxLength={100} /></div>
              <div>
                <Label htmlFor="reranker_provider">Reranker</Label>
                <Select id="reranker_provider" name="reranker_provider" defaultValue={s.reranker_provider ?? ""}>
                  <option value="">Server default</option>
                  <option value="local">Local cross-encoder</option>
                  <option value="cohere">Cohere</option>
                  <option value="none">None (stricter evidence gate)</option>
                </Select>
              </div>
              <div><Label htmlFor="confidence_threshold" hint="Minimum evidence relevance (0.05–0.95) before the assistant may answer. Higher = refuses more.">Evidence threshold</Label><Input id="confidence_threshold" name="confidence_threshold" type="number" step="0.01" min={0.05} max={0.95} defaultValue={s.confidence_threshold} required /></div>
              <div><Label htmlFor="max_answer_tokens">Max answer length (tokens)</Label><Input id="max_answer_tokens" name="max_answer_tokens" type="number" min={50} max={4000} defaultValue={s.max_answer_tokens} required /></div>
              <div>
                <Label htmlFor="default_language">Default language</Label>
                <Select id="default_language" name="default_language" defaultValue={s.default_language}>
                  <option value="en">English</option>
                  <option value="ur">Urdu</option>
                  <option value="ur-Latn">Roman Urdu</option>
                </Select>
              </div>
            </div>
            {s.embedding_index && <p className="mt-3 text-xs text-muted">Embedding index: {String(s.embedding_index.provider)}/{String(s.embedding_index.model)} ({String(s.embedding_index.dimension)} dimensions).</p>}
          </Card>

          <Card title="Widget appearance">
            <div className="grid gap-4 md:grid-cols-3">
              <div><Label htmlFor="primary" hint="#RRGGBB">Primary color</Label><Input id="primary" name="primary" defaultValue={t.primary ?? ""} pattern="^#[0-9a-fA-F]{6}$" placeholder="#AA97FD" /></div>
              <div><Label htmlFor="accent" hint="#RRGGBB">Accent color</Label><Input id="accent" name="accent" defaultValue={t.accent ?? ""} pattern="^#[0-9a-fA-F]{6}$" placeholder="#AA97FD" /></div>
              <div><Label htmlFor="launcher_text">Launcher text</Label><Input id="launcher_text" name="launcher_text" defaultValue={t.launcher_text ?? ""} placeholder="Ask us anything" maxLength={40} /></div>
              <div>
                <Label htmlFor="mode">Theme</Label>
                <Select id="mode" name="mode" defaultValue={t.mode ?? "auto"}>
                  <option value="auto">Match visitor’s system</option><option value="light">Light</option><option value="dark">Dark</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="position">Position</Label>
                <Select id="position" name="position" defaultValue={t.position ?? "right"}>
                  <option value="right">Bottom right</option><option value="left">Bottom left</option>
                </Select>
              </div>
              <div className="md:col-span-3"><Label htmlFor="greeting">Greeting</Label><Input id="greeting" name="greeting" defaultValue={s.greeting ?? ""} maxLength={300} /></div>
            </div>
          </Card>

          <Card title="Handoff — when the assistant can’t answer">
            <div id="handoff" className="grid gap-5 md:grid-cols-3">
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm font-medium text-heading"><input type="checkbox" name="email_enabled" defaultChecked={h.email?.enabled} /> Email form</label>
                <Label htmlFor="email_to" hint="Where new leads are emailed (not shown to visitors).">Team email</Label>
                <Input id="email_to" name="email_to" type="email" defaultValue={h.email?.to ?? ""} />
              </div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm font-medium text-heading"><input type="checkbox" name="whatsapp_enabled" defaultChecked={h.whatsapp?.enabled} /> WhatsApp</label>
                <Label htmlFor="whatsapp_number" hint="International format, e.g. +15550001111">Business number</Label>
                <Input id="whatsapp_number" name="whatsapp_number" defaultValue={h.whatsapp?.number ?? ""} />
              </div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm font-medium text-heading"><input type="checkbox" name="booking_enabled" defaultChecked={h.booking?.enabled} /> Book a call</label>
                <Label htmlFor="booking_url" hint="Cal.com, Calendly or any https link.">Booking link</Label>
                <Input id="booking_url" name="booking_url" type="url" defaultValue={h.booking?.url ?? ""} />
              </div>
            </div>
          </Card>

          <Card title="Usage & budget">
            <p className="mb-3 text-sm">Spent this month: <strong className="text-heading">${s.spend_this_month_usd.toFixed(2)}</strong> <span className="text-xs text-muted">(estimated; local models cost $0; cloud prices come from MODEL_PRICES_JSON on the server)</span></p>
            <div className="grid gap-4 md:grid-cols-3">
              <div><Label htmlFor="monthly_budget_usd" hint="Blank = no limit.">Monthly budget (USD)</Label><Input id="monthly_budget_usd" name="monthly_budget_usd" type="number" step="0.01" min={0} defaultValue={s.monthly_budget_usd ?? ""} /></div>
              <div><Label htmlFor="budget_warning_pct">Warn at (%)</Label><Input id="budget_warning_pct" name="budget_warning_pct" type="number" min={1} max={100} defaultValue={s.budget_warning_pct} /></div>
              <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" name="budget_hard_limit" defaultChecked={s.budget_hard_limit} /> Stop answering when the budget is reached</label>
            </div>
          </Card>

          {!s.setup_completed && (
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="mark_setup_complete" /> I’ve tested the assistant in the Playground — mark setup complete</label>
          )}
          {!readOnly && <SubmitButton>Save settings</SubmitButton>}
        </fieldset>
      </ActionForm>
    </>
  );
}
