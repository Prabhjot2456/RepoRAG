"""
GitHub OAuth authentication endpoints:
  GET  /api/auth/github/login     → Returns the GitHub OAuth URL to redirect the user
  GET  /api/auth/github/callback  → Handles the OAuth callback from GitHub
  GET  /api/auth/me               → Returns current user info (from signed token)
  GET  /api/auth/status            → Check if OAuth is configured
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.models.schemas import AuthStatus, GitHubLoginURL, GitHubUser
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Token signing ──────────────────────────────────────────────────────────────

def _sign_token(github_access_token: str) -> str:
    """Sign a GitHub access token so we can verify it later without a database."""
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(settings.session_secret)
    return s.dumps({"github_token": github_access_token})


def _verify_token(signed_token: str, max_age: int = 86400 * 30) -> str | None:
    """
    Verify a signed token and return the GitHub access token.
    Tokens are valid for 30 days by default.
    Returns None if the token is invalid or expired.
    """
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    s = URLSafeTimedSerializer(settings.session_secret)
    try:
        data = s.loads(signed_token, max_age=max_age)
        return data.get("github_token")
    except (BadSignature, SignatureExpired):
        return None


def extract_github_token(request: Request) -> str | None:
    """
    Extract GitHub access token from the request.
    Checks the Authorization header for a Bearer token.
    Returns the raw GitHub token if valid, else None.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        signed = auth_header[7:]
        return _verify_token(signed)
    return None


# ── OAuth endpoints ────────────────────────────────────────────────────────────

@router.get("/status", response_model=AuthStatus)
async def auth_status():
    """Check whether GitHub OAuth is configured on this server."""
    configured = bool(settings.github_client_id and settings.github_client_secret)
    return AuthStatus(
        authenticated=False,
        user=None,
        oauth_configured=configured,
    )


@router.get("/github/login", response_model=GitHubLoginURL)
async def github_login():
    """
    Returns the GitHub OAuth authorization URL.
    The frontend should redirect the user to this URL.
    """
    if not settings.github_client_id:
        raise HTTPException(
            status_code=501,
            detail="GitHub OAuth is not configured. "
                   "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env",
        )

    state = secrets.token_urlsafe(32)

    params = {
        "client_id": settings.github_client_id,
        "scope": "repo read:user user:email",
        "state": state,
        "redirect_uri": f"http://localhost:{settings.port}/api/auth/github/callback",
    }

    url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return GitHubLoginURL(url=url)


@router.get("/github/callback")
async def github_callback(code: str = Query(...), state: str = Query(default="")):
    """
    Handle the GitHub OAuth callback.
    Exchanges the authorization code for an access token,
    fetches user info, and returns a signed session token.

    Returns an HTML page that sends the token to the extension/frontend
    via postMessage and closes itself.
    """
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=501, detail="OAuth not configured.")

    # Exchange code for access token
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub token exchange failed.")

    token_data = token_resp.json()
    github_access_token = token_data.get("access_token")
    if not github_access_token:
        error = token_data.get("error_description", "Unknown error")
        raise HTTPException(status_code=400, detail=f"OAuth failed: {error}")

    # Fetch user info
    async with httpx.AsyncClient(timeout=10.0) as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {github_access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )

    if user_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch GitHub user info.")

    user_data = user_resp.json()

    # Sign the token for future API calls
    signed_token = _sign_token(github_access_token)

    user_info = {
        "login": user_data.get("login", ""),
        "name": user_data.get("name"),
        "avatar_url": user_data.get("avatar_url"),
        "email": user_data.get("email"),
        "access_token": signed_token,
    }

    logger.info("oauth_login_success", user=user_info["login"])

    # Return an HTML page that passes credentials back to the opener
    # (works for both extension popups and website windows)
    import json
    user_json = json.dumps(user_info)

    html = f"""<!DOCTYPE html>
<html>
<head><title>Login Successful</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         display: flex; align-items: center; justify-content: center;
         height: 100vh; margin: 0; background: #0d1117; color: #c9d1d9; }}
  .card {{ text-align: center; padding: 40px; border-radius: 12px;
           background: #161b22; border: 1px solid #30363d; }}
  h2 {{ color: #58a6ff; }}
</style>
</head>
<body>
<div class="card">
  <h2>✅ Login Successful</h2>
  <p>Welcome, <strong>{user_data.get("login", "")}</strong>!</p>
  <p>This window will close automatically...</p>
</div>
<script>
  const userData = {user_json};
  // Send to extension or opener window
  if (window.opener) {{
    window.opener.postMessage({{ type: 'github-oauth-success', user: userData }}, '*');
    setTimeout(() => window.close(), 1500);
  }} else if (chrome && chrome.runtime) {{
    chrome.runtime.sendMessage({{ type: 'github-oauth-success', user: userData }});
    setTimeout(() => window.close(), 1500);
  }} else {{
    // Store in localStorage as fallback
    localStorage.setItem('reporag_user', JSON.stringify(userData));
    setTimeout(() => window.close(), 2000);
  }}
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/me", response_model=GitHubUser)
async def get_current_user(request: Request):
    """
    Get the currently authenticated user's info.
    Requires a signed Bearer token in the Authorization header.
    """
    github_token = extract_github_token(request)
    if not github_token:
        raise HTTPException(status_code=401, detail="Not authenticated. Provide a valid Bearer token.")

    # Fetch fresh user info from GitHub
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="GitHub token is invalid or expired.")

    user_data = resp.json()

    return GitHubUser(
        login=user_data.get("login", ""),
        name=user_data.get("name"),
        avatar_url=user_data.get("avatar_url"),
        email=user_data.get("email"),
        access_token="[redacted]",  # Don't echo the token back
    )
