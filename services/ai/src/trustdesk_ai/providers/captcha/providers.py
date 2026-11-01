"""Captcha verification adapters: none, Cloudflare Turnstile, hCaptcha (server-side token validation)."""

from __future__ import annotations

import logging

import httpx

from trustdesk_ai.config.settings import Settings
from trustdesk_ai.providers.base import CaptchaProvider

log = logging.getLogger(__name__)


class NoCaptcha:
    name = "none"

    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        return True


class SiteVerifyCaptcha:
    """Turnstile and hCaptcha share the same siteverify contract (form POST, JSON {success: bool})."""

    def __init__(self, name: str, url: str, secret: str) -> None:
        self.name, self._url, self._secret = name, url, secret

    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        if not token or len(token) > 4096:
            return False
        data = {"secret": self._secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.post(self._url, data=data)
            return resp.status_code == 200 and resp.json().get("success") is True
        except (httpx.HTTPError, ValueError):
            log.warning("%s verification unavailable; rejecting submission", self.name)
            return False  # fail closed


def build_captcha(s: Settings) -> CaptchaProvider:
    if s.captcha_provider == "turnstile" and s.turnstile_secret_key:
        return SiteVerifyCaptcha(
            "turnstile",
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            s.turnstile_secret_key.get_secret_value(),
        )
    if s.captcha_provider == "hcaptcha" and s.hcaptcha_secret_key:
        return SiteVerifyCaptcha(
            "hcaptcha", "https://api.hcaptcha.com/siteverify", s.hcaptcha_secret_key.get_secret_value()
        )
    return NoCaptcha()
