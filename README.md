# Gmail Bridge

Private Gmail sending bridge built with FastAPI and the Gmail API.

## Reliability endpoints

All `/gmail/*` routes and `/health/ready` require `X-Bridge-Key`. Keep the bridge key, Google OAuth client secret, and Fernet key in Vercel encrypted environment variables. Gmail OAuth tokens remain encrypted in the database; message bodies and attachment contents are not copied into the send-history table.

- `GET /health`: public liveness check only; does not reveal account or database state.
- `GET /health/ready`: authenticated readiness check for database connectivity and Gmail credential validity.
- `GET /gmail/status`: authenticated Gmail connection and credential status.
- `GET /gmail/history?limit=25&offset=0`: authenticated metadata-only send history (limit 1â€“100).
- `POST /attachments`: authenticated multipart attachment upload.
- `POST /gmail/send`: authenticated email send.

### Duplicate protection

Send requests should include a stable `Idempotency-Key` header (1â€“200 characters) and reuse that same key when retrying the same request. The key is bound to a SHA-256 hash of the request fields; reusing a key for different content is rejected. If the header is omitted, the API creates a backward-compatible fingerprint that deduplicates identical requests within a 10-minute window.

A successful repeat returns the original Gmail message ID without sending again. A request whose outcome is unknown is not automatically resent; check `/gmail/history` and Gmai¶»§q«^