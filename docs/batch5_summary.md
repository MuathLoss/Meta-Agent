# Batch 5 Summary

Batch 5 focuses on frontend operations polish and UAT support before the final WhatsApp/live deployment phase.

## Added

- `/uat/academy-cases` backend endpoint for safe academy acceptance test cases.
- `/uat/run-academy-cases` backend endpoint to run tenant-scoped intent/routing checks without creating customer messages.
- `/uat/custom` backend endpoint for one-off tenant UAT checks.
- New **UAT Tests** dashboard tab.
- Custom UAT message form in the dashboard.
- Better visual pass/fail result cards for UAT results.
- `runtimeScenario` frontend API helper for future manual scenario tests.

## Important

The UAT runner uses the logged-in tenant's own FAQ, intent keywords, and routing rules. It does not hardcode academy behavior in the core engine. The academy cases are only test cases for Tenant #1 validation.
