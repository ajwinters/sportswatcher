"""
Tennis Tour scraper for ATP and WTA match schedules.

Combines:
- ATP Tour website scraping for daily schedules
- WTA API for player data
- Draw parsing for upcoming matchups
"""

import re
from datetime import datetime, timedelta
from typing import Optional
import requests
from bs4 import BeautifulSoup


class TourScraperError(Exception):
    """Raised when scraping fails."""
    pass


class TourScraper:
    """
    Unified scraper for ATP and WTA Tour match schedules.

    Extracts scheduled matches from daily schedules and tournament draws.
    """

    ATP_BASE_URL = "https://www.atptour.com"
    WTA_API_URL = "https://api.wtatennis.com/tennis"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # Tournament IDs for major events (shared by ATP/WTA for Grand Slams)
    ATP_TOURNAMENTS = {
        "australian-open": 580,
        "french-open": 520,
        "wimbledon": 540,
        "us-open": 560,
    }

    # WTA tournament group IDs
    WTA_TOURNAMENTS = {
        "australian-open": 901,
        "french-open": 903,
        "wimbledon": 904,
        "us-open": 905,
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    # ==================== ATP Methods ====================

    def get_atp_daily_schedule(self, tournament_slug: str = "australian-open") -> list[dict]:
        """Get today's scheduled ATP matches from a tournament."""
        tournament_id = self.ATP_TOURNAMENTS.get(tournament_slug, 580)
        url = f"{self.ATP_BASE_URL}/en/scores/current/{tournament_slug}/{tournament_id}/daily-schedule"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            raise TourScraperError(f"Failed to fetch ATP schedule: {e}") from e

        return self._parse_atp_schedule(response.text, tournament_slug)

    def get_atp_draws(self, tournament_slug: str = "australian-open") -> list[dict]:
        """
        Get all matchups from ATP tournament draws.

        Returns future matches without exact times (TBD).
        """
        tournament_id = self.ATP_TOURNAMENTS.get(tournament_slug, 580)
        url = f"{self.ATP_BASE_URL}/en/scores/current/{tournament_slug}/{tournament_id}/draws"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            raise TourScraperError(f"Failed to fetch ATP draws: {e}") from e

        return self._parse_atp_draws(response.text, tournament_slug)

    def _parse_atp_schedule(self, html: str, tournament_name: str) -> list[dict]:
        """Parse ATP daily schedule HTML."""
        matches = []

        # Pattern to find player links and data
        player_pattern = r'<a href="/en/players/([^/]+)/([^/]+)/overview">\s*<span>([^<]+)</span>\s*([^<]+)</a>'
        datetime_pattern = r'data-datetime="(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"'

        datetimes = re.findall(datetime_pattern, html)
        players = re.findall(player_pattern, html)

        player_buffer = []

        for i, (player_slug, player_id, initial, last_name) in enumerate(players):
            player_name = f"{initial.strip()} {last_name.strip()}"

            player_buffer.append({
                "name": player_name,
                "slug": player_slug,
                "player_id": player_id,
            })

            if len(player_buffer) == 2:
                match_datetime = datetimes[min(i // 2, len(datetimes) - 1)] if datetimes else None

                match = {
                    "event_key": f"{player_buffer[0]['player_id']}-{player_buffer[1]['player_id']}",
                    "event_home_player": player_buffer[0]["name"],
                    "event_away_player": player_buffer[1]["name"],
                    "home_player_id": player_buffer[0]["player_id"],
                    "away_player_id": player_buffer[1]["player_id"],
                    "tournament_name": self._format_tournament_name(tournament_name),
                    "event_round": "Singles",
                    "event_date": "",
                    "event_time": "",
                    "start_timestamp": 0,
                    "event_status": "scheduled",
                    "event_surface": "Hardcourt",
                    "event_stadium": "",
                    "tour": "ATP",
                }

                if match_datetime:
                    try:
                        dt = datetime.strptime(match_datetime, "%Y-%m-%d %H:%M:%S")
                        match["event_date"] = dt.strftime("%Y-%m-%d")
                        match["event_time"] = dt.strftime("%H:%M")
                        match["start_timestamp"] = int(dt.timestamp())
                    except ValueError:
                        pass

                matches.append(match)
                player_buffer = []

        return matches

    def _parse_atp_draws(self, html: str, tournament_name: str) -> list[dict]:
        """
        Parse ATP draws page to extract all matchups.

        Returns matches without specific times (for future rounds).
        """
        matches = []
        soup = BeautifulSoup(html, "html.parser")

        # Find all player name divs in the draw
        name_divs = soup.find_all("div", class_="name")

        # Extract player info from links
        players = []
        for div in name_divs:
            link = div.find("a", href=re.compile(r"/en/players/"))
            if link:
                href = link.get("href", "")
                parts = href.split("/")
                if len(parts) >= 3:
                    player_id = parts[-2]
                    player_name = link.get_text(strip=True)
                    # Remove seed numbers like "(1)" from name
                    player_name = re.sub(r'\s*\(\d+\)\s*$', '', player_name)
                    player_name = re.sub(r'\s*\([QW]C?\)\s*$', '', player_name)  # Remove (Q), (WC)
                    players.append({
                        "name": player_name.strip(),
                        "player_id": player_id,
                    })

        # Group into pairs (first round matchups)
        # In a draw, players are listed in pairs
        for i in range(0, len(players) - 1, 2):
            if i + 1 < len(players):
                p1 = players[i]
                p2 = players[i + 1]

                match = {
                    "event_key": f"draw-{p1['player_id']}-{p2['player_id']}",
                    "event_home_player": p1["name"],
                    "event_away_player": p2["name"],
                    "home_player_id": p1["player_id"],
                    "away_player_id": p2["player_id"],
                    "tournament_name": self._format_tournament_name(tournament_name),
                    "event_round": "Round 1",
                    "event_date": "",  # TBD - will be determined by daily schedule
                    "event_time": "",
                    "start_timestamp": 0,
                    "event_status": "scheduled",
                    "event_surface": "Hardcourt",
                    "event_stadium": "",
                    "tour": "ATP",
                    "from_draw": True,  # Mark that this is from draws, not daily schedule
                }

                matches.append(match)

        return matches

    def search_atp_player(self, name: str) -> list[dict]:
        """Search for an ATP player by name."""
        url = f"{self.ATP_BASE_URL}/en/-/ajax/playersearch/PlayerUrlSearch"
        params = {"searchTerm": name}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            players = []
            for item in data.get("items", []):
                url_parts = item.get("Value", "").split("/")
                if len(url_parts) >= 2:
                    players.append({
                        "name": item.get("Key", ""),
                        "player_id": url_parts[-2],
                        "slug": url_parts[-3] if len(url_parts) >= 3 else "",
                        "tour": "ATP",
                    })

            return players

        except requests.RequestException:
            return []

    # ==================== WTA Methods ====================

    def search_wta_player(self, name: str) -> list[dict]:
        """Search for a WTA player by name using the WTA API."""
        url = f"{self.WTA_API_URL}/players"
        params = {"name": name, "pageSize": 10}

        try:
            response = self.session.get(url, params=params, timeout=10, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()

            players = []
            for item in data.get("content", []):
                if item.get("fullName"):
                    players.append({
                        "name": item.get("fullName", ""),
                        "player_id": str(item.get("id", "")),
                        "first_name": item.get("firstName", ""),
                        "last_name": item.get("lastName", ""),
                        "country": item.get("countryCode", ""),
                        "tour": "WTA",
                    })

            return players

        except requests.RequestException:
            return []

    def get_wta_player_info(self, player_id: str) -> Optional[dict]:
        """Get WTA player details by ID."""
        url = f"{self.WTA_API_URL}/players/{player_id}"

        try:
            response = self.session.get(url, timeout=10, headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return None

    # ==================== Combined Methods ====================

    def search_player(self, name: str, tour: Optional[str] = None) -> list[dict]:
        """
        Search for a player by name across both tours.

        Args:
            name: Player name to search
            tour: Optional tour filter ("ATP" or "WTA")

        Returns:
            List of matching players with tour info
        """
        results = []

        if tour is None or tour.upper() == "ATP":
            results.extend(self.search_atp_player(name))

        if tour is None or tour.upper() == "WTA":
            results.extend(self.search_wta_player(name))

        return results

    def get_all_matches(
        self,
        tournament_slug: str = "australian-open",
        include_draws: bool = True,
    ) -> list[dict]:
        """
        Get all matches from daily schedule and optionally draws.

        For Grand Slams, this gets ATP matches. WTA matches would need
        separate tournament handling.

        Args:
            tournament_slug: Tournament identifier
            include_draws: Whether to include draw matchups

        Returns:
            List of all matches (scheduled first, then draw matches)
        """
        matches = []
        seen_keys = set()

        # Get daily schedule (has exact times)
        try:
            daily_matches = self.get_atp_daily_schedule(tournament_slug)
            for match in daily_matches:
                key = match.get("event_key")
                if key and key not in seen_keys:
                    matches.append(match)
                    seen_keys.add(key)
        except TourScraperError:
            pass

        # Get draws (future matches without times)
        if include_draws:
            try:
                draw_matches = self.get_atp_draws(tournament_slug)
                for match in draw_matches:
                    # Create a normalized key for deduplication
                    home_id = match.get("home_player_id", "")
                    away_id = match.get("away_player_id", "")
                    normalized_key = f"{home_id}-{away_id}"
                    alt_key = f"{away_id}-{home_id}"

                    # Don't add if already in daily schedule
                    if normalized_key not in seen_keys and alt_key not in seen_keys:
                        matches.append(match)
                        seen_keys.add(normalized_key)
            except TourScraperError:
                pass

        return matches

    def get_player_matches(
        self,
        player_ids: list[str],
        tournament_slug: str = "australian-open",
        include_draws: bool = True,
    ) -> list[dict]:
        """
        Get matches for specific players.

        Args:
            player_ids: List of player IDs (ATP format like 's0ag')
            tournament_slug: Tournament to search
            include_draws: Whether to include draw matchups

        Returns:
            List of matches involving any of the specified players
        """
        all_matches = self.get_all_matches(tournament_slug, include_draws)
        player_ids_set = set(player_ids)
        player_ids_lower = {pid.lower() for pid in player_ids}

        matching_matches = []
        for match in all_matches:
            home_id = match.get("home_player_id", "").lower()
            away_id = match.get("away_player_id", "").lower()

            if home_id in player_ids_lower or away_id in player_ids_lower:
                match["followed_player_ids"] = []
                if home_id in player_ids_lower:
                    match["followed_player_ids"].append(match.get("home_player_id"))
                if away_id in player_ids_lower:
                    match["followed_player_ids"].append(match.get("away_player_id"))
                matching_matches.append(match)

        return matching_matches

    def _format_tournament_name(self, slug: str) -> str:
        """Convert tournament slug to display name."""
        return slug.replace("-", " ").title()


# Singleton instance
_scraper_instance = None


def get_tour_scraper() -> TourScraper:
    """Get a singleton Tour scraper instance."""
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = TourScraper()
    return _scraper_instance


# Backwards compatibility with existing code
def get_atp_scraper() -> TourScraper:
    """Backwards compatible alias for get_tour_scraper."""
    return get_tour_scraper()
