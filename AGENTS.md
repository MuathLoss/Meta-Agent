# Repository Agent Instructions

## Project identity

This is a configurable multi-tenant business agent platform.

It is not a simple academy chatbot. It is a SaaS-style platform where each business/tenant has its own workspace, onboarding flow, configuration, staff, FAQ, routing, channel settings, customer inbox, tickets, analytics, and runtime agent behavior.

Tenant isolation is critical. Do not weaken tenant scoping, authentication, channel configuration, routing logic, database safety, or security behavior.

## Main stack

- Frontend: React + TypeScript + Vite
- Backend: FastAPI + PostgreSQL + SQLAlchemy + Alembic

## Validation

- Frontend-only change: run `npm run build`
- Backend touched: run relevant backend tests, usually `python -m pytest -q`

## Working rules

- Make the smallest safe change that solves the requested problem.
- Do not redesign the whole app unless explicitly asked.
- Do not touch backend, database, migrations, auth, tenant logic, API payloads, or routes during frontend UI-only work.
- Preserve existing functionality.
- Preserve existing API calls and response shapes.
- Avoid unnecessary dependencies.
- Avoid broad refactors.
- Prefer improving one UI area per run.
- After edits, run the smallest relevant validation command.

## Frontend design direction

The product should feel like a premium SaaS admin dashboard.

Target mood:
- enterprise
- polished
- mature
- dark maroon / charcoal / black
- clean spacing
- clear hierarchy
- professional business software

Avoid:
- generic AI gradients
- random glowing blobs
- childish glassmorphism
- excessive shadows
- oversized cards with no information hierarchy
- decorative animations that slow the app
- landing page design inside admin screens

## Done means

A change is done only when:
- the requested UI area looks more professional
- spacing and alignment are cleaner
- hierarchy is clearer
- empty/loading/error states are handled if relevant
- responsive behavior is not broken
- existing behavior still works
- validation command passes
