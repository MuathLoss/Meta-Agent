# Remaining launch blockers

Live list (spec v1.2, Sections 17–18). Update it whenever something changes. Last updated 2026-11-13.

## Owner / external (not coding tasks)

| Blocker | Blocks | Status |
|---|---|---|
| Ownership of the handed-over Agent SW code | Any sale | Settled: the owner confirmed on 2026-11-13 that the original author transferred it to him in full. Keep a short written note of that transfer on file |
| Meta billing arrangement for included WhatsApp usage, or verified free-tier sizing (spec 3.1 a–b) | Live WhatsApp | Open |
| Whether a WhatsApp Business account needs a payment method on file for free-tier messages | Live WhatsApp | Open |
| Meta app, business verification, WABA assets | Live WhatsApp | Open |
| Payment gateway choice and merchant account | Paid launch | Open |
| Price, currency, tax, included allowances | Paid launch | Open |
| Domain, DNS, email sender, VPS purchase | Internet pilot | Open (see `docs/vps-sizing.md`) |
| Server country and data-location wording; privacy policy, terms, data-processing terms | Real institution data | Open |
| Live staff replies vs ticket-only (spec P08) | Product behavior | Open; default ticket-only |
| Commit the outstanding Agent SW work | Clean history | Done 2026-11-13 on branch `institution-chatbot`, all under the owner's name |
| Repository visibility and licence (GitHub `MuathLoss/Meta-Agent` is public with an MIT licence) | Selling the product | Open: owner decision |

## Engineering (by phase)

| Item | Phase | Status |
|---|---|---|
| pgvector, Redis + worker, private storage, production compose, CI | 0 | Done 2026-11-13 |
| Off-server encrypted backups + tested restore of database **and** storage | 0/7 | Open; staging-only backup exists |
| HTTP-only cookie sessions + CSRF, Argon2id, email verification | 1 | Open |
| PostgreSQL RLS with a non-owner app role (see `docs/decisions.md`) | 1 | Open |
| Gemini model access check; 768 vs 1536 evaluation | 2 | Open |
| Document ingestion, RAG answers, evaluation set (Arabic/English) | 2 | Open |
| Widget publishing gates, domain allowlist, signed sessions | 3 | Open |
| Billing adapter, entitlements, usage ledger | 5 | Open |
| WhatsApp 24-hour window, quota reservation, idempotency | 6 | Open |
| Monitoring and alerts (disk, memory, queue, errors) | 7 | Open |
