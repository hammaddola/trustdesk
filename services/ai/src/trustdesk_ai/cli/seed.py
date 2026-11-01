"""Seed the fictional 'Acme Studio' DEMO organization (development only)."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

import typer
from sqlalchemy import select, text

from trustdesk_ai.auth.passwords import hash_password
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Document, Source, Tenant, TenantMembership, TenantSettings, User
from trustdesk_ai.db.session import global_session, tenant_session
from trustdesk_ai.ingestion.chunker import ChunkConfig
from trustdesk_ai.ingestion.pipeline import index_document
from trustdesk_ai.ingestion.types import Block, BlockKind, ParsedDocument
from trustdesk_ai.providers.registry import embeddings

SEED_DIR = Path(__file__).resolve().parents[5] / "database" / "seed" / "acme-studio"
DEMO_EMAIL = "demo-owner@acme-studio.example"
DEMO_NAME = "Acme Studio (DEMO)"
TAGS = {"pricing.md": ["pricing"], "faq.md": ["faq"]}


def parse_markdown(source: str) -> ParsedDocument:
    """Minimal Markdown -> blocks for seed files (headings, paragraphs, '-' lists, pipe tables)."""
    blocks: list[Block] = []
    title = None
    for chunk in re.split(r"\n\s*\n", source.strip()):
        lines = chunk.strip().splitlines()
        if not lines:
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)", lines[0]):
            level, heading = len(m.group(1)), m.group(2).strip()
            title = title or heading
            blocks.append(Block("heading", heading, level=level))
            lines = lines[1:]
            if not lines:
                continue
        body = "\n".join(lines)
        kind: BlockKind = "table" if lines[0].startswith("|") else "list" if lines[0].startswith("- ") else "paragraph"
        blocks.append(Block(kind, body if kind != "paragraph" else " ".join(lines)))
    return ParsedDocument(blocks=blocks, title=title, language="en")


async def seed() -> None:
    settings = get_settings()
    if settings.is_production:
        typer.echo("Refusing to seed demo data in production.", err=True)
        raise typer.Exit(2)
    password = secrets.token_urlsafe(12)
    async with global_session() as db:
        existing = (await db.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
        if existing is not None:
            typer.echo(f"Demo organization already exists (sign in as {DEMO_EMAIL}).")
            return
        user = User(email=DEMO_EMAIL, password_hash=hash_password(password), display_name="Demo owner")
        db.add(user)
        await db.flush()
        user_id = user.id
        key = "td_pk_demo_" + secrets.token_urlsafe(12)
        tenant_id = (
            await db.execute(
                text("SELECT create_tenant(:s, :n, :k, true)"),
                {"s": "acme-demo-" + secrets.token_hex(3), "n": DEMO_NAME, "k": key},
            )
        ).scalar_one()

    embedder = embeddings()
    async with tenant_session(tenant_id) as db:
        db.add(TenantMembership(tenant_id=tenant_id, user_id=user_id, role="owner"))
        db.add(
            TenantSettings(
                tenant_id=tenant_id,
                organization_name=DEMO_NAME,
                description="Fictional web design studio used for TrustDesk demos.",
                website_urls=["https://acme-studio.example"],
                allowed_domains=["acme-studio.example"],
                allowed_origins=["http://localhost:5173", "http://localhost:3000"],
                greeting="Hi! Ask me about Acme Studio's services, pricing or process. (Demo data)",
                handoff_channels={
                    "email": {"enabled": True, "to": DEMO_EMAIL},
                    "booking": {"enabled": False},
                    "whatsapp": {"enabled": False},
                },
            )
        )
        await db.flush()
        for path in sorted(SEED_DIR.glob("*.md")):
            if path.name == "README.md":
                continue
            tags = TAGS.get(path.name, [])
            source = Source(tenant_id=tenant_id, kind="upload", tags=tags)
            db.add(source)
            await db.flush()
            doc = Document(
                tenant_id=tenant_id,
                source_id=source.id,
                source_type="web_page",
                title=path.stem.title(),
                canonical_url=f"https://acme-studio.example/{path.stem}",
                tags=tags,
            )
            db.add(doc)
            await db.flush()
            await index_document(
                db,
                document=doc,
                parsed=parse_markdown(path.read_text(encoding="utf-8")),
                embedder=embedder,
                chunk_config=ChunkConfig(),
                source_url=doc.canonical_url,
            )
        await db.execute(
            text("UPDATE tenant_settings SET setup_completed_at = now() WHERE tenant_id = :t"), {"t": tenant_id}
        )
        tenant = await db.get(Tenant, tenant_id)
        public_key = tenant.public_key if tenant else key
    typer.echo(
        f"Seeded {DEMO_NAME}.\n  Admin sign-in: {DEMO_EMAIL}\n  Password: {password}  (shown once)\n"
        f"  Widget key: {public_key}"
    )
