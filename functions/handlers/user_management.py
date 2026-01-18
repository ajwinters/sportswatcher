"""
User management handlers for profile and player following.
"""

from typing import Any, Optional

from flask import jsonify

from services.firestore_service import FirestoreService
from handlers.sync_players import sync_specific_player


def get_authenticated_user(request: Any) -> Optional[dict]:
    """
    Extract and validate the authenticated user from the request.

    Args:
        request: HTTP request with Authorization header

    Returns:
        User data if authenticated, None otherwise
    """
    firestore = FirestoreService()

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    user_id = firestore.get_session_user(token)

    if not user_id:
        return None

    return firestore.get_user(user_id)


def get_profile(request: Any) -> tuple:
    """
    Get the current user's profile.

    Args:
        request: HTTP request

    Returns:
        Tuple of (response_dict, status_code)
    """
    user = get_authenticated_user(request)

    if not user:
        return {"error": "Unauthorized"}, 401

    # Return sanitized profile (exclude tokens)
    profile = {
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "picture": user.get("picture"),
        "followed_players": user.get("followed_players", []),
        "last_sync": user.get("last_sync"),
        "created_at": user.get("created_at"),
    }

    return profile, 200


def get_followed_players(request: Any) -> tuple:
    """
    Get the list of players the user is following.

    Args:
        request: HTTP request

    Returns:
        Tuple of (response_dict, status_code)
    """
    user = get_authenticated_user(request)

    if not user:
        return {"error": "Unauthorized"}, 401

    return {"players": user.get("followed_players", [])}, 200


def follow_player(request: Any) -> tuple:
    """
    Follow a player.

    Expects JSON body: { "player_key": "..." }

    Args:
        request: HTTP request

    Returns:
        Tuple of (response_dict, status_code)
    """
    user = get_authenticated_user(request)

    if not user:
        return {"error": "Unauthorized"}, 401

    try:
        data = request.get_json()
        if not data:
            return {"error": "Missing request body"}, 400

        player_key = data.get("player_key")
        if not player_key:
            return {"error": "player_key is required"}, 400

        firestore = FirestoreService()

        # Check if player exists in our database
        player = firestore.get_player(player_key)
        if not player:
            # Try to sync the player from API
            sync_result = sync_specific_player(player_key)
            if "error" in sync_result:
                return {"error": f"Player not found: {sync_result['error']}"}, 404
            player = sync_result.get("player")

        # Try to find the tour-specific player ID for web scraping
        tour_player_id = player.get("tour_player_id") or player.get("atp_player_id")
        player_tour = player.get("tour", "ATP")

        if not tour_player_id:
            tour_player_id, found_tour = _lookup_tour_player_id(player.get("name", ""), tour=player_tour)
            if found_tour:
                player_tour = found_tour

        # Add to followed list with tour player ID
        added = firestore.add_followed_player(
            user["user_id"],
            player_key,
            tour_player_id=tour_player_id,
            tour=player_tour
        )

        if not added:
            return {"message": "Already following this player"}, 200

        return {
            "success": True,
            "message": f"Now following {player.get('name', player_key)}",
            "player": {
                "player_key": player.get("player_key"),
                "name": player.get("name"),
                "tour_player_id": tour_player_id,
                "tour": player_tour,
            },
        }, 200

    except Exception as e:
        return {"error": str(e)}, 500


def _lookup_tour_player_id(player_name: str, tour: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Look up a player's tour-specific ID by name.

    Searches both ATP and WTA if tour is not specified.

    Args:
        player_name: Player's full name
        tour: Optional tour ("ATP" or "WTA")

    Returns:
        Tuple of (player_id, tour) or (None, None) if not found
    """
    if not player_name:
        return None, None

    try:
        from services.tour_scraper import get_tour_scraper
        scraper = get_tour_scraper()

        # Search the appropriate tour(s)
        results = scraper.search_player(player_name, tour=tour)

        # Try to find an exact match
        name_lower = player_name.lower()
        for result in results:
            if result.get("name", "").lower() == name_lower:
                return result.get("player_id"), result.get("tour")

        # If no exact match, return first result
        if results:
            return results[0].get("player_id"), results[0].get("tour")

    except Exception:
        pass

    return None, None


def _lookup_atp_player_id(player_name: str) -> Optional[str]:
    """
    Look up a player's ATP Tour ID by name.

    Backwards compatible function - tries ATP first, then WTA.

    Args:
        player_name: Player's full name

    Returns:
        Player ID or None if not found
    """
    player_id, _ = _lookup_tour_player_id(player_name)
    return player_id


def unfollow_player(request: Any, player_key: str) -> tuple:
    """
    Unfollow a player.

    Args:
        request: HTTP request
        player_key: Player key from URL path

    Returns:
        Tuple of (response_dict, status_code)
    """
    user = get_authenticated_user(request)

    if not user:
        return {"error": "Unauthorized"}, 401

    if not player_key:
        return {"error": "player_key is required"}, 400

    firestore = FirestoreService()
    removed = firestore.remove_followed_player(user["user_id"], player_key)

    if not removed:
        return {"error": "Not following this player"}, 404

    return {"success": True, "message": "Player unfollowed"}, 200


def search_players(request: Any) -> tuple:
    """
    Search for players by name.

    Query param: q (search query)

    Args:
        request: HTTP request

    Returns:
        Tuple of (response_dict, status_code)
    """
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return {"error": "Query must be at least 2 characters"}, 400

    firestore = FirestoreService()
    players = firestore.search_players(query, limit=20)

    # Get current user's followed players for marking
    user = get_authenticated_user(request)
    followed_keys = set()
    if user:
        followed_keys = {p["player_key"] for p in user.get("followed_players", [])}

    # Add is_following flag to each player
    for player in players:
        player["is_following"] = player.get("player_key") in followed_keys

    return {"players": players, "count": len(players)}, 200


def update_preferences(request: Any) -> tuple:
    """
    Update user preferences.

    Expects JSON body with preference fields.

    Args:
        request: HTTP request

    Returns:
        Tuple of (response_dict, status_code)
    """
    user = get_authenticated_user(request)

    if not user:
        return {"error": "Unauthorized"}, 401

    try:
        data = request.get_json()
        if not data:
            return {"error": "Missing request body"}, 400

        # Allowed preference fields
        allowed_fields = {
            "include_qualifying",
            "notify_hours_before",
            "calendar_id",
        }

        preferences = user.get("preferences", {})

        for field in allowed_fields:
            if field in data:
                preferences[field] = data[field]

        firestore = FirestoreService()
        firestore.db.collection("users").document(user["user_id"]).update({
            "preferences": preferences
        })

        return {"success": True, "preferences": preferences}, 200

    except Exception as e:
        return {"error": str(e)}, 500


def backfill_atp_ids(request: Any = None) -> dict:
    """
    Backfill tour player IDs for all followed players that don't have them.

    This is a maintenance function to add tour IDs to players that were
    followed before the scraper was implemented. Searches both ATP and WTA.

    Args:
        request: HTTP request (unused)

    Returns:
        Dictionary with backfill results
    """
    firestore = FirestoreService()
    results = {
        "users_processed": 0,
        "players_updated": 0,
        "players_skipped": 0,
        "errors": [],
    }

    users = firestore.get_all_users_with_players()

    for user in users:
        user_id = user["user_id"]
        followed_players = user.get("followed_players", [])
        updated = False

        for player in followed_players:
            # Check if already has tour player ID
            if player.get("tour_player_id") or player.get("atp_player_id"):
                results["players_skipped"] += 1
                continue

            # Look up tour ID (searches both ATP and WTA)
            player_name = player.get("name", "")
            player_tour = player.get("tour")
            tour_id, found_tour = _lookup_tour_player_id(player_name, tour=player_tour)

            if tour_id:
                player["tour_player_id"] = tour_id
                player["atp_player_id"] = tour_id  # Backward compatibility
                if found_tour:
                    player["tour"] = found_tour
                updated = True
                results["players_updated"] += 1
            else:
                results["errors"].append(f"Could not find tour ID for: {player_name}")

        if updated:
            # Update the user's followed_players in Firestore
            firestore.db.collection("users").document(user_id).update({
                "followed_players": followed_players
            })

        results["users_processed"] += 1

    return results
