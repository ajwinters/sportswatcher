"""
Handler for syncing tennis matches to Google Calendar.

This handler runs periodically to check for new matches for
users' followed players and creates/updates calendar events.
"""

from datetime import datetime, timedelta
from typing import Any

from services.tennis_api import TennisAPIClient, TennisAPIError
from services.firestore_service import FirestoreService
from services.calendar_service import CalendarService
from handlers.oauth_handler import get_user_credentials
from utils.event_builder import (
    build_calendar_event,
    calculate_event_hash,
    is_match_relevant,
)
from utils.rate_limiter import RateLimitExceeded


def sync_matches(request: Any = None) -> dict:
    """
    Sync upcoming matches for all users' followed players to their calendars.

    This function:
    1. Gets all users who have followed players
    2. For each user, fetches upcoming matches for their players
    3. Creates new calendar events or updates existing ones
    4. Tracks synced events in Firestore for deduplication

    Args:
        request: HTTP request object (unused, for Cloud Function compatibility)

    Returns:
        Dictionary with sync results
    """
    tennis_api = TennisAPIClient()
    firestore = FirestoreService()

    results = {
        "status": "completed",
        "started_at": datetime.utcnow().isoformat(),
        "users_processed": 0,
        "events_created": 0,
        "events_updated": 0,
        "events_skipped": 0,
        "errors": [],
    }

    # Get all users with followed players
    users = firestore.get_all_users_with_players()

    if not users:
        results["message"] = "No users with followed players found"
        return results

    for user in users:
        user_result = sync_user_matches(user, tennis_api, firestore)

        results["users_processed"] += 1
        results["events_created"] += user_result.get("events_created", 0)
        results["events_updated"] += user_result.get("events_updated", 0)
        results["events_skipped"] += user_result.get("events_skipped", 0)

        if user_result.get("errors"):
            results["errors"].extend(user_result["errors"][:5])

        # Update user's last sync time
        firestore.update_user_last_sync(user["user_id"])

        # Check rate limit status
        rate_status = tennis_api.get_rate_limit_status()
        if rate_status["day"] <= 5:
            results["status"] = "partial"
            results["message"] = "Rate limit nearly exhausted, stopping early"
            break

    results["completed_at"] = datetime.utcnow().isoformat()
    results["rate_limit_status"] = tennis_api.get_rate_limit_status()

    # Log the sync
    firestore.log_sync(
        sync_type="match_sync",
        records_processed=results["events_created"] + results["events_updated"],
        errors=results["errors"],
    )

    # Truncate errors for response
    if len(results["errors"]) > 10:
        results["errors"] = results["errors"][:10]
        results["errors"].append("... (truncated)")

    return results


def sync_user_matches(user: dict, tennis_api: TennisAPIClient, firestore: FirestoreService) -> dict:
    """
    Sync matches for a single user.

    Uses a single API call to get all live matches, then filters for followed players.
    This is more efficient than making one API call per player.

    Args:
        user: User data including followed_players and google_tokens
        tennis_api: Tennis API client
        firestore: Firestore service

    Returns:
        Dictionary with sync results for this user
    """
    result = {
        "events_created": 0,
        "events_updated": 0,
        "events_skipped": 0,
        "errors": [],
    }

    user_id = user["user_id"]
    followed_players = user.get("followed_players", [])
    calendar_id = user.get("preferences", {}).get("calendar_id", "primary")

    if not followed_players:
        return result

    # Get user credentials for calendar access
    try:
        credentials = get_user_credentials(user_id)
        calendar_service = CalendarService(credentials)
    except ValueError as e:
        result["errors"].append(f"User {user_id}: Failed to get credentials - {e}")
        return result

    # Build a lookup for player names by their IDs
    player_names_lookup = {p["player_key"]: p.get("name", "") for p in followed_players}
    player_ids = list(player_names_lookup.keys())

    # Collect player names for SerpAPI lookups
    player_names_list = [p.get("name", "") for p in followed_players if p.get("name")]

    # Collect tour player IDs (supports both new and legacy field names)
    tour_player_ids = []
    for p in followed_players:
        tour_id = p.get("tour_player_id") or p.get("atp_player_id")
        if tour_id:
            tour_player_ids.append(tour_id)

    try:
        # Get all matches for followed players (live + SerpAPI + tour scraper)
        matches = tennis_api.get_matches_for_players(
            player_ids,
            tour_player_ids,
            player_names=player_names_list
        )

        for match in matches:
            # Skip irrelevant matches
            if not is_match_relevant(match):
                result["events_skipped"] += 1
                continue

            match_key = match.get("event_key", match.get("id", ""))
            if not match_key:
                continue

            # Determine which followed player is in this match
            followed_ids = match.get("followed_player_ids", [])
            player_key = followed_ids[0] if followed_ids else ""
            # Handle both player_key IDs and player names (from SerpAPI)
            player_name = player_names_lookup.get(player_key, "")
            if not player_name and player_key:
                # SerpAPI returns player names as followed_player_ids
                player_name = player_key

            # Check if we already synced this match
            existing_event = firestore.get_synced_event(user_id, str(match_key))
            event_hash = calculate_event_hash(match)

            if existing_event:
                # Check if match details changed
                if existing_event.get("event_hash") != event_hash:
                    # Update the calendar event
                    try:
                        event_data = build_calendar_event(match, player_name)
                        calendar_service.update_event(
                            calendar_id,
                            existing_event["calendar_event_id"],
                            event_data,
                        )
                        firestore.update_synced_event(
                            existing_event["id"],
                            {
                                "event_hash": event_hash,
                                "scheduled_time": match.get("event_date"),
                                "match_status": match.get("event_status", "scheduled"),
                            },
                        )
                        result["events_updated"] += 1
                    except Exception as e:
                        result["errors"].append(
                            f"Failed to update event {match_key}: {e}"
                        )
                else:
                    result["events_skipped"] += 1
            else:
                # Create new calendar event
                try:
                    event_data = build_calendar_event(match, player_name)
                    calendar_event = calendar_service.create_event(
                        calendar_id,
                        event_data,
                        str(match_key),
                    )

                    # Record in Firestore
                    firestore.create_synced_event({
                        "match_key": str(match_key),
                        "user_id": user_id,
                        "calendar_event_id": calendar_event["id"],
                        "player_key": player_key,
                        "event_hash": event_hash,
                        "scheduled_time": match.get("event_date"),
                        "match_status": match.get("event_status", "scheduled"),
                        "tournament_name": match.get("tournament_name", ""),
                    })
                    result["events_created"] += 1

                except Exception as e:
                    result["errors"].append(
                        f"Failed to create event for {match_key}: {e}"
                    )

    except RateLimitExceeded as e:
        result["errors"].append(f"Rate limit exceeded: {e}")

    except TennisAPIError as e:
        result["errors"].append(f"API error: {e}")

    except Exception as e:
        result["errors"].append(f"Error processing matches: {e}")

    return result


def sync_single_user(user_id: str) -> dict:
    """
    Sync matches for a single user on demand.

    Useful for triggering a sync after a user follows a new player.

    Args:
        user_id: The user's ID

    Returns:
        Dictionary with sync results
    """
    tennis_api = TennisAPIClient()
    firestore = FirestoreService()

    user = firestore.get_user(user_id)
    if not user:
        return {"error": "User not found"}

    result = sync_user_matches(user, tennis_api, firestore)
    firestore.update_user_last_sync(user_id)

    return result


def cleanup_old_events(request: Any = None) -> dict:
    """
    Clean up old synced event records and optionally delete cancelled events.

    Args:
        request: HTTP request object (unused)

    Returns:
        Dictionary with cleanup results
    """
    firestore = FirestoreService()

    results = {
        "status": "completed",
        "records_deleted": 0,
        "calendar_events_deleted": 0,
        "errors": [],
    }

    # Get events older than 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)
    old_events = firestore.get_old_synced_events(cutoff)

    for event in old_events:
        try:
            # If match was cancelled, try to delete from calendar
            if event.get("match_status") in ["cancelled", "CANC", "ABD"]:
                try:
                    user = firestore.get_user(event["user_id"])
                    if user:
                        credentials = get_user_credentials(event["user_id"])
                        calendar = CalendarService(credentials)
                        calendar_id = user.get("preferences", {}).get("calendar_id", "primary")
                        calendar.delete_event(calendar_id, event["calendar_event_id"])
                        results["calendar_events_deleted"] += 1
                except Exception:
                    pass  # Event may already be deleted

            # Delete the Firestore record
            firestore.delete_synced_event(event["id"])
            results["records_deleted"] += 1

        except Exception as e:
            results["errors"].append(f"Failed to clean up {event.get('id')}: {e}")

    results["completed_at"] = datetime.utcnow().isoformat()
    return results
