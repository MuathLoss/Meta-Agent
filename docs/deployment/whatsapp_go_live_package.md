# WhatsApp Go-Live Package

The platform build does not wait on this package. The academy cannot go live on WhatsApp until the package is supplied and stored under the academy tenant's WhatsApp channel settings.

## Required tenant-specific items

- Final WhatsApp Business phone number.
- WABA ID.
- PHONE_NUMBER_ID.
- Production access token.
- App secret.
- Verify token.
- Approved template names and languages.
- Public HTTPS webhook callback URL.

## Storage rule

These are business-specific credentials. Store them in `channel_configs` for the academy tenant only, encrypted at rest. Do not store them as one global WhatsApp config in `.env`.

## Current safe behavior

The platform can normalize webhook payloads, validate signatures when app secret exists, deduplicate provider retries, and store outbound replies locally. Live sending remains disabled unless `live_send_enabled` is explicitly set in the tenant channel public config.
