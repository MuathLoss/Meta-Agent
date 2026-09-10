# Agent SW — Project Overview and Developer Handoff

**Updated:** September 10, 2026  
**Owner:** Fouad  
**Current project folder:** `/Users/fouad/Desktop/projects/agent SW/agent_SW_final`  
**Status:** Working local development and local staging environments. Further usability testing and real provider validation are needed before a pilot.

This document explains the project and its current handoff point. It contains no account passwords, provider tokens, or customer records. File paths below are relative to the project folder unless stated otherwise.

## 1. What the project is

Agent SW is a configurable customer-service platform for multiple businesses. Each business has a separate workspace containing its own profile, opening hours, team, approved answers, messaging channels, customers, conversations, and handoff rules.

The goal is to let a business administrator set up an agent without needing to understand the underlying technical configuration. The agent should answer questions using that business's approved information, ask for clarification when needed, and pass appropriate conversations to a person.

An academy was the original example business. Its content is configuration for one workspace; future development should keep the platform useful for other businesses.

Typical customer flow:

```text
Customer message
    → identify the channel and business workspace
    → normalize the message and check for duplicate delivery
    → classify the question using rules and, optionally, local AI
    → apply that workspace's working hours and routing rules
    → send an approved answer, clarify, or hand over to the team
    → record the conversation and any resulting ticket
```

Typical administrator flow:

```text
Create workspace → add business details → add approved answers
→ connect a channel → try virtual replies → review readiness
→ publish workspace → validate actual message delivery before a pilot
```

Publishing a workspace, verifying credentials, and enabling live replies are separate actions. A successful virtual test does not prove a real provider can deliver messages.

## 2. The latest request and where work stopped

Fouad asked to resume development, repair startup, finish channel setup and staging preparation, extend Smart Import, separate internal tools from customer screens, and overhaul the UI so setup is smoother and easier to understand.

**Hosting decision:** Prepare staging locally first; choose a hosting provider and domain later. No public deployment was performed in this upgrade.

The September implementation is saved in the Desktop project folder. Work stopped after implementation, automated checks, local staging validation, database backup/migration, and local startup verification. Desktop/mobile browser review and real-provider delivery testing remain unfinished.

### Git handoff — do not miss the new files

At this handoff, the branch is `master` and the last committed change is:

```text
93cc35b — Improve smart import correction workflow — May 22, 2026
```

**The September upgrades are saved but are not committed.** They include both modified files and new, untracked files. A clone of only the last committed repository will not contain all the current work.

Before continuing, inspect `git status`, preserve the current working tree, and coordinate a commit/branch with Fouad. This Markdown file provides context; the next developer also needs the current source files.

For a clean development handoff, share source and lockfiles. Recreate `.venv`, `node_modules`, and generated builds on the receiving machine. Existing `.env` files, database dumps, `.local-backups`, `.staging-backups`, and uploads can contain secrets or business data; arrange any necessary transfer separately rather than including them in an ordinary source archive.

## 3. What is already implemented

### Business platform and daily operations

- Business signup/login, workspace membership, and roles.
- Business profile, branding, locations, opening hours, and staff configuration.
- Approved answers in Arabic/English, question topics, keywords, and routing rules.
- Customer inbox, conversation details, tickets, customers, and activity summaries.
- Staff handoff and conversation management.
- Broadcast management and recipient tracking; live behavior still needs provider-specific validation.
- Audit records, tenant-scoped configuration, encrypted channel credentials, webhook checks, and duplicate-message handling.
- Optional Ollama classification fallback. The core can operate without local AI.

These are existing capabilities, not a claim that every screen and live-provider scenario has passed final acceptance testing.

### September startup repairs

- `setup_local.sh` refreshes the Python environment paths and installs declared backend/frontend dependencies.
- Startup uses the environment's Python directly, avoiding the old folder path embedded in activation scripts and command launchers.
- XLSX import support is installed through the existing `openpyxl` requirement.
- `scripts/local_runner.py` coordinates startup, checks dependencies and health, detects occupied ports, and tracks the processes it starts.
- `start_all.sh` and `stop_all.sh` wrap the runner. The final stop/start checks passed after a shutdown coordination fix.
- Startup does not seed, reset, or automatically migrate a database.
- Telegram failures are isolated per account. Rejected credentials have a retry delay, and changed credentials can be retried. Existing webhooks are preserved.

### UI/UX changes

- Redesigned sign-in and workspace creation screens.
- Simplified navigation based on the user's role.
- New overview with actual activity and a next setup action.
- A setup guide covering business details, knowledge, channels, and a virtual test before publication.
- Setup progress is derived from saved configuration.
- A rewritten channel screen with provider-specific fields, required-field checks, connection verification, and virtual replies.
- Clearer knowledge wording and fewer internal identifiers in customer-facing screens.
- Advanced provider settings and live-reply controls are expandable.
- Charcoal/maroon styling, responsive rules, more readable controls, and less decorative visual clutter.
- Saved-review controls, unsaved-review close protection, and keyboard focus handling in the import dialog.

**Unfinished:** the refreshed interface still needs hands-on desktop/mobile, keyboard, Arabic/RTL, and usability review. The automated browser tool was blocked by an enforced-policy verification failure, so visual testing was not marked as passed.

### Smart Import beyond Phase 1

Users can paste messages or upload TXT, CSV, or XLSX, inspect suggestions, correct them, and approve selected content.

September additions:

- Encrypted, redacted review drafts that can be saved and reopened.
- Revision checks to prevent one editing session overwriting a newer saved review.
- Import history and read-only views of completed imports.
- Retry-safe approval for a saved import job, avoiding double application of the same job.
- Duplicate handling that preserves existing content.
- Batch undo that removes items added by the import and restores its routing changes.
- Undo refuses the entire operation if tracked content was subsequently edited/removed or relevant new content is used outside the import.
- An explicit option to save a reviewed handoff choice. Previously, these choices were only shown during review.
- Protected topics retain immediate handoff: complaints, requests for a human, payment transfers, and certificates.
- Optional local AI grouping, with deterministic topic grouping when AI is unavailable or disabled. Grouping does not approve rows, invent answers, or apply routing changes.

Current boundaries:

| Area | Current behavior |
| --- | --- |
| Review/upload limit | Up to 500 messages and 2 MB, subject to validation |
| AI grouping | Up to 80 messages per review |
| Saved history list | Most recent 100 jobs; no pagination yet |
| Saving a review | Explicit save; do not assume continuous autosave |
| New topics created through import | Created disabled for later review |
| Existing answers | Preserved rather than silently overwritten |
| Undo | Guarded batch operation, not a general version-control system |
| Raw upload files | Not retained by Smart Import; saved review content is redacted and encrypted |

Redaction is a processing safeguard, not a guarantee that every possible identifying detail is removed. Saved reviews and database backups should still be handled as business data.

### Channel setup

| Channel | Code and setup available | Remaining validation |
| --- | --- | --- |
| Telegram | Adapter, local polling, encrypted token storage, read-only token verification | Repair rejected/missing credentials and test actual inbound/replies |
| WhatsApp | Adapter, webhooks, signature checks, outbound integration, account routing, configurable Graph API version | Real business account, permissions/templates where applicable, public HTTPS callback, actual delivery |
| Email | SMTP outbound, IMAP inbound polling, credential checks | Real test mailbox, provider settings, enabled worker, actual receive/reply behavior |
| Instagram | Meta messaging integration, webhook handling, settings and account checks | App/account permissions, HTTPS webhook subscription, actual delivery |
| Messenger | Meta messaging integration, webhook handling, settings and account checks | Page/app permissions, HTTPS webhook subscription, actual delivery |
| Web chat | First-party message endpoint and virtual testing | A finished embeddable customer widget and website integration |

Changing one saved credential now preserves the other credentials. Required-field status and a provider verification result are displayed separately. Live customer replies remain an explicit setting.

During the September read-only checks, one saved Telegram account was accepted, one token was rejected, and one configuration lacked required details. Those were point-in-time results, not continuing monitoring. No customer messages were sent as part of those checks.

### Internal tools and local staging

- Deployment, UAT, and handoff endpoints now require a platform administrator, and their menu is hidden from ordinary business users.
- Platform support access requires an audit reason. API support access uses `X-Support-Access-Reason` in addition to the authenticated workspace context.
- `docker-compose.staging.yml` provides separate PostgreSQL storage, backend, migrations, and an Nginx-served frontend.
- Staging waits for database health, completes migrations, and checks backend readiness before bringing up the frontend.
- Container health checks and rotating logs are configured.
- Backup and disposable-database restore verification commands exist.
- An HTTPS proxy example exists for later hosting. It is not a deployed HTTPS setup.

## 4. Architecture and where to look

**Stack:** React + TypeScript + Vite; FastAPI + SQLAlchemy + Alembic + PostgreSQL; optional Ollama. The staging images use Node 22, Python 3.12, and PostgreSQL 16. The current startup scripts are written for a Unix-like environment; Windows operation has not been verified.

| Location | Purpose |
| --- | --- |
| `frontend/src/App.tsx` | Session handling and platform-support entry |
| `frontend/src/pages/Dashboard.tsx` | Main navigation and remaining operational/configuration screens; still a large file |
| `frontend/src/pages/LoginPage.tsx` | Sign-in and workspace creation |
| `frontend/src/pages/WorkspaceGuide.tsx` | Overview and setup guide |
| `frontend/src/pages/ChannelsPage.tsx` | Guided channel settings, verification, virtual replies |
| `frontend/src/pages/SmartImportStudio.tsx` | Import review, saved drafts, history, grouping, undo |
| `frontend/src/services/api.ts` | Frontend API calls and shared response types |
| `frontend/src/workspace.css` | September UI styling; older styles remain in `styles.css` |
| `backend/main.py` | API startup, middleware, health checks, router registration |
| `backend/app/core/tenancy.py` | Workspace roles, access checks, platform-support access |
| `backend/app/core/config.py` | Settings actually read by the current application |
| `backend/app/models/entities.py` | Database models, including `ImportJob` |
| `backend/app/api/routes_imports.py` | Preview, saved review, approval, grouping, and undo endpoints |
| `backend/app/services/smart_import_service.py` | Import parsing, redaction, and suggestions |
| `backend/app/services/import_job_service.py` | Encrypted drafts, change tracking, guarded undo |
| `backend/app/services/import_grouping_service.py` | Optional AI grouping and fallback |
| `backend/app/services/orchestrator.py` | Main customer-message workflow |
| `backend/app/services/intent_rules.py`, `routing_engine.py`, `response_engine.py` | Classification, handoff decisions, approved responses |
| `backend/app/services/tenant_channel_service.py`, `channel_health_service.py` | Credential storage/update behavior and connection checks |
| `backend/app/api/routes_webhook.py` | Provider inbound routes |
| `backend/app/services/outbound_service.py` | Provider reply dispatch |
| `backend/migrations/versions/` | Versioned database changes |
| `backend/tests/` | Backend regression tests |
| `scripts/` | Local startup, upgrade/backup, staging, and smoke checks |

Workspace context typically uses a bearer access token and `X-Tenant-Slug`. Authorization must also check workspace membership/roles; the header alone is not permission to access a business's data.

## 5. Starting on another machine

### Option A — isolated local staging

This is the most self-contained way to inspect the application with a fresh test workspace. Install Docker with Compose and Python 3, then run from the project root:

```bash
bash scripts/staging.sh init
bash scripts/staging.sh start
bash scripts/staging.sh check
```

Open `http://127.0.0.1:8088` and create a workspace through the signup screen.

`init` creates random local staging secrets in `.env.staging` and will not overwrite an existing file. The staging database is separate from Fouad's development database. Backend schema migrations run automatically in this staging flow; demo seeding is not needed.

Provider workers and local AI are off by default in this Compose configuration. Email and Ollama settings are explicitly overridden there, so changing only an unrelated development `.env` will not enable them in staging.

Useful commands:

```bash
bash scripts/staging.sh status
bash scripts/staging.sh logs
bash scripts/staging.sh backup
bash scripts/staging.sh restore-check .staging-backups/database-TIMESTAMP.dump
bash scripts/staging.sh stop
```

Replace the example archive path with the backup command's actual output. The restore check uses a disposable database and does not replace staging's data. Avoid removing Docker volumes if you need to preserve that environment.

### Option B — edit and run the development app

Use Python 3.12, Node/npm compatible with the frontend, and a running PostgreSQL database.

From the project root:

```bash
bash setup_local.sh
```

For a new environment, create `backend/.env` from `backend/.env.example`, configure your own local database and development secrets, and check `backend/app/core/config.py` for the active settings. Never replace the encryption key for an existing encrypted database without a deliberate migration plan.

For a **brand-new empty database only**, initialize it through Alembic:

```bash
cd backend
.venv/bin/python -m alembic upgrade head
cd ..
```

Then run the UI and backend with background provider polling off:

```bash
EMAIL_POLLING_ENABLED=false bash start_all.sh --without-telegram
```

- Interface: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- API reference: `http://127.0.0.1:8000/docs`
- Stop: `bash stop_all.sh`

Create a test workspace using signup. Keep real provider accounts out of routine UI testing. The start script checks database availability but does not start a native PostgreSQL installation for you.

Running `bash start_all.sh` without the Telegram flag starts its polling worker. Enable it deliberately after configuring a bot you control. The runner does not delete an existing webhook to force polling.

### Existing database and migration state

Fouad's database was upgraded from `20260515_0006` to `20260910_0007`. The September migration adds the `import_jobs` table. A private database/configuration/upload backup was created first; existing table row counts were unchanged afterward.

For a copy still at the previous known revision, the helper is:

```bash
backend/.venv/bin/python scripts/upgrade_local.py --apply
```

It backs up before migrating and accepts the known previous revision or an already-upgraded database. It requires PostgreSQL client backup tools. Investigate any other starting revision before applying changes.

Do not blindly follow the older migration note suggesting `alembic stamp head` on a populated database: stamping records a version without applying the new table. Do not use the old README's seed/init sequence as an upgrade procedure. Academy seeding is for intentional local demo setup, not staging or production.

## 6. Validation already recorded

These results were obtained during the September upgrade, not rerun solely to create this handoff:

- The recorded full backend suite passed **223 tests**. Subsequent focused tests, including an additional provider-isolation case, also passed.
- TypeScript checking and the frontend production build passed.
- Local PostgreSQL staging built, migrated, and reached healthy UI/API endpoints.
- API flow checks passed for signup, setup, channel save/verification, virtual replies, import preview, encrypted review/resume, grouping, approval/retry, undo, and denial of internal-tool access to a customer administrator.
- Staging backup restoration succeeded in a disposable database.
- The original project's environment repair, database upgrade, and final local start/stop checks passed.
- The production frontend dependency audit reported zero known vulnerabilities at that time. This does not certify all development or backend dependencies.

Not verified: complete desktop/mobile visual acceptance, live AI grouping quality with a running model, real-provider end-to-end delivery, hosted HTTPS, off-device backup scheduling, or external alerts.

To rerun development checks:

```bash
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm run build
```

Run backend tests with the development configuration available; the test fixtures use isolated databases. Review `backend/tests/conftest.py` before adapting the test environment. Do not aim new destructive integration tests at the owner's database.

## 7. What remains — recommended order

### 1. Review the UI with an actual user

Complete desktop/mobile and keyboard review first. Walk a new user through signup, setup, knowledge creation, import review, channel connection, testing, and publication without coaching.

Check navigation, focus, modal scrolling, long Arabic/English text, RTL presentation, narrow screens, error messages, loading states, unsaved changes, and permission-specific screens. Refine brand identity and consistency across the older inbox, tickets, settings, staff, and broadcast screens. The September changes establish a direction; they are not a finished visual sign-off.

### 2. Make one real channel work end to end

Start with an account Fouad controls. For Telegram, replace the rejected token through Channels and resolve the incomplete configuration if that workspace will use Telegram. Check credentials, then prove inbound receipt and an actual reply. A valid token by itself is not enough.

Also test a team handoff, provider failure, duplicate webhook/update, and disabled live replies. Do not run competing polling workers for a bot or silently remove an existing webhook. Repeat the delivery checks for each channel intended for the pilot.

### 3. Finish operational staging before a pilot

Hosting and domain selection are still pending by choice. After they are chosen, configure HTTPS, explicit frontend/CORS origins, provider webhooks and permissions, protected persistent storage, scheduled off-device backups, retention, restore drills, and external failure alerts.

Current backups are manual. Health checks and local logs exist, but nobody is automatically notified through an external monitoring service. Test upload recovery as well as database recovery, and securely retain the encryption key.

Use the existing production/staging checklists as input, updating their academy-only and old UI references as needed. Internal UAT/deployment pages now require a platform administrator.

### 4. Finish Smart Import acceptance and usability

Test real, appropriately redacted Arabic/English exports; large reviews; duplicate handling; saving and reopening; two sessions editing the same review; approval retries; and undo after later manual edits.

Exercise Ollama grouping with a running local model before describing its grouping quality as validated. Check its unavailable/invalid-output fallback. Decide whether history pagination/search, automatic draft saving, and clearer conflict recovery are needed next; they are follow-up ideas, not completed features.

### 5. Review remaining engineering debt

- Break up the large `Dashboard.tsx` gradually without losing existing behavior.
- Reconcile old and new styles after visual review.
- Update outdated README/setup/migration instructions and old absolute folder links.
- Review frontend `latest` version ranges and dependency audits before a release; preserve the lockfile when reproducing this handoff.
- Assess the documented database follow-ups: tenant-composite foreign keys, hot-query indexes, legacy nullability, and provider-event uniqueness. These require deliberate migrations, not a database reset.
- Review read endpoints that still create missing default routing rules, such as `GET /routing-rules`, so their behavior is intentional.
- Build the embeddable web-chat widget if website chat is in the pilot scope.

## 8. Behaviors to preserve while continuing

- Every business owns its own knowledge, channel credentials, customers, and conversations.
- Approved business information is the source of answers; AI suggestions do not become business facts automatically.
- Important human-handoff protections must survive import and UI changes.
- Virtual channel tests must not populate the real inbox or send provider messages.
- Blank credential fields during an update should preserve stored values.
- Import undo must protect later edits rather than remove them silently.
- Customer admins must not gain platform-only tools merely because a menu changes.
- Existing databases, uploads, and encryption keys need backups before migration or transfer.

## 9. Existing reference documents

Read this handoff first, then consult:

- `docs/upgrade-2026-09-10.md` — September implementation and validation notes.
- `docs/deployment/local_staging.md` — Local staging, backups, and recovery commands.
- `docs/deployment/production_checklist.md` — Pilot/production gates; some wording predates the latest upgrade.
- `docs/deployment/staging_checklist.md` — Staging acceptance items; older academy/UI assumptions need review.
- `docs/testing.md` — Earlier testing guidance.
- `AGENTS.md`, `frontend/AGENTS.md`, and `frontend/UI_QUALITY_RUBRIC.md` — Repository and frontend working guidance.

**Suggested first milestone for the next developer:** preserve the current uncommitted work, launch an isolated workspace, rerun the checks, complete the browser usability review, and prove one controlled real-channel conversation from customer message through reply/handoff. Agree with Fouad before choosing hosting or expanding the pilot scope.
