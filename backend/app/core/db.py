from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

# Row-level security context (spec v1.2, Section 8). PostgreSQL policies only show a tenant's
# rows when the transaction says which tenant it works for, or that it is trusted system work
# (sign-in, webhooks, the worker). Settings are transaction-local, so a pooled connection
# never carries one request's tenant into another, and they are re-applied after each commit.
RLS_TENANT_KEY = "rls_tenant_id"


def _apply(connection, tenant_id: int | None) -> None:
    if connection.dialect.name != "postgresql":
        return
    if tenant_id is None:
        connection.execute(text("SELECT set_config('app.rls_scope', 'system', true), set_config('app.tenant_id', '', true)"))
    else:
        connection.execute(
            text("SELECT set_config('app.rls_scope', 'tenant', true), set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(int(tenant_id))},
        )


@event.listens_for(Session, "after_begin")
def _apply_rls_context(session: Session, transaction, connection) -> None:
    _apply(connection, session.info.get(RLS_TENANT_KEY))


def bind_tenant(db: Session, tenant_id: int) -> None:
    """From now on this session only sees and writes this tenant's rows."""
    db.info[RLS_TENANT_KEY] = int(tenant_id)
    if db.in_transaction():
        _apply(db.connection(), tenant_id)


@contextmanager
def system_scope(db: Session) -> Iterator[None]:
    """Briefly look across tenants inside a tenant request, e.g. to report a duplicate id."""
    previous = db.info.pop(RLS_TENANT_KEY, None)
    _apply(db.connection(), None)
    try:
        yield
    finally:
        if previous is not None:
            db.info[RLS_TENANT_KEY] = previous
            if db.in_transaction():
                _apply(db.connection(), previous)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
