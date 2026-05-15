# Testing Guide

## Backend tests

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -q
```

The tests cover:

- Arabic intent normalization and classification.
- Routing rules for complaints and handoff.
- Runtime message persistence.
- Provider message idempotency.
- WhatsApp webhook signature validation.
- Broadcast send/schedule behavior.

## Manual smoke test

1. Start backend.
2. Open `/docs`.
3. Login using the academy admin.
4. Authorize with the access token.
5. Test `/auth/me`.
6. Test `/onboarding/readiness` with `X-Tenant-Slug: sarh-almarifah`.
7. Test `/dashboard/preview/inbound` with Arabic customer messages.
8. Test `/broadcasts`, then `/broadcasts/{id}/send`.
9. Test `/health/ready`.
