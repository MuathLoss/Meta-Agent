# Client Handoff Package

## Product delivered

Configurable multi-tenant business agent platform.

The academy is Tenant #1. WhatsApp is Channel #1. The platform core remains channel-agnostic and can later support email, Instagram, Facebook messaging, and web chat through adapters.

## What is included

- FastAPI backend
- React + TypeScript dashboard
- PostgreSQL data model
- Tenant-scoped authentication and roles
- Self-serve onboarding and publish flow
- Tenant-scoped FAQ, intents, keywords, routing, branches, staff, channel configs
- Conversations, messages, customers, tickets, broadcasts, webhook events, audit logs
- Rule-first intent engine
- Response engine
- Routing engine
- Orchestrator and state machine
- WhatsApp adapter boundary
- Idempotency model
- UAT and deployment dashboard tabs
- Final handoff dashboard tab

## What is intentionally not included yet

The real academy WhatsApp production connection is not enabled because the tenant-specific WhatsApp package has not been supplied. Live outbound sending must stay disabled until credentials and templates are approved.

## Recommended next step

Deploy to staging, run UAT, then connect the academy WhatsApp tenant configuration only after the official credential/template package is supplied.
