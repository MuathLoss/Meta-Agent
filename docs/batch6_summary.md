# Batch 6 Summary

Batch 6 focuses on staging/production readiness and WhatsApp UAT preparation while keeping the product direction strict: platform-level secrets stay in `.env`, and business/channel credentials stay tenant-scoped in `channel_configs`.

## Added

- Deployment readiness API under `/deployment/*`.
- Secret-safe environment status endpoint.
- Tenant WhatsApp go-live package checklist endpoint.
- WhatsApp webhook UAT fixtures under `/uat/whatsapp-fixtures`.
- Fixture simulation endpoint that normalizes and classifies realistic WhatsApp payloads without creating customer messages.
- New frontend **Deployment** tab.
- Staging checklist, production checklist, and WhatsApp go-live runbook docs.

## Important rule

Do not move WhatsApp token, verify token, app secret, phone number ID, or WABA ID into global `.env`. They belong in tenant-scoped channel settings.
