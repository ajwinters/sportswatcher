"""
Tournament configuration for timezone and session times.

Major tournaments have specific session start times. When we don't have
an exact match time from the API, we use these defaults to create more
accurate calendar events.
"""

# Tournament configurations
# Keys are substrings that match tournament names (case-insensitive)
TOURNAMENT_CONFIG = {
    # Grand Slams
    "australian open": {
        "timezone": "Australia/Melbourne",  # AEDT (UTC+11 in January)
        "day_session_start": "11:00",       # 11 AM local
        "night_session_start": "19:00",     # 7 PM local
        "default_session": "day",           # Most matches are day session
    },
    "french open": {
        "timezone": "Europe/Paris",         # CEST (UTC+2 in May-June)
        "day_session_start": "11:00",
        "night_session_start": "20:00",
        "default_session": "day",
    },
    "roland garros": {  # Alternate name for French Open
        "timezone": "Europe/Paris",
        "day_session_start": "11:00",
        "night_session_start": "20:00",
        "default_session": "day",
    },
    "wimbledon": {
        "timezone": "Europe/London",        # BST (UTC+1 in July)
        "day_session_start": "11:00",
        "night_session_start": None,        # No night sessions at Wimbledon
        "default_session": "day",
    },
    "us open": {
        "timezone": "America/New_York",     # EDT (UTC-4 in Aug-Sep)
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    # ATP Masters 1000
    "indian wells": {
        "timezone": "America/Los_Angeles",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "miami open": {
        "timezone": "America/New_York",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "monte carlo": {
        "timezone": "Europe/Monaco",
        "day_session_start": "11:00",
        "night_session_start": None,
        "default_session": "day",
    },
    "madrid open": {
        "timezone": "Europe/Madrid",
        "day_session_start": "12:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "italian open": {
        "timezone": "Europe/Rome",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "rome": {  # Alternate name
        "timezone": "Europe/Rome",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "canadian open": {
        "timezone": "America/Toronto",
        "day_session_start": "12:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "cincinnati": {
        "timezone": "America/New_York",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    "shanghai": {
        "timezone": "Asia/Shanghai",
        "day_session_start": "12:00",
        "night_session_start": "18:00",
        "default_session": "day",
    },
    "paris masters": {
        "timezone": "Europe/Paris",
        "day_session_start": "11:00",
        "night_session_start": "19:00",
        "default_session": "day",
    },
    # ATP Finals
    "atp finals": {
        "timezone": "Europe/Turin",
        "day_session_start": "11:30",
        "night_session_start": "18:00",
        "default_session": "day",
    },
    "nitto atp finals": {
        "timezone": "Europe/Turin",
        "day_session_start": "11:30",
        "night_session_start": "18:00",
        "default_session": "day",
    },
}

# Default configuration for unknown tournaments
DEFAULT_CONFIG = {
    "timezone": "UTC",
    "day_session_start": "12:00",      # Noon UTC as fallback
    "night_session_start": "19:00",
    "default_session": "day",
}


def get_tournament_config(tournament_name: str) -> dict:
    """
    Get configuration for a tournament.

    Args:
        tournament_name: Name of the tournament (e.g., "Australian Open 2026")

    Returns:
        Tournament config dict with timezone and session times
    """
    if not tournament_name:
        return DEFAULT_CONFIG

    tournament_lower = tournament_name.lower()

    for key, config in TOURNAMENT_CONFIG.items():
        if key in tournament_lower:
            return config

    return DEFAULT_CONFIG


def get_default_match_time(tournament_name: str, session: str = None) -> tuple[str, str]:
    """
    Get the default match time for a tournament.

    Args:
        tournament_name: Name of the tournament
        session: "day" or "night" (optional, uses tournament default)

    Returns:
        Tuple of (time_string, timezone_string)
        e.g., ("11:00", "Australia/Melbourne")
    """
    config = get_tournament_config(tournament_name)

    session = session or config.get("default_session", "day")

    if session == "night" and config.get("night_session_start"):
        time_str = config["night_session_start"]
    else:
        time_str = config["day_session_start"]

    return time_str, config["timezone"]
