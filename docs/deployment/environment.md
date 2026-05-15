# Environment Model

## Platform environment

Used only for shared platform operation:

```env
APP_ENV=development
APP_SECRET_KEY=replace-with-long-random-secret
JWT_REFRESH_SECRET_KEY=replace-with-another-long-random-secret
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_MINUTES=10080
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/business_agent_platform_v2
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
FRONTEND_URL=http://127.0.0.1:5173
DEFAULT_TIMEZONE=Asia/Riyadh
LOG_LEVEL=INFO
TENANT_CHANNEL_SECRET_KEY=replace-with-generated-fernet-key
ALLOW_UNSIGNED_WEBHOOKS_IN_DEV=true
OLLAMA_ENABLED=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e4b
OLLAMA_TIMEOUT_SECONDS=10
```

## Tenant channel configuration

Stored inside the platform database per tenant/channel, encrypted at rest:

- WhatsApp token.
- WABA ID.
- Phone number ID.
- Verify token.
- App secret.
- Approved template references.
- Future email/Instagram/Facebook/web chat credentials.
