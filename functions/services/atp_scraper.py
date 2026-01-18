"""
ATP Tour website scraper for tennis match schedules.

This module is maintained for backward compatibility.
New code should use tour_scraper.py which supports both ATP and WTA.
"""

from services.tour_scraper import TourScraper, TourScraperError, get_tour_scraper


# Backwards compatible aliases
ATPScraperError = TourScraperError
ATPScraper = TourScraper


def get_atp_scraper() -> TourScraper:
    """Get a singleton ATP scraper instance."""
    return get_tour_scraper()
