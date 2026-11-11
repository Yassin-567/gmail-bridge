---
name: gmail-bridge
description: Send emails through Yassin's private Gmail Bridge, including PDF and other file attachments. Use whenever the user asks to send an email from their Gmail account or attach a file.
---

# Gmail Bridge skill

## Purpose

Use the user's private Gmail Bridge for outgoing email, including messages with PDF attachments. This skill is intended to work across new chats when the user asks to use the "Gmail Bridge skill".

## Non-negotiable preferences and security

- Use the Gmail Bridge. Do **not** use the native Gmail connector or another mail provider as a fallback unless the user explicitly changes this preference.
- Never reveal, print, quote, or place secrets in chat, source files, logs, URLs, or generated artifacts.
- The bridge key and Vercel deployment access link are stored in the private configuration of the user's persistent Vercel sandbox. Google OAuth client secret and Fernet key remain in the deployed app's encrypted environment.
- Do not retrieve Vercel environment variables during normal sends. Do not create a new sandbox for each email.
- Do not claim an email was sent until the bridge returns a successful result with a Gmail message ID.
- Sending an email is an external action. Proceed when the user clearly asks to send it. Ask only for missing essential details.
- Do not blindly retry a send after a timeout or ambiguous network error. Check send history first.

## Known deployment and prepared runner

- Production app: `https://gmail-bridge-ten.vercel.app`
- GitHub repository: `https://github.com/Yassin-567/gmail-bridge`
- Vercel project ID: `prj_WTRkNs9tNlyUreywI1Vzoo9yLeQk`
- Vercel team ID: `team_vmsMQnU5QgWpQAsTlw4Xvxyc`
- Persistent sandbox name: `gmail-bridge-send`
- Runner script in the sandbox: `/vercel/gmail_bridge.py`
- The sandbox configuration contains `GMAIL_BRIDGE_ACCESS_URL` and `GMAIL_BRIDGE_KEY`. Treat both as secrets. Do not print them.
- The sandbox is persistent and automatically snapshots its files when it stops. It may be stopped after inactivity; resume the named sandbox instead of creating another one.
- The previously transferred CV is at `/vercel/cv_from_drive.pdf`. Verify the path exists before reusing it. It is a copy of the CV previously sent by the user.
- The helper supports `status`, `history`, and `send`. For `send`, it accepts local sandbox files, a public Google Drive file URL, or existing attachment IDs.

## Fast path in each new chat

Use the connected Vercel tools. This is the intended routine path; do not use the Vercel dashboard or retrieve secrets manually.

1. Call `mcp__Vercel__get_named_sandbox` with:
   - `name: "gmail-bridge-send"`
   - `projectId: "prj_WTRkNs9tNlyUreywI1Vzoo9yLeQk"`
   - `teamId: "team_vmsMQnU5QgWpQAsTlw4Xvxyc"`
   - `resume: true`
2. Read `result.sandbox.currentSessionId`.
3. Use `mcp__Vercel__run_session_command` with that session ID and the same team ID. Set `wait: true` and `logs: true` so the output is returned with the command.
4. For a readiness check, run:
   `python3 /vercel/gmail_bridge.py status`
5. To inspect send history after an ambiguous result, run:
   `python3 /vercel/gmail_bridge.py history --limit 25 --offset 0`
6. To send, run `python3 /vercel/gmail_bridge.py send` with arguments as separate command args:
   - `--to`, recipient
   - `--subject`, subject
   - `--body`, full body
   - optional `--cc`, `--bcc`
   - optional repeated `--file`, sandbox file path
   - optional repeated `--file-url`, public file URL (including Google Drive links)
   - optional `--filename`, filename for a URL-sourced attachment
   - optional `--attachment-id`, a Bridge attachment ID
   - optional `--idempotency-key`, only when retrying the identical send
7. The helper prints the idempotency key and result. Confirm success only if the result contains a successful status and a Gmail message ID.
8. Do not re-send with a new idempotency key after an ambiguous outcome. First inspect history; reuse the original key only for the exact same request.

When practical, orchestrate the resume and command in one `functions.exec` call so the user does not see setup steps.

## Session and access recovery

- If a command fails with `sandbox_stopped` or `410`, call `get_named_sandbox` again with `resume: true` and use the new session ID. Do not create a new sandbox.
- The stored Vercel share link may expire. Only if the app returns a Vercel login page, a protection error, or an access failure that indicates the share link expired:
  1. Call `mcp__Vercel__get_access_to_vercel_url` for `https://gmail-bridge-ten.vercel.app` and the known team ID.
  2. Store the returned access URL using `mcp__Vercel__update_sandbox` on `gmail-bridge-send`, setting only `requestBody.env.GMAIL_BRIDGE_ACCESS_URL`.
  3. Do not fetch the Bridge key again unless the user rotated it or the app returns an actual Bridge authentication error.
- If the Bridge returns a 401 after Vercel access has been confirmed, investigate Bridge authentication separately. Do not switch to native Gmail.
- If the named sandbox or helper script is genuinely missing, inspect the existing named sandbox and its snapshot before creating or rebuilding anything.

## Attachments

- If an attachment is already present in the sandbox, pass its path with `--file`.
- If the user provides a public Google Drive link, pass it with `--file-url`; the helper downloads it and uploads it to the Bridge using multipart field `file`.
- If the user uploads a file directly into ChatGPT, do not assume the file path is visible inside the remote Vercel sandbox. Use an available file-transfer action to stage the exact uploaded file into the sandbox. If no safe transfer path is available, ask for a Drive share link or clearly explain the transfer limitation. Never substitute a different file.
- The Bridge's attachment upload and email-send calls are separate. Never claim a send based only on an upload success.

## Reliability and API contract

- Authenticated routes include `/health/ready`, `/gmail/status`, `/gmail/history`, `/attachments`, and `/gmail/send`.
- `GET /health` is a public liveness check only; it does not prove readiness or Gmail authorization.
- All `/gmail/*` routes and `/health/ready` require `X-Bridge-Key`.
- `POST /attachments` is multipart with field name exactly `file`.
- `POST /gmail/send` accepts `to`, `subject`, `body`, optional `attachment_ids`, `cc`, and `bcc`.
- Include a stable `Idempotency-Key` for each distinct send operation. The helper generates one if not supplied and returns it in its output.
- Successful duplicate requests with the same idempotency key return the original Gmail message ID without sending again. Reusing a key with different content is rejected.
- Rate-limit and transient Google server errors are retried by the Bridge (up to three attempts with exponential backoff).
- Ambiguous transport failures are marked unknown and must not be blindly retried.
- Send history is metadata-only; email bodies and attachment contents are not stored in the history table.

## User-facing interaction

- Keep the process direct. Do not ask the user to run PowerShell or manually configure environment variables if connected tools can do the work.
- If the user says, for example, "Send this PDF to me and say hello", infer the requested short body and use the supplied/created PDF; ask only if the recipient or another essential detail is missing.
- Never say "sent" based only on an upload success. Confirm the recipient and attachments only after the Gmail message ID is returned.
- If the Bridge is unavailable, state what failed and what is needed to continue. Do not claim that the native Gmail connector can send through this Bridge.
