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
        return s¶»§q«^