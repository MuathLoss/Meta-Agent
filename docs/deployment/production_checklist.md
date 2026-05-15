# Production Checklist

Production should only happen after staging UAT passes.

## Infrastructure

- Hosted backend with public HTTPS.
- Hosted frontend with HTTPS.
- Managed PostgreSQL with backups enabled.
- Secrets stored in platform environment or secret manager, never committed.
- Basic logs and error monitoring enabled.
- `CORS_ALLOWED_ORIGINS` is explicit and does not use `*`.
- Public health/readiness responses do not expose raw database errors,
  hostnames, usernames, or connection strings.

## Platform env only

Allowed platform env values:

- `APP_ENV`
- `APP_SECRET_KEY`
- `DATABASE_URL`
- `CORS_ALLOWED_ORIGINS`
- `FRONTEND_URL`
- `DEFAULT_TIMEZONE`
- `LOG_LEVEL`
- `TENANT_CHANNEL_SECRET_KEY`
- `ALLOW_UNSIGNED_WEBHOOKS_IN_DEV=false`

Do not store one global WhatsApp token, verify token, phone number ID, WABA ID, or app secret in `.env`.
Tenant channel credentials belong in encrypted tenant channel configs, not
global platform environment variables.

## Go-live gates

- `/deployment/checklist` passes except live-send items while credentials are pending.
- Tenant channel config contains the academy WhatsApp package.
- WhatsApp templates are approved.
- Callback URL is registered in Meta.
- Webhook signature validation is enforced in production with the tenant
  app secret stored in encrypted channel credentials.
- Live outbound send is explicitly enabled only after approval.
