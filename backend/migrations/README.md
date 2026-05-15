# Alembic Migration Safety

This project now has an Alembic baseline for the current SQLAlchemy model schema.

## Fresh Database

For a brand-new empty database, run from `backend/`:

```bash
alembic upgrade head
```

This applies the baseline migration and creates the schema from scratch.

## Existing Database

Do not run the baseline upgrade against an existing populated database. The
baseline migration contains `create_table` operations for tables that already
exist, so applying it directly to the current database would fail and is not the
safe path for adoption.

After confirming the live schema matches the baseline closely enough, mark the
existing database as being at the baseline revision:

```bash
alembic stamp head
```

Stamping only records the migration version; it does not create, drop, rename,
truncate, or alter application tables.

## Check Migration State

From `backend/`:

```bash
alembic current
alembic heads
alembic history
```

`alembic current` checks the database's recorded revision. `alembic heads`
checks the latest available migration in code.

## Known Follow-Up Migration Patches

Do not include these in the baseline setup patch:

- Tenant-aware/composite foreign keys for tenant-owned child rows.
- Index additions for hot tenant-scoped queries.
- Nullability drift cleanup for legacy columns.
- Webhook uniqueness redesign at the database level.
