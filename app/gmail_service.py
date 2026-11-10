import base64
import json
import mimetypes
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from .config import settings
from .models import GoogleCredential, StoredAttachment
from .security import decrypt_secret, encrypt_secret

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def save_credentials(db: Session, credentials: Credentials) -> None:
    row = db.get(GoogleCredential, 1)
    serialized = credentials.to_json()
    encrypted = encrypt_secret(serialized)
    if row is None:
        row = GoogleCredential(id=1, encrypted_token_json=encrypted)
        db.add(row)
    else:
        row.encrypted_token_json = encrypted
    db.commit()


def get_credentials(db: Session) -> Credentials | None:
    row = db.get(GoogleCredential, 1)
    if row is None:
        return None
    info = json.loads(decrypt_secret(row.encrypted_token_json))
    credentials = Credentials.from_authorized_user_info(info, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_credentials(db, credentials)
    return credentials


def gmail_service(db: Session):
    credentials = get_credentials(db)
    if credentials is None or not credentials.valid:
        raise RuntimeError("Gmail is not connected. Open /auth/google to authorize it first.")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def send_message(db: Session, to: str, subject: str, body: str, attachment_ids: list[str] | None = None, cc: str | None = None, bcc: str | None = None) -> dict:
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
    sent = gmail_service(db).users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"status": "sent", "message_id": sent.get("id"), "thread_id": sent.get("threadId"), "to": to, "subject": subject}


def store_attachment(db: Session, attachment_id: str, filename: str, content: bytes, mime_type: str | None = None) -> StoredAttachment:
    detected = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    item = StoredAttachment(id=attachment_id, filename=filename, mime_type=detected, content=content)
    db.add(item)
    db.commit()
    return item
