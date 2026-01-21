"""
SerpAPI service for fetching tennis match data from Google Sports.

Uses SerpAPI to scrape Google search results which include sports fixtures.
Free tier: 250 searches/month.
"""

import re
from datetime import datetime, timedelta
from typing import Optional
import requests

from config.settings import get_settings
from config.tournaments import get_tournament_config, get_default_match_time


class SerpAPIError(Exception):
    """Raised when SerpAPI returns an error."""
    pass


class SerpAPIService:
    """
    Service for fetching tennis match schedules from Google Sports via SerpAPI.

    Google Sports shows upcoming matches when you search for a player's name.
    SerpAPI can scrape these results including the sports_results section.
    """

    BASE_URL = "https://serpapi.com/search"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.serpapi_key

    def _make_request(self, query: str) -> dict:
        """
        Make a SerpAPI request.

        Args:
            query: Search query

        Returns:
            JSON response from SerpAPI

        Raises:
            SerpAPIError: If the request fails
        """
        if not self.api_key:
            raise SerpAPIError("SERPAPI_KEY not configured")

        params = {
            "q": query,
            "api_key": self.api_key,
            "engine": "google",
            "hl": "en",
            "gl": "us",
        }

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise SerpAPIError(f"Request failed: {e}") from e

    def get_player_next_match(self, player_name: str) -> Optional[dict]:
        """
        Get a player's next scheduled match from Google Sports.

        Args:
            player_name: Full player name (e.g., "Jannik Sinner")

        Returns:
            Match data or None if no upcoming match found
        """
        query = f"{player_name} tennis next match"
        data = self._make_request(query)

        # Check for sports_results in the response
        sports_results = data.get("sports_results", {})

        if sports_results:
            return self._parse_sports_results(sports_results, player_name)

        # Try knowledge graph as fallback
        knowledge_graph = data.get("knowledge_graph", {})
        if knowledge_graph:
            return self._parse_knowledge_graph(knowledge_graph, player_name)

        return None

    def get_player_schedule(self, player_name: str) -> list[dict]:
        """
        Get a player's upcoming match schedule.

        Args:
            player_name: Full player name

        Returns:
            List of upcoming matches
        """
        query = f"{player_name} tennis schedule"
        data = self._make_request(query)

        matches = []

        # Check sports_results
        sports_results = data.get("sports_results", {})
        if sports_results:
            match = self._parse_sports_results(sports_results, player_name)
            if match:
                matches.append(match)

        # Check for games/fixtures in sports_results
        games = sports_results.get("games", []) or sports_results.get("fixtures", [])
        for game in games:
            match = self._parse_game_fixture(game, player_name)
            if match:
                matches.append(match)

        return matches

    def get_tournament_schedule(self, tournament_name: str) -> list[dict]:
        """
        Get scheduled matches for a tournament.

        Args:
            tournament_name: Tournament name (e.g., "Australian Open")

        Returns:
            List of scheduled matches
        """
        query = f"{tournament_name} tennis schedule"
        data = self._make_request(query)

        matches = []

        # Check sports_results for games
        sports_results = data.get("sports_results", {})
        games = sports_results.get("games", []) or []

        for game in games:
            match = self._parse_game_fixture(game)
            if match:
                matches.append(match)

        return matches

    def _parse_sports_results(self, sports_results: dict, player_name: str) -> Optional[dict]:
        """
        Parse Google sports_results into our match format.

        The sports_results structure varies but typically includes:
        - game_spotlight: Current/next match details
        - games: List of upcoming games
        - tables: Tournament tables with games
        """
        # Check for game_spotlight (single featured match)
        spotlight = sports_results.get("game_spotlight", {})
        if spotlight:
            return self._parse_spotlight(spotlight, player_name)

        # Check for tables structure (tournament schedule format)
        tables = sports_results.get("tables", {})
        if tables:
            tournament_name = tables.get("title", "")
            games = tables.get("games", [])
            for game in games:
                match = self._parse_table_game(game, player_name, tournament_name)
                if match:
                    return match

        # Check for games array
        games = sports_results.get("games", [])
        if games:
            # Find the next upcoming game
            for game in games:
                match = self._parse_game_fixture(game, player_name)
                if match and match.get("event_status") == "scheduled":
                    return match

        return None

    def _parse_table_game(self, game: dict, player_name: str, tournament_name: str) -> Optional[dict]:
        """
        Parse a game from the tables structure.

        Format:
        {
            "date": "Mon, Jan 19",
            "stage": "First round",
            "location": "2",
            "players": [
                {"name": "H. Gaston", "thumbnail": "..."},
                {"name": "J. Sinner", "ranking": "2", "thumbnail": "..."}
            ]
        }
        """
        players = game.get("players", [])
        if len(players) < 2:
            return None

        player1 = players[0].get("name", "")
        player2 = players[1].get("name", "")

        # Parse date
        date_str = game.get("date", "")
        event_date, event_time, timestamp = self._parse_datetime(date_str, "")

        # If no specific time, use tournament default session time
        tournament_config = get_tournament_config(tournament_name)
        timezone = tournament_config.get("timezone", "UTC")

        if not event_time:
            default_time, _ = get_default_match_time(tournament_name)
            event_time = default_time

        # Stage/round
        stage = game.get("stage", "")

        # Location might be court number
        court = game.get("location", "")
        stadium = f"Court {court}" if court and court.isdigit() else court

        return {
            "event_key": f"serp-{player1.lower().replace(' ', '-').replace('.', '')}-{player2.lower().replace(' ', '-').replace('.', '')}-{event_date}",
            "event_home_player": player1,
            "event_away_player": player2,
            "home_player_id": "",
            "away_player_id": "",
            "tournament_name": tournament_name,
            "event_round": stage,
            "event_date": event_date,
            "event_time": event_time,
            "event_timezone": timezone,
            "start_timestamp": timestamp,
            "event_status": "scheduled",
            "event_surface": "",
            "event_stadium": stadium,
            "source": "serpapi",
        }

    def _parse_spotlight(self, spotlight: dict, player_name: str) -> Optional[dict]:
        """Parse a game_spotlight into match format."""
        teams = spotlight.get("teams", [])
        if len(teams) < 2:
            return None

        # Find opponent
        home_team = teams[0] if teams else {}
        away_team = teams[1] if len(teams) > 1 else {}

        # Determine which is the followed player
        home_name = home_team.get("name", "")
        away_name = away_team.get("name", "")

        # Parse date/time
        date_str = spotlight.get("date", "")
        time_str = spotlight.get("time", "")
        event_date, event_time, timestamp = self._parse_datetime(date_str, time_str)

        # Get status
        status = spotlight.get("status", "")
        event_status = self._normalize_status(status)

        # Tournament info
        league = spotlight.get("league", "") or spotlight.get("tournament", "")
        venue = spotlight.get("venue", "") or spotlight.get("stadium", "")

        # Get tournament timezone and default time if needed
        tournament_config = get_tournament_config(league)
        timezone = tournament_config.get("timezone", "UTC")

        if not event_time:
            default_time, _ = get_default_match_time(league)
            event_time = default_time

        return {
            "event_key": f"serp-{home_name.lower().replace(' ', '-')}-{away_name.lower().replace(' ', '-')}",
            "event_home_player": home_name,
            "event_away_player": away_name,
            "home_player_id": "",
            "away_player_id": "",
            "tournament_name": league,
            "event_round": "",
            "event_date": event_date,
            "event_time": event_time,
            "event_timezone": timezone,
            "start_timestamp": timestamp,
            "event_status": event_status,
            "event_surface": "",
            "event_stadium": venue,
            "source": "serpapi",
        }

    def _parse_game_fixture(self, game: dict, player_name: str = None) -> Optional[dict]:
        """Parse a game fixture from games array."""
        teams = game.get("teams", [])
        if len(teams) < 2:
            # Try alternate format
            home = game.get("home_team", {}) or game.get("team1", {})
            away = game.get("away_team", {}) or game.get("team2", {})
            if home and away:
                teams = [home, away]
            else:
                return None

        home_team = teams[0] if isinstance(teams[0], dict) else {"name": teams[0]}
        away_team = teams[1] if isinstance(teams[1], dict) else {"name": teams[1]}

        home_name = home_team.get("name", str(home_team))
        away_name = away_team.get("name", str(away_team))

        # Parse date/time
        date_str = game.get("date", "") or game.get("start_date", "")
        time_str = game.get("time", "") or game.get("start_time", "")
        event_date, event_time, timestamp = self._parse_datetime(date_str, time_str)

        # Get status
        status = game.get("status", "") or game.get("game_status", "")
        event_status = self._normalize_status(status)

        # Tournament/venue
        tournament = game.get("tournament", "") or game.get("league", "") or game.get("competition", "")
        venue = game.get("venue", "") or game.get("stadium", "")

        # Get tournament timezone and default time if needed
        tournament_config = get_tournament_config(tournament)
        timezone = tournament_config.get("timezone", "UTC")

        if not event_time:
            default_time, _ = get_default_match_time(tournament)
            event_time = default_time

        return {
            "event_key": f"serp-{home_name.lower().replace(' ', '-')}-{away_name.lower().replace(' ', '-')}-{event_date}",
            "event_home_player": home_name,
            "event_away_player": away_name,
            "home_player_id": "",
            "away_player_id": "",
            "tournament_name": tournament,
            "event_round": game.get("round", ""),
            "event_date": event_date,
            "event_time": event_time,
            "event_timezone": timezone,
            "start_timestamp": timestamp,
            "event_status": event_status,
            "event_surface": "",
            "event_stadium": venue,
            "source": "serpapi",
        }

    def _parse_knowledge_graph(self, kg: dict, player_name: str) -> Optional[dict]:
        """
        Try to extract match info from knowledge graph.

        Knowledge graph sometimes shows next match info for athletes.
        """
        # Look for next match info in various places
        next_match = kg.get("next_match", {})
        if next_match:
            opponent = next_match.get("opponent", "")
            date_str = next_match.get("date", "")
            tournament = next_match.get("tournament", "")

            event_date, event_time, timestamp = self._parse_datetime(date_str, "")

            return {
                "event_key": f"serp-kg-{player_name.lower().replace(' ', '-')}-{opponent.lower().replace(' ', '-')}",
                "event_home_player": player_name,
                "event_away_player": opponent,
                "home_player_id": "",
                "away_player_id": "",
                "tournament_name": tournament,
                "event_round": "",
                "event_date": event_date,
                "event_time": event_time,
                "start_timestamp": timestamp,
                "event_status": "scheduled",
                "event_surface": "",
                "event_stadium": "",
                "source": "serpapi",
            }

        return None

    def _parse_datetime(self, date_str: str, time_str: str) -> tuple[str, str, int]:
        """
        Parse date and time strings into standardized format.

        Handles various formats like:
        - "Jan 20, 2025"
        - "Tomorrow"
        - "Today at 3:00 PM"
        - "Monday, January 20"

        Returns:
            Tuple of (event_date, event_time, timestamp)
        """
        if not date_str:
            return "", "", 0

        now = datetime.utcnow()
        event_date = ""
        event_time = ""
        timestamp = 0

        # Handle relative dates
        date_lower = date_str.lower()
        if "today" in date_lower:
            event_date = now.strftime("%Y-%m-%d")
        elif "tomorrow" in date_lower:
            tomorrow = now + timedelta(days=1)
            event_date = tomorrow.strftime("%Y-%m-%d")
        else:
            # Try parsing various date formats
            date_formats = [
                "%b %d, %Y",   # Jan 20, 2025
                "%B %d, %Y",   # January 20, 2025
                "%Y-%m-%d",    # 2025-01-20
                "%m/%d/%Y",    # 01/20/2025
                "%d %b %Y",    # 20 Jan 2025
                "%A, %B %d",   # Monday, January 20
                "%a, %b %d",   # Mon, Jan 19
                "%A, %b %d",   # Monday, Jan 19
            ]

            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(date_str.strip(), fmt)
                    # If no year in format, assume current year
                    if "%Y" not in fmt:
                        parsed = parsed.replace(year=now.year)
                        # If date is in the past, assume next year
                        if parsed < now:
                            parsed = parsed.replace(year=now.year + 1)
                    event_date = parsed.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

        # Parse time
        if time_str:
            # Try parsing various time formats
            time_formats = [
                "%I:%M %p",   # 3:00 PM
                "%H:%M",      # 15:00
                "%I %p",      # 3 PM
            ]

            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(time_str.strip(), fmt)
                    event_time = parsed_time.strftime("%H:%M")
                    break
                except ValueError:
                    continue

        # Also check for time in date string (e.g., "Today at 3:00 PM")
        if not event_time and " at " in date_str.lower():
            time_part = date_str.lower().split(" at ")[-1]
            for fmt in ["%I:%M %p", "%I %p"]:
                try:
                    parsed_time = datetime.strptime(time_part.strip(), fmt)
                    event_time = parsed_time.strftime("%H:%M")
                    break
                except ValueError:
                    continue

        # Calculate timestamp
        if event_date:
            try:
                dt_str = f"{event_date} {event_time or '12:00'}"
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                timestamp = int(dt.timestamp())
            except ValueError:
                pass

        return event_date, event_time, timestamp

    def _normalize_status(self, status: str) -> str:
        """Normalize status string to our format."""
        if not status:
            return "scheduled"

        status_lower = status.lower()
        if any(s in status_lower for s in ["live", "in progress", "playing"]):
            return "inprogress"
        elif any(s in status_lower for s in ["final", "finished", "completed"]):
            return "finished"
        elif any(s in status_lower for s in ["cancelled", "postponed", "suspended"]):
            return "cancelled"
        else:
            return "scheduled"


# Singleton instance
_serpapi_instance = None


def get_serpapi_service() -> SerpAPIService:
    """Get a singleton SerpAPI service instance."""
    global _serpapi_instance
    if _serpapi_instance is None:
        _serpapi_instance = SerpAPIService()
    return _serpapi_instance
