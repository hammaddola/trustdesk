"""Alembic environment. Migrations run as the schema owner (DIRECT_DATABASE_URL)."""

from alembic import context
from sqlalchemy import create_engine, pool

from trustdesk_ai.db.urls import migration_url

with create_engine(migration_url(), poolclass=pool.NullPool).connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
