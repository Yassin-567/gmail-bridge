import base64
import binascii
import uuid
from mcp.server.fastmcp import FastMCP
from .config import settings
from .database import SessionLocal
from .gmail_service import send_message, store_attachment
from .models import GoogleCredential

mcp = FastMCP("Gmail Bridge", stateless_http=True)


@mcp.tool()
def gmail_connection_status() -> dict:
    """Check whether the Gmail account has been authorized for sending."""
    with SessionLocal() as db:
        connected = db.get(GoogleCredential, 1) is not None
        return {"connected": connected, "scope": "gmail.send" if connected else None}


@mcp.tool()
def upload_attachment(filename: str, content_base64: str, mime_type: str | None = None) -> dict:
    """Store a file for a later Gmail message. Supply the file bytes as base64; max size is 15 MB by default."""
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        return {"error": "content_base64 is not valid base64"}
    if len(content) > settings.max_attachment_bytes:
        return {"error": f"File exceeds the {settings.max_attachment_bytes // (1024 * 1024)} MB limit"}
    attachment_id = uuid.uuid4().hex
    with SessionLocal() as db:
        item = store_attachment(db, attachment_id, filename, content, mime_type)
    return {"attachment_id": item.id, "filename": item.filename, "mime_type": item.mime_type, "size_bytes": len(content)}


@mcp.tool()
def send_gmail(to: str, subject: str, body: str, attachmen¶»§q«^