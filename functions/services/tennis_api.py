"""
Tennis API client for fetching player and match data.

Uses TennisApi1 via RapidAPI.
"""

from datetime import datetime, timedelta
from typing import Optional
import requests

from config.settings import get_settings
from utils.rate_limiter import get_tennis_api_limiter, RateLimitExceeded


class TennisAPIError(Exception):
    """Raised when Tennis API returns an error."""
    pass


class TennisAPIClient:
    """
    Client for TennisApi1 via RapidAPI.

    Handles rate limiting, authentication, and response parsing.
    Endpoint: https://tennisapi1.p.rapidapi.com/api/tennis
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.tennis_api_key
        self.base_url = "https://tennisapi1.p.rapidapi.com/api/tennis"
        self.api_host = "tennisapi1.p.rapidapi.com"
        self.rate_limiter = get_tennis_api_limiter()

    def _get_headers(self) -> dict:
        """Get request headers."""
        return {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.api_host,
        }

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """
        Make a rate-limited API request.

        Args:
            endpoint: API endpoint path (e.g., '/rankings/atp')
            params: Additional query parameters

        Returns:
            Response data from the API

        Raises:
            TennisAPIError: If the API returns an error
            RateLimitExceeded: If rate limit is reached
        """
        self.rate_limiter.wait_if_needed()

        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            raise TennisAPIError(f"Request failed: {e}") from e

    # ==================== Rankings Endpoints ====================

    def get_standings(self, tour: str = "ATP") -> list[dict]:
        """
        Get ATP or WTA rankings.

        Args:
            tour: "ATP" or "WTA"

        Returns:
            List of players with rankings
        """
        endpoint = f"/rankings/{tour.lower()}"
        data = self._make_request(endpoint)
        return data.get("rankings", [])

    # ==================== Player Endpoints ====================

    def get_player(self, player_id: str) -> Optional[dict]:
        """
        Get detailed player information.

        Args:
            player_id: Player identifier

        Returns:
            Player data or None if not found
        """
        try:
            data = self._make_request(f"/player/{player_id}")
            return data.get("player", None)
        except TennisAPIError:
            return None

    def search_players(self, name: str) -> list[dict]:
        """
        Search for players by name.

        Args:
            name: Player name to search

        Returns:
            List of matching players
        """
        data = self._make_request("/search", {"term": name})
        # Filter to only return player results
        results = data.get("results", [])
        return [r for r in results if r.get("type") == "player"]

    # ==================== Match/Event Endpoints ====================

    def get_player_events(self, player_id: str) -> list[dict]:
        """
        Get events for a specific player.

        Args:
            player_id: Player identifier

        Returns:
            List of events
        """
        data = self._make_request(f"/player/{player_id}/events")
        return data.get("events", [])

    def get_player_next_events(self, player_id: str) -> list[dict]:
        """
        Get upcoming events for a player.

        Args:
            player_id: Player identifier

        Returns:
            List of upcoming events
        """
        data = self._make_request(f"/player/{player_id}/events/next")
        return data.get("events", [])

    def get_player_last_events(self, player_id: str) -> list[dict]:
        """
        Get recent events for a player.

        Args:
            player_id: Player identifier

        Returns:
            List of recent events
        """
        data = self._make_request(f"/player/{player_id}/events/last")
        return data.get("events", [])

    def get_live_events(self) -> list[dict]:
        """
        Get currently live matches.

        Returns:
            List of live events
        """
        data = self._make_request("/events/live")
        return data.get("events", [])

    def get_events_by_date(self, date: str) -> list[dict]:
        """
        Get all events on a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of events
        """
        # Convert date to timestamp format if needed
        data = self._make_request(f"/events/{date}")
        return data.get("events", [])

    # ==================== Tournament Endpoints ====================

    def get_tournament(self, tournament_id: str) -> Optional[dict]:
        """
        Get tournament details.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Tournament data or None if not found
        """
        try:
            data = self._make_request(f"/tournament/{tournament_id}")
            return data.get("tournament", None)
        except TennisAPIError:
            return None

    # ==================== Helper Methods ====================

    def get_player_upcoming_matches(
        self,
        player_id: str,
        days_ahead: int = 14,
    ) -> list[dict]:
        """
        Get upcoming matches for a specific player.

        Since TennisApi1 doesn't have a player-specific upcoming events endpoint,
        we filter live events to find matches involving the player.

        Args:
            player_id: Player identifier
            days_ahead: Number of days to look ahead (not used)

        Returns:
            List of matches for the player (normalized format)
        """
        live_events = self.get_live_events()
        player_matches = []

        for event in live_events:
            home_team = event.get("homeTeam", {})
            away_team = event.get("awayTeam", {})

            home_id = str(home_team.get("id", ""))
            away_id = str(away_team.get("id", ""))

            if player_id in (home_id, away_id):
                normalized = normalize_live_event(event)
                player_matches.append(normalized)

        return player_matches

    def get_matches_for_players(
        self,
        player_ids: list[str],
        tour_player_ids: list[str] = None,
        player_names: list[str] = None,
    ) -> list[dict]:
        """
        Get all live/upcoming matches for a list of followed players.

        Combines:
        1. Live matches from TennisApi1
        2. Scheduled matches from SerpAPI (Google Sports)
        3. Scheduled matches from tour scraper (daily schedule + draws) as fallback
        4. Scheduled/live matches from the Live Tennis API (only when
           LIVETENNIS_API_KEY is set; skipped entirely otherwise)

        Args:
            player_ids: List of TennisApi1 player IDs to check for live matches
            tour_player_ids: List of tour player IDs for scheduled match scraping
            player_names: List of player names for SerpAPI lookups

        Returns:
            List of matches involving any of the players (normalized format)
        """
        matches = []
        seen_match_keys = set()

        # Get live matches from TennisApi1
        try:
            live_events = self.get_live_events()
            player_ids_set = set(player_ids)

            for event in live_events:
                home_team = event.get("homeTeam", {})
                away_team = event.get("awayTeam", {})

                home_id = str(home_team.get("id", ""))
                away_id = str(away_team.get("id", ""))

                if home_id in player_ids_set or away_id in player_ids_set:
                    normalized = normalize_live_event(event)
                    # Track which followed player(s) are in this match
                    normalized["followed_player_ids"] = []
                    if home_id in player_ids_set:
                        normalized["followed_player_ids"].append(home_id)
                    if away_id in player_ids_set:
                        normalized["followed_player_ids"].append(away_id)
                    matches.append(normalized)
                    seen_match_keys.add(normalized.get("event_key"))
        except Exception:
            pass  # Continue even if live events fail

        # Get scheduled matches from SerpAPI (Google Sports)
        if player_names:
            try:
                from services.serpapi_service import get_serpapi_service
                serpapi = get_serpapi_service()

                for player_name in player_names:
                    match = serpapi.get_player_next_match(player_name)
                    if match:
                        event_key = match.get("event_key", "")
                        if event_key and event_key not in seen_match_keys:
                            # Add followed player tracking
                            match["followed_player_ids"] = [player_name]
                            matches.append(match)
                            seen_match_keys.add(event_key)
            except Exception:
                pass  # Continue even if SerpAPI fails

        # Fallback: Get scheduled matches from tour scraper (daily schedule + draws)
        if tour_player_ids:
            try:
                from services.tour_scraper import get_tour_scraper
                scraper = get_tour_scraper()
                # include_draws=True gets future matchups beyond daily schedule
                scheduled_matches = scraper.get_player_matches(
                    tour_player_ids,
                    include_draws=True
                )

                for match in scheduled_matches:
                    # Avoid duplicates (check both orderings of player IDs)
                    event_key = match.get("event_key", "")
                    if event_key and event_key not in seen_match_keys:
                        matches.append(match)
                        seen_match_keys.add(event_key)
            except Exception:
                pass  # Continue even if scraping fails

        # Optional: scheduled/live matches from the Live Tennis API.
        # No key configured means this block does nothing at all.
        if player_names:
            try:
                from services.livetennis_service import (
                    get_livetennis_service,
                    match_signature,
                )
                livetennis = get_livetennis_service()

                if livetennis.is_configured:
                    # Providers use separate ID spaces, so also compare on
                    # date + player pair to avoid a second calendar event for
                    # a match an earlier source already reported.
                    seen_signatures = {match_signature(m) for m in matches}

                    for match in livetennis.get_matches_for_player_names(player_names):
                        event_key = match.get("event_key", "")
                        signature = match_signature(match)

                        if event_key in seen_match_keys or signature in seen_signatures:
                            continue

                        # followed_player_ids carries names here, as it does
                        # for SerpAPI results.
                        match["followed_player_ids"] = match.pop(
                            "followed_player_names", []
                        )
                        matches.append(match)
                        seen_match_keys.add(event_key)
                        seen_signatures.add(signature)
            except Exception:
                pass  # Continue even if the Live Tennis API fails

        return matches

    def get_rate_limit_status(self) -> dict:
        """
        Get current rate limit status.

        Returns:
            Dictionary with remaining requests
        """
        return self.rate_limiter.get_remaining_requests()


def generate_search_terms(player: dict) -> list[str]:
    """
    Generate search terms for a player record.

    Used for Firestore array-contains queries.

    Args:
        player: Player data from API

    Returns:
        List of lowercase search terms
    """
    terms = set()

    # Handle different API response formats
    name = player.get("name", "") or player.get("player_name", "")
    if name:
        terms.add(name.lower())
        parts = name.lower().split()
        terms.update(parts)

    # Add first/last name if available
    first_name = player.get("firstName", "") or player.get("player_first_name", "")
    last_name = player.get("lastName", "") or player.get("player_last_name", "")
    if first_name:
        terms.add(first_name.lower())
    if last_name:
        terms.add(last_name.lower())

    # Add country
    country = player.get("country", {})
    if isinstance(country, dict):
        country_name = country.get("name", "")
    else:
        country_name = player.get("player_country", "")
    if country_name:
        terms.add(country_name.lower())

    return list(terms)


def normalize_player_data(api_player: dict, tour: str) -> dict:
    """
    Normalize player data from API to our schema.

    Args:
        api_player: Raw player data from API (rankings format)
        tour: ATP or WTA

    Returns:
        Normalized player record

    TennisApi1 rankings response format:
    {
        "team": {"name": "Player Name", "shortName": "P. Name", "id": 12345, "country": {...}},
        "ranking": 1,
        "points": 9000,
        "rowName": "Player Name",
        "country": {"alpha2": "US", "name": "USA"}
    }
    """
    # TennisApi1 uses "team" object for player info in rankings
    team_info = api_player.get("team", {}) or {}

    # Get player ID from team object
    player_id = str(team_info.get("id", ""))

    # Get name - prefer team.name, fall back to rowName at root level
    name = team_info.get("name", "") or api_player.get("rowName", "")
    short_name = team_info.get("shortName", "")

    # Country can be in team.country or at root level
    team_country = team_info.get("country", {}) or {}
    root_country = api_player.get("country", {}) or {}
    country_info = team_country if team_country else root_country

    # Parse first/last name from full name if available
    first_name = ""
    last_name = ""
    if name:
        name_parts = name.split()
        if len(name_parts) >= 2:
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:])
        elif len(name_parts) == 1:
            last_name = name_parts[0]

    # Build the normalized record
    normalized = {
        "player_key": player_id,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "country": country_info.get("name", "") if isinstance(country_info, dict) else "",
        "country_code": country_info.get("alpha2", "") if isinstance(country_info, dict) else "",
        "tour": tour,
        "ranking": api_player.get("ranking", None),
        "points": api_player.get("points", None),
        "image_url": "",  # This API may not provide images in rankings
        "last_updated": datetime.utcnow(),
    }

    # Generate search terms using the normalized data
    normalized["search_terms"] = generate_search_terms(normalized)

    return normalized


def normalize_live_event(event: dict) -> dict:
    """
    Normalize a live event from TennisApi1 to our match schema.

    TennisApi1 live event format:
    {
        "id": 15373171,
        "homeTeam": {"name": "Player A", "id": 123, "country": {...}},
        "awayTeam": {"name": "Player B", "id": 456, "country": {...}},
        "tournament": {"name": "Australian Open, Melbourne, Australia"},
        "uniqueTournament": {"name": "Australian Open"},
        "roundInfo": {"name": "Round of 128", "round": 64},
        "startTimestamp": 1768694400,
        "status": {"description": "1st set", "type": "inprogress"},
        "groundType": "Hardcourt outdoor"
    }

    Returns:
        Normalized match record compatible with event_builder
    """
    home_team = event.get("homeTeam", {})
    away_team = event.get("awayTeam", {})
    tournament = event.get("uniqueTournament", {}) or event.get("tournament", {})
    round_info = event.get("roundInfo", {})
    status = event.get("status", {})

    # Convert Unix timestamp to datetime string
    start_timestamp = event.get("startTimestamp", 0)
    if start_timestamp:
        start_dt = datetime.utcfromtimestamp(start_timestamp)
        event_date = start_dt.strftime("%Y-%m-%d")
        event_time = start_dt.strftime("%H:%M")
    else:
        event_date = ""
        event_time = ""

    return {
        "event_key": str(event.get("id", "")),
        "event_home_player": home_team.get("name", "TBD"),
        "event_away_player": away_team.get("name", "TBD"),
        "home_player_id": str(home_team.get("id", "")),
        "away_player_id": str(away_team.get("id", "")),
        "tournament_name": tournament.get("name", "Tennis Match"),
        "event_round": round_info.get("name", ""),
        "event_date": event_date,
        "event_time": event_time,
        "start_timestamp": start_timestamp,
        "event_status": status.get("type", "scheduled"),
        "status_description": status.get("description", ""),
        "event_surface": event.get("groundType", ""),
        "event_stadium": "",  # Not typically in live events
    }
