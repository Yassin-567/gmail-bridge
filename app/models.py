from datetime import datetime, timezone
from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class GoogleCredential(Base):
    __tablename__ = "google_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    encrypted_token_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StoredAttachment(Base):
    __tablename__ = "stored_attachments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EmailSend(Base):
    """Metadata-only send history and idempotency guard; never stores message bodies or tokens."""
    __tablename__ = "email_sends"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), index=True)
    recipient: Mapped[str] = mapped_column(Text)
    cc: Mapped[str | None] = mapped_column(Text, nullable=True)
    bcc: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_email_sends_created_at", "created_at"),)
