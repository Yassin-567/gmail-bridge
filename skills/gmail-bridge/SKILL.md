---
name: gmail-bridge
description: Send emails through Yassin's private Gmail Bridge, including PDF and other file attachments. Use whenever the user asks to send an email from their Gmail account or attach a file.
---

# Gmail Bridge skill

## Purpose

Use the user's private Gmail Bridge for outgoing email, including messages with PDF attachments. This skill is intended to work across new chats when the user asks to use the "Gmail Bridge skill".

## Non-negotiable preferences and security

- Prefer the Gmail Bridge. Do **not** use the native Gmail connector or another mail provider as a fallback unless the user explicitly changes this preference.
- Never reveal, print, quote, or place secrets in chat, source files, logs, URLs, or generated artifacts.
- The bridge key, Google OAuth client secret, Fernet key, and Vercel deployment-protection bypass value must remain in the user's encrypted environment/configuration. Never ask the user to paste secrets into chat if an authorized connected tool can access them.
- Do not claim an email was sent until the bridge returns a successful result with a Gmail message ID.
- Sending an email is an external action. Proceed when the user clearly asks to send it. Ask only for missing essential details.
- Do not blindly retry a send after a timeout or ambiguous network error. Check send history and Gmail Sent first.

## Known deployment

- Production base URL: `https://gmail-bridge-ten.vercel.app`
- GitHub repository: `https://github.com/Yassin-567/gmail-bridge`
- Vercel project: `gmail-bridge`
- Authenticated routes include `/health/ready`, `/gmail/status`, `/gmail/history`, `/attachments`, and `/gmail/send`.
- `GET /health` is a public liveness check only. It does not prove Gmail authorization or database readiness.
- All `/gmail/*` routes and `/health/ready` require `X-Bridge-Key`.
- Vercel deployment protection may also require its configured bypass value. Supply it only through an authorized tool's secure/header/query mechanism; never expose it in user-visible text.

## Tool discovery in every new chat

1. Inspect the tools available in the current chat for an authenticated HTTP/API request capability that can send GET and POST requests with custom headers and multipart form data.
2. If available, use that capability to call the bridge. Use connected Vercel/GitHub tools for configuration or source inspection only when needed.
3. Do not assume that a Vercel deployment inspection/fetch tool can call protected application routes. Do not repeat a method that returned 401.
4. If no authorized HTTP request capability or secure access to the configured secrets is available, explain the exact missing capability. Do not switch to native Gmail.

## Sending workflow

1. Identify the recipient, subject, body, and any requested attachment. If the user supplied a file in the current chat, use that exact file. If they asked for a PDF to be created, create the PDF first using an available file-generation tool; verify the file exists and is a valid PDF before uploading. If file generation is unavailable, explain that limitation and ask the user to upload the PDF or retry later. Never pretend a PDF exists.
2. Check bridge readiness with authenticated `GET /health/ready` when appropriate. Optionally inspect `GET /gmail/status` if authorization needs checking.
3. For an attachment, use authenticated `POST /attachments` as multipart upload. Read the current API schema or OpenAPI definition/source before constructing the request; do not guess multipart field names or the response's attachment identifier.
4. Send using authenticated `POST /gmail/send`, following the current request schema. Include the attachment reference returned by the upload route as required by the API. Use the user's exact recipient, subject, and message.
5. Include a stable `Idempotency-Key` header for each distinct send operation. Reuse the same key only when safely retrying the identical request. Never reuse it for different message content.
6. Confirm success only after receiving the successful response and Gmail message ID. Report the recipient and whether the attachment was included.
7. If the result is ambiguous (timeout, dropped connection, or unknown status), do not resend immediately. Check `GET /gmail/history?limit=25&offset=0` and Gmail Sent, if available. If the result remains uncertain, tell the user and ask before any new send attempt.

## Reliability behavior

- The bridge supports metadata-only send history; message bodies and attachment contents are not stored in that history.
- Successful duplicate requests with the same idempotency key return the original Gmail message ID without sending again.
- Reusing an idempotency key with different request content is rejected.
- Rate-limit and transient Google server errors are retried by the bridge (up to three attempts with exponential backoff).
- Ambiguous transport failures are marked unknown and must not be blindly retried.
- The bridge's `/health` endpoint alone is not a readiness or authorization test.

## User-facing interaction

- Keep the process direct. Do not ask the user to run PowerShell or manually configure environment variables if connected tools can do the work.
- If the user says, for example, "Send this PDF to me and say hello", infer the requested short body and use the supplied/created PDF; ask only if the recipient or another essential detail is missing.
- Never say "sent" based only on an upload success. Attachment upload and email send are separate steps.
- If the bridge is unavailable, state what failed and what is needed to continue. Do not claim that the native Gmail connector can attach/send through this bridge.
