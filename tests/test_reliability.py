import os
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/gmail_bridge_reliability_tests.db")
os.environ.setdefault("BRIDGE_API_KEY", "test-bridge-key")
os.environ.setdefault("FERNET_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "https://example.test/auth/callback")

import pytest
import httplib2
from googleapiclient.errors import HttpError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import EmailSend
import app.gmail_service as service_module


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


class FakeRequest:
    def __init__(self, result=None, errors=None):
        self.result = result or {"id": "gmail-message-1", "threadId": "gmail-thread-1"}
        self.errors = list(errors or [])
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


class FakeService:
    def __init__(self, request):
        self.request = request

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, **kwargs):
        return self.request


def test_send_history_and_duplicate_protection(db, monkeypatch):
    request = FakeRequest()
    monkeypatch.setattr(service_module, "gmail_service", lambda _db: FakeService(request))
    first = service_module.send_message(db, "person@example.com", "Hello", "Body", idempotency_key="send-001")
    second = service_module.send_message(db, "person@example.com", "Hello", "Body", idempotency_key="send-001")
    assert first["status"] == "sent"
    assert second["duplicate"] is True
    assert request.calls == 1
    history = db.query(EmailSend).one()
    assert history.status == "sent"
    assert history.message_id == "gmail-message-1"
    assert not hasattr(history, "body")


def test_retry_after_rate_limit(db, monkeypatch):
    rate_limited = HttpError(httplib2.Response({"status": "429"}), b"rate limit")
    request = FakeRequest(errors=[rate_limited])
    monkeypatch.setattr(service_module, "gmail_service", lambda _db: FakeService(request))
    monkeypatch.setattr(service_module.time, "sleep", lambda _seconds: None)
    result = service_module.send_message(db, "person@example.com", "Hello", "Body", idempotency_key="send-002")
    assert result["status"] == "sent"
    assert result["attempts"] == 2
    assert request.calls == 2


def test_reusing_key_for_different_content_is_rejected(db, monkeypatch):
    request = FakeRequest()
    monkeypatch.setattr(service_module, "gmail_service", lambda _db: FakeService(request))
    service_module.send_message(db, "person@example.com", "Hello", "Body", idempotency_key="send-003")
    with pytest.raises(ValueError, match="different email"):
        service_module.send_message(db, "person@example.com", "Changed", "Body", idempotency_key="send-003")
    assert request.calls == 1
