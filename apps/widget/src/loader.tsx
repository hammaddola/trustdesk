/**
 * TrustDesk widget loader. Install with one tag:
 *   <script src="https://YOUR-CDN/trustdesk.js" data-tenant="td_pk_..." data-api="https://api.example.com" defer></script>
 *
 * Renders inside a closed-over Shadow DOM so host-page CSS cannot leak in and widget CSS cannot leak out.
 * Initialization never throws into the host page.
 */
import { createClient } from "@trustdesk/sdk";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { LightDomContext } from "./lib/lightDom";
import css from "./styles.css?inline";

export const VERSION = "0.1.0";
const HOST_TAG = "trustdesk-widget";

declare global {
  interface Window {
    __trustdesk?: { version: string; destroy(): void };
  }
}

export interface MountOptions {
  publicKey: string;
  apiUrl: string;
  theme?: "light" | "dark" | "auto";
}

function storage(): Storage | null {
  try {
    const s = window.localStorage;
    s.setItem("__td", "1");
    s.removeItem("__td");
    return s;
  } catch {
    return null; // privacy mode / blocked storage: fall back to in-memory ids
  }
}

function visitor(): { id: string; firstVisit: boolean } {
  const s = storage();
  const existing = s?.getItem("trustdesk.visitor");
  if (existing && /^[0-9a-f-]{36}$/.test(existing)) return { id: existing, firstVisit: false };
  const id = crypto.randomUUID();
  s?.setItem("trustdesk.visitor", id);
  return { id, firstVisit: true };
}

const HEX = /^#([0-9a-f]{6})$/i;
function hexToRgb(hex: unknown): string | null {
  const m = typeof hex === "string" ? HEX.exec(hex) : null;
  if (!m?.[1]) return null;
  const n = parseInt(m[1], 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

export function mount(opts: MountOptions): () => void {
  if (window.__trustdesk) return window.__trustdesk.destroy; // idempotent: one widget per page
  // Validate before touching the host page, so a bad key leaves no trace in the DOM.
  const client = createClient({ apiUrl: opts.apiUrl, publicKey: opts.publicKey });
  const host = document.createElement(HOST_TAG);
  host.style.cssText = "all: initial; position: fixed; z-index: 2147483646;";
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = css;
  const container = document.createElement("div");
  shadow.append(style, container);
  const captchaSlot = document.createElement("div");
  captchaSlot.slot = "captcha";
  host.appendChild(captchaSlot);
  document.body.appendChild(host);

  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const theme = opts.theme === "dark" || (opts.theme !== "light" && prefersDark) ? "dark" : "light";
  const { id, firstVisit } = visitor();

  // Apply organization brand colors once config loads (validated hex only).
  void client
    .getConfig()
    .then((cfg) => {
      const t = cfg.theme as { primary?: unknown; accent?: unknown };
      const primary = hexToRgb(t.primary);
      const accent = hexToRgb(t.accent);
      if (primary) host.style.setProperty("--td-primary", primary);
      if (accent) host.style.setProperty("--td-accent", accent);
    })
    .catch(() => undefined);

  const root = createRoot(container);
  root.render(
    <LightDomContext.Provider value={{ captchaSlot }}>
      <App client={client} visitorId={id} firstVisit={firstVisit} theme={theme} />
    </LightDomContext.Provider>,
  );
  const destroy = () => {
    root.unmount();
    host.remove();
    delete window.__trustdesk;
  };
  window.__trustdesk = { version: VERSION, destroy };
  return destroy;
}

function autoInit(): void {
  try {
    const script =
      (document.currentScript as HTMLScriptElement | null) ??
      document.querySelector<HTMLScriptElement>("script[data-tenant][src*='trustdesk']");
    const publicKey = script?.dataset.tenant;
    if (!script || !publicKey) return; // used as a module (tests / React wrapper): no auto-mount
    const apiUrl = script.dataset.api ?? import.meta.env.VITE_TRUSTDESK_API_URL ?? new URL(script.src).origin;
    const theme = (script.dataset.theme as MountOptions["theme"]) ?? "auto";
    const start = () => {
      try {
        mount({ publicKey, apiUrl, theme });
      } catch (err) {
        console.warn("[TrustDesk] widget failed to start:", (err as Error).message);
      }
    };
    if (document.body) start();
    else document.addEventListener("DOMContentLoaded", start, { once: true });
  } catch (err) {
    console.warn("[TrustDesk] widget failed to start:", (err as Error).message);
  }
}

autoInit();
