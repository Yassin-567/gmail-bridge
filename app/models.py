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
    bcc: Mappe¶»§q«^t((€€€}}Ñ…‰±•}…ÉÍ}|€ô€¡%¹‘•à ‰¥á}•µ…¥±}Í•¹‘Í}É•…Ñ•‘}…Ğˆ°€‰É•…Ñ•‘}…Ğˆ¤°¤