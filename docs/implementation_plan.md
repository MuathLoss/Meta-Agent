# Clean implementation plan

## Batch 1 foundation
- repo structure
- FastAPI app shell
- PostgreSQL models with tenant ownership
- auth and roles
- tenant resolution with `X-Tenant-Slug`
- encrypted tenant channel config
- onboarding readiness/publish
- runtime preview
- academy seed as Tenant #1 config only

## Batch 2 configuration CRUD
- business settings
- branches/hours
- staff roles
- FAQ manager
- intent keywords
- routing rules
- channel settings

## Batch 3 runtime
- webhook idempotency
- customer/conversation/message persistence
- rule-based intent engine
- response engine
- routing engine
- ticket/handoff state machine

## Batch 4 dashboard
- inbox
- conversation view
- tickets
- customers
- broadcasts
- analytics

## Batch 5 WhatsApp adapter
- tenant-specific verify token
- tenant-specific signature validation
- provider normalization
- outbound adapter boundary

## Batch 6 deployment
- Docker backend
- hosted frontend
- managed Postgres
- staging checklist
- production runbook
