# Staging Checklist

Staging is mandatory before production go-live.

## Backend

- `/health` returns `ok`.
- `/health/ready` returns `ready`.
- `APP_ENV=staging`.
- Real staging `DATABASE_URL` points to managed or staging Postgres.
- CORS allows only the staging frontend URL.
- `TENANT_CHANNEL_SECRET_KEY` is a real Fernet key and is backed up securely.

## Frontend

- `VITE_API_BASE_URL` points to the staging backend.
- Login works for the academy tenant.
- Onboarding readiness loads.
- UAT tests pass.
- Deployment tab loads.

## Tenant/channel

- Academy exists as Tenant #1.
- WhatsApp channel settings are tenant-scoped.
- Live send remains disabled until approved credentials/templates are supplied.
- Webhook fixture simulation works.

## Runtime

- Pricing, registration, location, accreditation, women section, kids section, complaint, human request, payment, and certificate scenarios pass UAT.
- Webhook retry/idempotency tests pass.
- Complaints create high-priority tickets and stop bot auto-replies.
