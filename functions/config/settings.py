"""
Application configuration loaded from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Application settings container."""

    # Tennis API (RapidAPI)
    tennis_api_key: str
    tennis_api_host: str = "api-tennis.p.rapidapi.com"
    tennis_api_base_url: str = "https://api-tennis.p.rapidapi.com/"

    # Rate limits for Tennis API free tier
    tennis_api_requests_per_minute: int = 10
    tennis_api_requests_per_day: int = 100

    # SerpAPI for Google Sports data
    serpapi_key: str = ""

    # Live Tennis API (optional additional match source; leave empty to disable)
    livetennis_api_key: str = ""

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Application URLs
    oauth_redirect_uri: str = ""
    frontend_url: str = ""

    # GCP Project
    gcp_project_id: str = ""

    # Environment
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


def load_settings() -> Settings:
    """Load settings from environment variables."""
    return Settings(
        tennis_api_key=os.environ.get("TENNIS_API_KEY", ""),
        tennis_api_host=os.environ.get("TENNIS_API_HOST", "api-tennis.p.rapidapi.com"),
        tennis_api_base_url=os.environ.get("TENNIS_API_BASE_URL", "https://api-tennis.p.rapidapi.com/"),
        tennis_api_requests_per_minute=int(os.environ.get("TENNIS_API_RPM", "10")),
        tennis_api_requests_per_day=int(os.environ.get("TENNIS_API_RPD", "100")),
        serpapi_key=os.environ.get("SERPAPI_KEY", ""),
        livetennis_api_key=os.environ.get("LIVETENNIS_API_KEY", ""),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        oauth_redirect_uri=os.environ.get("OAUTH_REDIRECT_URI", ""),
        frontend_url=os.environ.get("FRONTEND_URL", ""),
        gcp_project_id=os.environ.get("GCP_PROJECT_ID", ""),
        environment=os.environ.get("ENVIRONMENT", "development"),
    )


# Global settings instance (lazy loaded)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
