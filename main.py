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
            supplied = authorization[7:].strip()
        if not supplied or not hmac.compare_digest(supplied, settings.bridge_api_key):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized MCP request"})
    return await call_next(request)

Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def google_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, state=state, redirect_uri=settings.google_redirect_uri)


@app.get("/")
def root():
    return {"name": settings.app_name, "status": "running", "mcp_endpoint": "/mcp", "health": "/health"}


@app.get("/health")
def health():
    # Public liveness probe: deliberately reveals no database or account details.
    return {"ok": True, "service": "gmail-bridge"}


@app.get("/health/ready", dependencies=[Depends(require_bridge_key)])
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(sql_text("SELECT 1"))
        connected = db.get(GoogleCredential, 1) is not None
        credentials_valid = False
        auth_error = None
        if connected:
            try:
                credentials = get_credentials(db)
                credentials_valid = bool(credentials and credentials.valid)
            except GmailAuthError as exc:
                auth_error = str(exc)
        return {"ok": True, "database": "ok", "gmail_connected": connected,
                "gmail_credentials_valid": credentials_valid, "gmail_error": auth_error}
    except Exception:
        raise HTTPException(status_code=503, detail="Readiness check failed. Check database connectivity and application logs.")


@app.get("/auth/google")
def start_google_auth():
    state = secrets.token_urlsafe(32)
    flow = google_flow(state=state)
    # Pass lowercase text: the OAuth URL must contain include_granted_scopes=true,
    # not Python's capitalized boolean representation "True".
    authorization_url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    response = RedirectResponse(authorization_url)
    response.set_cookie("gmail_oauth_state", state, httponly=True, secure=settings.google_redirect_uri.startswith("https://"), samesite="lax", max_age=600)
    # google-auth-oauthlib creates a PKCE verifier per Flow instance. Persist it
    # across the redirect so the callback's new Flow can complete the token exchange.
    response.set_cookie("gmail_oauth_verifier", flow.code_verifier, httponly=True, secure=settings.google_redirect_uri.startswith("https://"), samesite="lax", max_age=600)
    return response


@app.get("/auth/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    state = request.query_params.get("state", "")
    cookie_state = request.cookies.get("gmail_oauth_state", "")
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(status_code=400, detail="OAuth state validation failed. Start again at /auth/google.")
    verifier = request.cookies.get("gmail_oauth_verifier", "")
    if not verifier:
        raise HTTPException(status_code=400, detail="OAuth PKCE verifier cookie is missing. Start again at /auth/google.")
    flow = google_flow(state=state)
    flow.code_verifier = verifier
    try:
        flow.fetch_token(authorization_response=str(request.url))
        save_credentials(db, flow.credentials)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google authorization failed: {exc}") from exc
    response = RedirectResponse(url="/health")
    response.delete_cookie("gmail_oauth_state")
    response.delete_cookie("gmail_oauth_verifier")
    response.headers["X-Gmail-Connected"] = "true"
    return response


@app.get("/gmail/status", dependencies=[Depends(require_bridge_key)])
def gmail_status(db: Session = Depends(get_db)):
    connected = db.get(GoogleCredential, 1) is not None
    valid = False
    error = None
    if connected:
        try:
            credentials = get_credentials(db)
            valid = bool(credentials and credentials.valid)
        except GmailAuthError as exc:
            error = str(exc)
    return {"connected": connected, "credentials_valid": valid,
            "scope": "gmail.send" if connected else None, "error": error}


@app.post("/attachments", dependencies=[Depends(require_bridge_key)])
async def upload_attachment(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read(settings.max_attachment_bytes + 1)
    if len(content) > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_attachment_bytes // (1024 * 1024)} MB limit")
    attachment_id = uuid.uuid4().hex
    item = store_attachment(db, attachment_id, file.filename or "attachment", content, file.content_type)
    return {"attachment_id": item.id, "filename": item.filename, "mime_type": item.mime_type, "size_bytes": len(content)}


@app.post("/gmail/send", dependencies=[Depends(require_bridge_key)])
def gmail_send(payload: dict, request: Request, db: Session = Depends(get_db)):
    required = ["to", "subject", "body"]
    missing = [field for field in required if payload.get(field) is None or payload.get(field) == ""]
    if missing:
        raise HTTPException(status_code=422, detail={"code": "missing_fields", "message": f"Missing fields: {', '.join(missing)}"})
    idempotency_key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    try:
        return send_message(db, payload["to"], payload["subject"], payload["body"],
                            payload.get("attachment_ids"), payload.get("cc"), payload.get("bcc"),
                            idempotency_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_request", "message": str(exc)}) from exc
    except RuntimeError as exc:
        message = str(exc)
        code = "send_outcome_unknown" if "unknown outcome" in message or "connection failed" in message else "send_conflict" if "already" in message else "gmail_send_failed"
        status = 409 if code in {"send_outcome_unknown", "send_conflict"} else 503
        raise HTTPException(status_code=status, detail={"code": code, "message": message}) from exc


@app.get("/gmail/history", dependencies=[Depends(require_bridge_key)])
def gmail_history(limit: int = 25, offset: int = 0, db: Session = Depends(get_db)):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail={"code": "invalid_pagination", "message": "limit must be 1-100 and offset must be 0 or greater."})
    rows = db.query(EmailSend).order_by(EmailSend.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [{"id": row.id, "status": row.status, "to": row.recipient,
                       "cc": row.cc, "bcc": row.bcc, "subject": row.subject,
                       "message_id": row.message_id, "thread_id": row.thread_id,
                       "attempts": row.attempts, "error_code": row.error_code,
                       "error": row.error_message, "created_at": row.created_at.isoformat() if row.created_at else None,
                       "updated_at": row.updated_at.isoformat() if row.updated_at else None}
                      for row in rows], "limit": limit, "offset": offset}


# FastMCP's streamable_http_app() in the pinned SDK wrapper takes no arguments.
# Its built-in endpoint is /mcp, so mount it at the root to expose /mcp directly.
app.mount("/", mcp.streamable_http_app())
