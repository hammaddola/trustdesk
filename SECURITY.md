# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on this repository. Include affected version/commit, impact,
and reproduction steps. Do not include real personal data.

We aim to acknowledge reports within 3 business days and to agree a disclosure timeline with you.

Especially valuable: cross-tenant data access, RLS bypass, SSRF from the crawler, prompt injection that gets
an **unverified** claim shown to a visitor, authentication/session issues, secret leakage.

## Supported versions

Pre-1.0: only the latest release receives security fixes.

## Current status

The project has not had an external security audit. See [docs/security.md](docs/security.md) for the
controls in place and known gaps.
