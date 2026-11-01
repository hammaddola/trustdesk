"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SESSION_COOKIE, type S, api, errorMessage } from "@/lib/api";

export type FormState = { error?: string; ok?: string } | undefined;

async function setSessionCookie(token: string, maxAge: number) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  });
}

export async function login(_: FormState, form: FormData): Promise<FormState> {
  let out: S["LoginOut"];
  try {
    out = await api<S["LoginOut"]>("/v1/admin/auth/login", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email: String(form.get("email") ?? ""), password: String(form.get("password") ?? "") }),
    });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  await setSessionCookie(out.token, out.expires_in_seconds);
  redirect("/");
}

export async function logout(): Promise<void> {
  try {
    await api("/v1/admin/auth/logout", { method: "POST" });
  } catch {
    /* session may already be gone; clear the cookie regardless */
  }
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}

export async function setup(_: FormState, form: FormData): Promise<FormState> {
  const password = String(form.get("password") ?? "");
  if (password !== String(form.get("confirm") ?? "")) return { error: "Passwords do not match." };
  let out: S["LoginOut"];
  try {
    out = await api<S["LoginOut"]>("/v1/admin/setup", {
      method: "POST",
      auth: false,
      body: JSON.stringify({
        setup_token: String(form.get("setup_token") ?? ""),
        organization_name: String(form.get("organization_name") ?? ""),
        website_url: String(form.get("website_url") ?? ""),
        email: String(form.get("email") ?? ""),
        password,
      }),
    });
  } catch (err) {
    return { error: errorMessage(err) };
  }
  await setSessionCookie(out.token, out.expires_in_seconds);
  redirect("/?welcome=1");
}

export async function switchTenant(form: FormData): Promise<void> {
  await api("/v1/admin/auth/switch-tenant", {
    method: "POST",
    body: JSON.stringify({ tenant_id: String(form.get("tenant_id")) }),
  });
  redirect("/");
}
