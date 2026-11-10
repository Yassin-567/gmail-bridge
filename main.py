import secrets
import hmac
import uuid
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.gmail_service import SCOPES, GmailAuthError, get_credentials, save_credentials, send_message, store_attachment
from app.mcp_server import mcp
from app.security import require_bridge_key
from app.models import EmailSend, GoogleCredential
from sqlalchemy import text as sql_text

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Bridge-Key", "Idempotency-Key"])


@app.middleware("http")
async def protect_mcp(request: Request, call_next):
    if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
        supplied = request.headers.get("x-bridge-key", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()¶»§q«^