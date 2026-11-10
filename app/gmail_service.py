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
        credent¶»§q«^