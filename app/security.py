import secrets
from cryptography.fernet import Fernet
from fastapi import Header, HTTPException
from .config import settings

_cipher = Fernet(settings.fernet_key.encode())


def encrypt_secret(value: str) -> str:
    return _cipher.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _cipher.decrypt(value.encode()).decode()


def require_bridge_key(x_bridge_key: str | None = Header(default=None)) -> None:
    if not x_bridge_key or not secrets.compare_digest(x_bridge_key, settings.bridge_api_key):
        raise HTTPException(status_code=401, detail="Invalid bridge API key")
