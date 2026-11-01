import { forwardRef, useContext, useEffect, useImperativeHandle, useRef } from "react";

import { LightDomContext } from "../lib/lightDom";

export interface CaptchaHandle {
  token(): string | null;
  reset(): void;
}

type Provider = "turnstile" | "hcaptcha";

interface CaptchaApi {
  render(el: HTMLElement, opts: Record<string, unknown>): string;
  reset(id?: string): void;
}

const SCRIPTS: Record<Provider, { src: string; global: "turnstile" | "hcaptcha" }> = {
  turnstile: { src: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", global: "turnstile" },
  hcaptcha: { src: "https://js.hcaptcha.com/1/api.js?render=explicit", global: "hcaptcha" },
};

function loadScript(provider: Provider): Promise<CaptchaApi> {
  const { src, global } = SCRIPTS[provider];
  const existing = (window as unknown as Record<string, CaptchaApi | undefined>)[global];
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.onload = () => {
      const api = (window as unknown as Record<string, CaptchaApi | undefined>)[global];
      if (api) resolve(api);
      else reject(new Error("captcha failed to load"));
    };
    s.onerror = () => reject(new Error("captcha failed to load"));
    document.head.appendChild(s);
  });
}

/**
 * Captcha providers render iframes that do not work reliably inside a shadow root, so the widget renders
 * them into a light-DOM element (a child of the widget host) that is projected into the panel via <slot>.
 */
export const Captcha = forwardRef<CaptchaHandle, { provider: Provider; siteKey: string }>(function Captcha(
  { provider, siteKey },
  ref,
) {
  const lightDom = useContext(LightDomContext);
  const token = useRef<string | null>(null);
  const widgetId = useRef<string | null>(null);
  const api = useRef<CaptchaApi | null>(null);

  useImperativeHandle(ref, () => ({
    token: () => token.current,
    reset: () => {
      token.current = null;
      if (api.current && widgetId.current) api.current.reset(widgetId.current);
    },
  }));

  useEffect(() => {
    if (!lightDom) return;
    const target = document.createElement("div");
    lightDom.captchaSlot.replaceChildren(target);
    let cancelled = false;
    loadScript(provider)
      .then((loaded) => {
        if (cancelled) return;
        api.current = loaded;
        widgetId.current = loaded.render(target, {
          sitekey: siteKey,
          callback: (t: string) => (token.current = t),
          "expired-callback": () => (token.current = null),
        });
      })
      .catch(() => undefined); // server rejects submissions without a valid token
    return () => {
      cancelled = true;
      lightDom.captchaSlot.replaceChildren();
    };
  }, [lightDom, provider, siteKey]);

  return <slot name="captcha" />;
});
