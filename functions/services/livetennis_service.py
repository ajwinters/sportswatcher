"""
Live Tennis API service for fetching scheduled and live match data.

Optional additional source. When LIVETENNIS_API_KEY is not set the service is
inert and get_matches_for_player_names() returns an empty list, so the existing
TennisApi1 / SerpAPI / tour-scraper sources are unaffected.

Docs: https://github.com/livetennisapi/openapi
"""

import unicodedata
from datetime import datetime, timezone
from typing import Optional
import requests

from config.settings import get_settings


class LiveTennisAPIError(Exception):
    """Raised when the Live Tennis API returns an error."""
    pass


# Match.status (upcoming/live/completed/cancelled) -> the status vocabulary
# already used by normalize_live_event() and is_match_relevant().
_STATUS_MAP = {
    "upcoming": "notstarted",
    "live": "inprogress",
    "completed": "finished",
    "cancelled": "cancelled",
}


def _normalize_name(name: str) -> str:
    """
    Fold a player name for comparison.

    Lowercases, strips accents and collapses whitespace so that
    "Stefanos Tsitsipas" and "Stefanos Tsitsipás" compare equal.
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def match_signature(match: dict) -> tuple:
    """
    Build a provider-independent identity for a normalized match.

    Two sources describe the same match with different IDs, so identity is the
    date plus the unordered pair of players. Used to avoid creating a second
    calendar event for a match another source already reported.

    Args:
        match: Match in the normalized schema

    Returns:
        Hashable signature
    """
    players = frozenset({
        _normalize_name(match.get("event_home_player", "")),
        _normalize_name(match.get("event_away_player", "")),
    })
    return (match.get("event_date", ""), players)


class LiveTennisAPIService:
    """
    Client for the Live Tennis API (https://api.livetennisapi.com).

    Followed players are resolved to Live Tennis player IDs once via
    /players?search=, then matches are selected by ID rather than by name.
    An unresolved name is skipped rather than guessed, so a player we cannot
    identify with certainty never produces a calendar event.
    """

    BASE_URL = "https://api.livetennisapi.com/api/public/v1"

    # /matches is paged (limit max 200). Cap the walk so a bad page cursor can
    # never turn one sync into an unbounded crawl.
    PAGE_SIZE = 200
    MAX_PAGES = 5

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.livetennis_api_key
        self._player_id_cache: dict[str, Optional[int]] = {}

    @property
    def is_configured(self) -> bool:
        """True when an API key is present. False means "skip this source"."""
        return bool(self.api_key)

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """
        Make an authenticated request.

        Args:
            endpoint: Path below the API root (e.g. '/matches')
            params: Query parameters

        Returns:
            Decoded JSON response

        Raises:
            LiveTennisAPIError: If the request fails
        """
        if not self.api_key:
            raise LiveTennisAPIError("LIVETENNIS_API_KEY not configured")

        try:
            response = requests.get(
                f"{self.BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise LiveTennisAPIError(f"Request failed: {e}") from e

    # ==================== Player resolution ====================

    def resolve_player_id(self, player_name: str) -> Optional[int]:
        """
        Resolve a player name to a Live Tennis player ID.

        Only an exact (accent- and case-insensitive) name match counts. A
        near-miss returns None so we never attach a match to the wrong player.

        Args:
            player_name: Full player name (e.g. "Jannik Sinner")

        Returns:
            Player ID, or None if the name could not be resolved
        """
        wanted = _normalize_name(player_name)
        if not wanted:
            return None
        if wanted in self._player_id_cache:
            return self._player_id_cache[wanted]

        resolved = None
        try:
            data = self._make_request("/players", {"search": player_name, "limit": 50})
            for player in data.get("data", []):
                if _normalize_name(player.get("name", "")) == wanted:
                    resolved = player.get("id")
                    break
        except LiveTennisAPIError:
            # Leave the name unresolved for this run; do not cache a failure
            # caused by a transient error.
            return None

        self._player_id_cache[wanted] = resolved
        return resolved

    # ==================== Match retrieval ====================

    def _iter_matches(self, status: str) -> list[dict]:
        """
        Page through /matches for one lifecycle status.

        Args:
            status: "upcoming" or "live"

        Returns:
            List of raw match objects
        """
        collected = []
        offset = 0

        for _ in range(self.MAX_PAGES):
            data = self._make_request(
                "/matches",
                {"status": status, "limit": self.PAGE_SIZE, "offset": offset},
            )
            page = data.get("data", [])
            collected.extend(page)

            meta = data.get("meta", {}) or {}
            if not meta.get("has_more") or not page:
                break
            offset += len(page)

        return collected

    def get_matches_for_player_names(self, player_names: list[str]) -> list[dict]:
        """
        Get upcoming and live matches involving any of the given players.

        Args:
            player_names: Full names of the followed players

        Returns:
            List of matches in the normalized schema used by event_builder.
            Each carries "followed_player_names" naming the players matched.
        """
        if not self.is_configured or not player_names:
            return []

        # Resolve names to IDs, keeping the caller's spelling for attribution.
        ids_to_names: dict[int, str] = {}
        for name in player_names:
            player_id = self.resolve_player_id(name)
            if player_id is not None:
                ids_to_names[player_id] = name

        if not ids_to_names:
            return []

        matches = []
        for status in ("upcoming", "live"):
            try:
                raw_matches = self._iter_matches(status)
            except LiveTennisAPIError:
                continue

            for raw in raw_matches:
                players = raw.get("players", {}) or {}
                p1_id = (players.get("p1") or {}).get("id")
                p2_id = (players.get("p2") or {}).get("id")

                followed = [
                    ids_to_names[pid]
                    for pid in (p1_id, p2_id)
                    if pid in ids_to_names
                ]
                if not followed:
                    continue

                normalized = normalize_livetennis_match(raw)
                normalized["followed_player_names"] = followed
                matches.append(normalized)

        return matches


def normalize_livetennis_match(match: dict) -> dict:
    """
    Normalize a Live Tennis API match into the schema event_builder expects.

    Fields the API does not carry (venue) are left empty rather than guessed.

    Live Tennis API match format:
    {
        "id": 123456,
        "tournament": "Australian Open",
        "surface": "hard",
        "indoor": false,
        "round": "Round of 32",
        "status": "upcoming",
        "scheduled_time": "2026-01-20T09:00:00Z",
        "players": {"p1": {"id": 11, "name": "Player A"},
                    "p2": {"id": 22, "name": "Player B"}}
    }

    Args:
        match: Raw match object from /matches

    Returns:
        Normalized match record
    """
    players = match.get("players", {}) or {}
    p1 = players.get("p1") or {}
    p2 = players.get("p2") or {}

    event_date, event_time, start_timestamp = _split_scheduled_time(
        match.get("scheduled_time")
    )

    return {
        # Namespaced like the other sources ("serp-", "draw-") so IDs from
        # different providers can never collide in the dedupe set.
        "event_key": f"ltapi-{match.get('id', '')}",
        "event_home_player": p1.get("name", "TBD"),
        "event_away_player": p2.get("name", "TBD"),
        "home_player_id": str(p1.get("id", "")),
        "away_player_id": str(p2.get("id", "")),
        "tournament_name": match.get("tournament") or "Tennis Match",
        "event_round": match.get("round") or "",
        "event_date": event_date,
        "event_time": event_time,
        "start_timestamp": start_timestamp,
        "event_status": _STATUS_MAP.get(match.get("status", ""), "scheduled"),
        "status_description": match.get("event_status") or "",
        "event_surface": _format_surface(match.get("surface"), match.get("indoor")),
        "event_stadium": "",  # Not carried by this API
    }


def _split_scheduled_time(scheduled_time: Optional[str]) -> tuple[str, str, int]:
    """
    Split an ISO-8601 scheduled time into date, time and epoch seconds (UTC).

    Args:
        scheduled_time: ISO-8601 timestamp, or None for an unscheduled match

    Returns:
        Tuple of (YYYY-MM-DD, HH:MM, epoch seconds). Empty/0 when unknown.
    """
    if not scheduled_time:
        return "", "", 0

    try:
        dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
    except ValueError:
        return "", "", 0

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)

    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), int(dt.timestamp())


def _format_surface(surface: Optional[str], indoor: Optional[bool]) -> str:
    """
    Render surface for display, e.g. "Hard indoor".

    Args:
        surface: "hard", "clay", "grass" or None
        indoor: Whether the court is indoor

    Returns:
        Display string, empty when the surface is unknown
    """
    if not surface:
        return ""
    if indoor is None:
        return surface.capitalize()
    return f"{surface.capitalize()} {'indoor' if indoor else 'outdoor'}"


# Singleton instance
_livetennis_instance = None


def get_livetennis_service() -> LiveTennisAPIService:
    """Get a singleton Live Tennis API service instance."""
    global _livetennis_instance
    if _livetennis_instance is None:
        _livetennis_instance = LiveTennisAPIService()
    return _livetennis_instance
