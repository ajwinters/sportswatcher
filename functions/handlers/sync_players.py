"""
Handler for syncing tennis players from the API to Firestore.

This handler is triggered by Cloud Scheduler (daily) to keep
the player database up to date.
"""

from datetime import datetime
from typing import Any

from services.tennis_api import TennisAPIClient, normalize_player_data, TennisAPIError
from services.firestore_service import FirestoreService
from utils.rate_limiter import RateLimitExceeded


def sync_players(request: Any = None) -> dict:
    """
    Sync all tennis players from ATP and WTA rankings to Firestore.

    This function:
    1. Fetches ATP standings (top ranked players)
    2. Fetches WTA standings (top ranked players)
    3. Upserts each player to Firestore with search terms

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
        "players_synced": 0,
        "atp_players": 0,
        "wta_players": 0,
        "errors": [],
    }

    tours = ["ATP", "WTA"]

    for tour in tours:
        try:
            # Get standings which include ranked players
            standings = tennis_api.get_standings(tour)

            if not standings:
                results["errors"].append(f"No standings returned for {tour}")
                continue

            for player_data in standings:
                try:
                    # Normalize the player data
                    player = normalize_player_data(player_data, tour)

                    if not player.get("player_key"):
                        continue

                    # Upsert to Firestore
                    firestore.upsert_player(player)
                    results["players_synced"] += 1

                    if tour == "ATP":
                        results["atp_players"] += 1
                    else:
                        results["wta_players"] += 1

                except Exception as e:
                    error_msg = f"Player {player_data.get('player_key', 'unknown')}: {e}"
                    results["errors"].append(error_msg)
                    if len(results["errors"]) > 20:
                        # Stop collecting errors after 20
                        break

        except RateLimitExceeded as e:
            results["errors"].append(f"Rate limit exceeded for {tour}: {e}")
            results["status"] = "partial"
            break

        except TennisAPIError as e:
            results["errors"].append(f"API error for {tour}: {e}")

        except Exception as e:
            results["errors"].append(f"Unexpected error for {tour}: {e}")

    # Log the sync operation
    firestore.log_sync(
        sync_type="player_sync",
        records_processed=results["players_synced"],
        errors=results["errors"],
    )

    results["completed_at"] = datetime.utcnow().isoformat()
    results["rate_limit_status"] = tennis_api.get_rate_limit_status()

    # Truncate errors for response
    if len(results["errors"]) > 10:
        results["errors"] = results["errors"][:10]
        results["errors"].append("... (truncated)")

    return results


def sync_specific_player(player_key: str) -> dict:
    """
    Sync a specific player's data from the API.

    Useful for on-demand updates when a user follows a player.

    Args:
        player_key: The player's unique identifier

    Returns:
        Dictionary with the synced player data or error
    """
    tennis_api = TennisAPIClient()
    firestore = FirestoreService()

    try:
        player_data = tennis_api.get_player(player_key)

        if not player_data:
            return {"error": "Player not found", "player_key": player_key}

        # Determine tour from player data or default to ATP
        tour = "WTA" if "WTA" in player_data.get("player_type", "") else "ATP"

        player = normalize_player_data(player_data, tour)
        firestore.upsert_player(player)

        return {"status": "success", "player": player}

    except RateLimitExceeded as e:
        return {"error": str(e), "player_key": player_key}

    except TennisAPIError as e:
        return {"error": str(e), "player_key": player_key}

    except Exception as e:
        return {"error": f"Unexpected error: {e}", "player_key": player_key}
