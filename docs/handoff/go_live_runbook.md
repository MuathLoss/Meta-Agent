# Academy WhatsApp Go-Live Runbook

1. Deploy backend to a public HTTPS staging environment.
2. Deploy frontend to staging.
3. Connect staging backend to managed PostgreSQL.
4. Confirm `/health` and `/health/ready` pass.
5. Run backend tests.
6. Run dashboard UAT tab.
7. Review Deployment tab.
8. Review Final Handoff tab.
9. Collect academy WhatsApp package.
10. Store WhatsApp credentials in the academy tenant's `channel_configs` only.
11. Configure Meta webhook callback URL.
12. Verify webhook challenge.
13. Send controlled test messages.
14. Enable `live_send_enabled` only after successful testing.
15. Repeat on production.
