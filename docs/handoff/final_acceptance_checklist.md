# Final Acceptance Checklist

## Platform foundation

- Tenant model exists.
- User authentication works.
- Tenant roles work.
- `X-Tenant-Slug` tenant resolution works.
- Tenant-owned data stays tenant-scoped.

## Tenant configuration

- Business settings can be edited.
- Branches and hours can be stored.
- Staff and roles can be managed.
- FAQ content can be edited without code.
- Intents, keywords, and routing are tenant-owned.
- Channel credentials are stored through `channel_configs`.

## Runtime engine

- Intent engine is rule-first and tenant-scoped.
- Response engine uses approved tenant FAQ content.
- Routing engine uses tenant routing rules.
- Complaints create high-priority tickets.
- Explicit human requests hand off.
- Human handoff stops bot auto-replies.
- Webhook retries are deduplicated by provider IDs.

## Dashboard

- Overview works.
- Onboarding works.
- Inbox and conversation view work.
- Tickets, customers, broadcasts, audit, UAT, deployment, and handoff tabs work.

## Deployment

- `/health` works.
- `/health/ready` works.
- Environment variables are documented.
- Staging is required before production.
- Secrets are not committed.

## Live academy WhatsApp hookup

This remains blocked until the client supplies the tenant-specific WhatsApp package:

- Business phone number
- WABA ID
- PHONE_NUMBER_ID
- Production access token
- App secret
- Verify token
- Approved template names/languages
- Public HTTPS callback URL
