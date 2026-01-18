"""
OAuth handler for Google authentication and Calendar authorization.

Manages the OAuth 2.0 flow for users to authorize calendar access.
"""

import secrets
from typing import Any
from urllib.parse import urlencode

from flask import redirect, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config.settings import get_settings
from services.firestore_service import FirestoreService


# OAuth scopes required for the application
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]


def get_oauth_flow(state: str = None) -> Flow:
    """
    Create an OAuth flow instance.

    Args:
        state: Optional state parameter for CSRF protection

    Returns:
        Configured OAuth Flow instance
    """
    settings = get_settings()

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.oauth_redirect_uri],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.oauth_redirect_uri

    return flow


def initiate_auth(request: Any) -> Any:
    """
    Start the OAuth flow by redirecting to Google's authorization page.

    Args:
        request: HTTP request object

    Returns:
        Redirect response to Google OAuth
    """
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state for verification
    firestore = FirestoreService()
    firestore.store_oauth_state(state, {"initiated_from": "web"})

    # Create flow and get authorization URL
    flow = get_oauth_flow(state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # Force consent to always get refresh token
    )

    return redirect(authorization_url)


def handle_callback(request: Any) -> Any:
    """
    Handle the OAuth callback from Google.

    Exchanges the authorization code for tokens, creates/updates the user,
    and redirects to the frontend with a session token.

    Args:
        request: HTTP request object with code and state parameters

    Returns:
        Redirect to frontend with session token or error
    """
    settings = get_settings()
    firestore = FirestoreService()

    # Get parameters from request
    state = request.args.get("state")
    code = request.args.get("code")
    error = request.args.get("error")

    # Handle OAuth errors
    if error:
        error_description = request.args.get("error_description", error)
        return redirect(f"{settings.frontend_url}?error={error_description}")

    # Verify state
    if not state or not firestore.verify_oauth_state(state):
        return redirect(f"{settings.frontend_url}?error=invalid_state")

    try:
        # Exchange code for tokens
        flow = get_oauth_flow(state)
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user info from Google
        oauth_service = build("oauth2", "v2", credentials=credentials)
        user_info = oauth_service.userinfo().get().execute()

        # Prepare user data
        user_id = user_info["id"]
        user_data = {
            "email": user_info.get("email", ""),
            "display_name": user_info.get("name", ""),
            "picture": user_info.get("picture", ""),
            "google_tokens": {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
            },
        }

        # Create or update user
        firestore.upsert_user(user_id, user_data)

        # Create session
        session_token = firestore.create_session(user_id)

        # Redirect to frontend with session token
        return redirect(f"{settings.frontend_url}?token={session_token}")

    except Exception as e:
        error_msg = str(e)[:100]  # Truncate error message
        return redirect(f"{settings.frontend_url}?error={error_msg}")


def refresh_user_tokens(user_id: str) -> bool:
    """
    Refresh a user's access token using their refresh token.

    Args:
        user_id: The user's ID

    Returns:
        True if refresh succeeded, False otherwise
    """
    settings = get_settings()
    firestore = FirestoreService()

    user = firestore.get_user(user_id)
    if not user:
        return False

    tokens = user.get("google_tokens", {})
    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        return False

    try:
        credentials = Credentials(
            token=tokens.get("access_token"),
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

        # Force refresh
        from google.auth.transport.requests import Request
        credentials.refresh(Request())

        # Update stored tokens
        new_tokens = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token or refresh_token,
            "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }

        firestore.update_user_tokens(user_id, new_tokens)
        return True

    except Exception as e:
        firestore.log_error(f"Token refresh failed for user {user_id}: {e}")
        return False


def get_user_credentials(user_id: str) -> Credentials:
    """
    Get valid credentials for a user, refreshing if needed.

    Args:
        user_id: The user's ID

    Returns:
        Valid Google Credentials object

    Raises:
        ValueError: If user not found or tokens invalid
    """
    settings = get_settings()
    firestore = FirestoreService()

    user = firestore.get_user(user_id)
    if not user:
        raise ValueError("User not found")

    tokens = user.get("google_tokens", {})
    if not tokens.get("access_token"):
        raise ValueError("User has no tokens")

    credentials = Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )

    # Check if token needs refresh
    if credentials.expired and credentials.refresh_token:
        if not refresh_user_tokens(user_id):
            raise ValueError("Token refresh failed")

        # Reload credentials
        user = firestore.get_user(user_id)
        tokens = user.get("google_tokens", {})
        credentials = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

    return credentials


def logout(request: Any) -> dict:
    """
    Log out the current user by destroying their session.

    Args:
        request: HTTP request with Authorization header

    Returns:
        Success/error response
    """
    firestore = FirestoreService()

    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        firestore.delete_session(token)
        return {"status": "logged_out"}

    return {"error": "No session found"}
