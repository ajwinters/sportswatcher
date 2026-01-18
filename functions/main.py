"""
Main entry point for Cloud Functions.

Defines HTTP endpoints for:
- api_gateway: REST API for frontend
- sync_players: Scheduled player database sync
- sync_matches: Scheduled match calendar sync
- cleanup_events: Weekly cleanup of old records
"""

import functions_framework
from flask import jsonify, request

from handlers.sync_players import sync_players as do_sync_players
from handlers.sync_matches import sync_matches as do_sync_matches, cleanup_old_events
from handlers.oauth_handler import initiate_auth, handle_callback, logout
from handlers.user_management import (
    get_profile,
    get_followed_players,
    follow_player,
    unfollow_player,
    search_players,
    update_preferences,
    backfill_atp_ids,
)
from config.settings import get_settings


def cors_headers():
    """Get CORS headers for responses."""
    # CORS origin must be just the origin (scheme + host), not the full URL
    return {
        "Access-Control-Allow-Origin": "https://storage.googleapis.com",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "3600",
    }


def make_response(data, status_code=200):
    """Create a JSON response with CORS headers."""
    response = jsonify(data)
    for key, value in cors_headers().items():
        response.headers[key] = value
    return response, status_code


def handle_cors_preflight():
    """Handle CORS preflight request."""
    response = jsonify({})
    for key, value in cors_headers().items():
        response.headers[key] = value
    return response, 204


# ==================== API Gateway ====================

@functions_framework.http
def api_gateway(request):
    """
    Main API gateway for frontend requests.

    Routes:
    - GET  /players?q=...        - Search players
    - GET  /players/followed     - Get followed players
    - POST /players/follow       - Follow a player
    - DELETE /players/follow/:id - Unfollow a player
    - GET  /auth/google          - Start OAuth flow
    - GET  /auth/callback        - OAuth callback
    - POST /auth/logout          - Logout
    - GET  /user/profile         - Get user profile
    - PUT  /user/preferences     - Update preferences
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return handle_cors_preflight()

    path = request.path
    method = request.method

    try:
        # Player routes
        if path == "/players" and method == "GET":
            result, status = search_players(request)
            return make_response(result, status)

        elif path == "/players/followed" and method == "GET":
            result, status = get_followed_players(request)
            return make_response(result, status)

        elif path == "/players/follow" and method == "POST":
            result, status = follow_player(request)
            return make_response(result, status)

        elif path.startswith("/players/follow/") and method == "DELETE":
            player_key = path.split("/players/follow/")[1]
            result, status = unfollow_player(request, player_key)
            return make_response(result, status)

        # Auth routes
        elif path == "/auth/google" and method == "GET":
            return initiate_auth(request)

        elif path == "/auth/callback" and method == "GET":
            return handle_callback(request)

        elif path == "/auth/logout" and method == "POST":
            result = logout(request)
            return make_response(result, 200)

        # User routes
        elif path == "/user/profile" and method == "GET":
            result, status = get_profile(request)
            return make_response(result, status)

        elif path == "/user/preferences" and method == "PUT":
            result, status = update_preferences(request)
            return make_response(result, status)

        # Health check
        elif path == "/health" and method == "GET":
            return make_response({"status": "healthy"}, 200)

        # Admin routes
        elif path == "/admin/backfill-atp-ids" and method == "POST":
            result = backfill_atp_ids(request)
            return make_response(result, 200)

        # Not found
        else:
            return make_response({"error": "Not found"}, 404)

    except Exception as e:
        return make_response({"error": str(e)}, 500)


# ==================== Scheduled Functions ====================

@functions_framework.http
def sync_players(request):
    """
    Sync tennis players from API to Firestore.

    Triggered by Cloud Scheduler daily.
    """
    try:
        result = do_sync_players(request)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@functions_framework.http
def sync_matches(request):
    """
    Sync upcoming matches to users' Google Calendars.

    Triggered by Cloud Scheduler every 6 hours.
    """
    try:
        result = do_sync_matches(request)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@functions_framework.http
def cleanup_events(request):
    """
    Clean up old synced event records.

    Triggered by Cloud Scheduler weekly.
    """
    try:
        result = cleanup_old_events(request)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
