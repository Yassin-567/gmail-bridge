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
from app.gmail_service import SCOPES, save_credentials, store_attachment
from app.mcp_server import mcp
from app.security import require_bridge_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Bridge-Key"])


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
    return {"ok": True}


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
    from app.models import GoogleCredential
    return {"connected": db.get(GoogleCredential, 1) is not None, "scope": "gmail.send"}


@app.post("/attachments", dependencies=[Depends(require_bridge_key)])
async def upload_attachment(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read(settings.max_attachment_bytes + 1)
    if len(content) > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_attachment_bytes // (1024 * 1024)} MB limit")
    attachment_id = uuid.uuid4().hex
    item = store_attachment(db, attachment_id, file.filename or "attachment", content, file.content_type)
    return {"attachment_id": item.id, "filename": item.filename, "mime_type": item.mime_type, "size_bytes": len(content)}


@app.post("/gmail/send", dependencies=[Depends(require_bridge_key)])
def gmail_send(payload: dict, db: Session = Depends(get_db)):
    required = ["to", "subject", "body"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing fields: {', '.join(missing)}")
    from app.gmail_service import send_message
    try:
        return send_message(db, payload["to"], payload["subject"], payload["body"], payload.get("attachment_ids"), payload.get("cc"), payload.get("bcc"))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# FastMCP's streamable_http_app() in the pinned SDK wrapper takes no arguments.
# Its built-in endpoint is /mcp, so mount it at the root to expose /mcp directly.
app.mount("/", mcp.streamable_http_app())
