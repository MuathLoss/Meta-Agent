# Batch 3 summary

Added:

- Onboarding wizard dashboard tab with draft save.
- Runtime classification endpoint that does not create customer data.
- Runtime scenario endpoint that runs the full orchestrator.
- Tenant-scoped WhatsApp adapter boundary.
- Webhook signature validation using the tenant channel app secret.
- Webhook idempotency for provider retries.
- Outbound service that stores locally by default and only sends live when enabled per tenant channel config.
- Out-of-hours policy enforcement using tenant branch hours.

Still pending for later batches:

- Polished full onboarding UX for all nine steps.
- Broadcast scheduling worker.
- Production deployment files and staging runbook hardening.
- End-to-end UAT scenario test suite.
- Real academy WhatsApp hookup after tenant-specific credentials/templates are supplied.
