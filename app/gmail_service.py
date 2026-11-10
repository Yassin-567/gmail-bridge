import base64
import hashlib
import json
import mimetypes
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .models import EmailSend, GoogleCredential, StoredAttachment
from .security import decrypt_secret, encrypt_secret

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_GOOGLE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}
MAX_SEND_ATTEMPTS = 3


class GmailAuthError(RuntimeError):
    pass


def save_credentials(db: Session, credentials: Credentials) -> None:
    row = db.get(GoogleCredential, 1)
    encrypted = encrypt_secret(credentials.to_json())
    if row is None:
        db.add(GoogleCredential(id=1, encrypted_token_json=encrypted))
    else:
        row.encrypted_token_json = encrypted
        row.updated_at = datetime.now(timezone.utc)
    db.commit()


def get_credentials(db: Session) -> Credentials | None:
    row = db.get(GoogleCredential, 1)
    if row is None:
        return None
    try:
        info = json.loads(decrypt_secret(row.encrypted_token_json))
        credentials = Credentials.from_authorized_user_info(info, SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            save_credentials(db, credentials)
        return credentials
    except GoogleAuthError as exc:
        raise GmailAuthError("Google authorization could not be refreshed. Reconnect Gmail at /auth/google.") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise GmailAuthError("Stored Gmail credentials could not be read. Reconnect Gmail at /auth/google.") from exc


def gmail_service(db: Session):
    credentials = get_credentials(db)
    if credentials is None or not credentials.valid:
        raise GmailAuthError("Gmail is not connected. Open /auth/google to authorize it first.")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def make_idempotency_key(to: str, subject: str, body: str, attachment_ids: list[str] | None,
                         cc: str | None, bcc: str | None, supplied_key: str | None) -> tuple[str, str]:
    canonical = json.dumps({"to": to, "cc": cc, "bcc": bcc, "subject": subject,
                            "body": body, "attachments": attachment_ids or []},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if supplied_key:
        key = supplied_key.strip()
        if not key or len(key) > 200:
            raise ValueError("Idempotency-Key must contain between 1 and 200 characters.")
    else:
        # Backward-compatible fallback: identical requests collapse within a 10-minute window.
        bucket = int(time.time() // 600)
        key = "auto:" + hashlib.sha256(f"{bucket}:{canonical}".encode("utf-8")).hexdigest()
    return key, request_hash


def _is_retryable_http_error(exc: HttpError, status: int) -> bool:
    if status in RETRYABLE_HTTP_STATUSES:
        return True
    if status == 403:
        try:
            payload = json.loads(exc.content.decode("utf-8"))
            reasons = {item.get("reason") for item in payload.get("error", {}).get("errors", [])}
            return bool(reasons & RETRYABLE_GOOGLE_REASONS)
        except (AttributeError, UnicodeDecodeError, ValueError, TypeError):
            return False
    return False


def _history_result(row: EmailSend, duplicate: bool = False) -> dict:
    result = {"status": row.status, "message_id": row.message_id, "thread_id": row.thread_id,
              "to": row.recipient, "subject": row.subject, "attempts": row.attempts}
    if duplicate:
        result["duplicate"] = True
    if row.error_message:
        result["error"] = row.error_message
    return result


def send_message(db: Session, to: str, subject: str, body: str, attachment_ids: list[str] | None = None,
                 cc: str | None = None, bcc: str | None = None, idempotency_key: str | None = None) -> dict:
    key, request_hash = make_idempotency_key(to, subject, body, attachment_ids, cc, bcc, idempotency_key)
    existing = db.query(EmailSend).filter(EmailSend.idempotency_key == key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ValueError("This Idempotency-Key was already used for a different email.")
        if existing.status == "sent":
            return _history_result(existing, duplicate=True)
        if existing.status in {"sending", "unknown"}:
            raise RuntimeError("A send with this Idempotency-Key is already in progress or has an unknown outcome. Check /gmail/history before retrying.")
        existing.status = "sending"
        existing.error_code = None
        existing.error_message = None
        existing.updated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = EmailSend(id=str(uuid.uuid4()), idempotency_key=key, request_hash=request_hash,
                        status="sending", recipient=to, cc=cc, bcc=bcc, subject=subject, attempts=0)
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(EmailSend).filter(EmailSend.idempotency_key == key).first()
        if existing and existing.request_hash == request_hash and existing.status == "sent":
            return _history_result(existing, duplicate=True)
        raise RuntimeError("A matching send is already being processed. Check /gmail/history before retrying.")

    try:
        message = EmailMessage()
        message["To"] = to
        if cc:
            message["Cc"] = cc
        if bcc:
            message["Bcc"] = bcc
        message["Subject"] = subject
        message.set_content(body)
        for attachment_id in attachment_ids or []:
            attachment = db.get(StoredAttachment, attachment_id)
            if attachment is None:
                raise ValueError(f"Attachment not found: {attachment_id}")
            maintype, _, subtype = attachment.mime_type.partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service = gmail_service(db)
    except Exception as exc:
        row.status = "failed"
        row.error_code = type(exc).__name__
        row.error_message = str(exc)[:1000]
        db.commit()
        raise

    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        row.attempts = attempt
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        try:
            sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            row.status = "sent"
            row.message_id = sent.get("id")
            row.thread_id = sent.get("threadId")
            row.error_code = None
            row.error_message = None
            db.commit()
            return _history_result(row)
        except HttpError as exc:
            status = int(getattr(exc, "status_code", None) or getattr(exc.resp, "status", 0) or 0)
            if _is_retryable_http_error(exc, status) and attempt < MAX_SEND_ATTEMPTS:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            row.status = "failed"
            row.error_code = f"google_http_{status or 'error'}"
            row.error_message = f"Google returned HTTP {status}." if status else "Google rejected the send request."
            db.commit()
            raise RuntimeError(row.error_message) from exc
        except Exception as exc:
            # A transport failure can happen after Gmail accepted the message; never blindly resend it.
            row.status = "unknown"
            row.error_code = type(exc).__name__
            row.error_message = "The connection failed before Gmail confirmed the result. Check /gmail/history and Gmail Sent before retrying."
            db.commit()
            raise RuntimeError(row.error_message) from exc
    raise RuntimeError("Gmail send failed after retries.")


def store_attachment(db: Session, attachment_id: str, filename: str, content: bytes,
                     mime_type: str | None = None) -> StoredAttachment:
    detected = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    item = StoredAttachment(id=attachment_id, filename=filename, mime_type=detected, content=content)
    db.add(item)
    db.commit()
    return item
