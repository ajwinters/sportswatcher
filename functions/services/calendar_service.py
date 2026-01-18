"""
Google Calendar API service for creating and managing tennis match events.
"""

from typing import Optional
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.settings import get_settings


class CalendarService:
    """
    Google Calendar API client for tennis match events.

    Handles creating, updating, and deleting calendar events
    with proper deduplication using extended properties.
    """

    # App identifier for extended properties
    APP_ID = "sportswatcher-tennis"

    def __init__(self, credentials: Credentials):
        """
        Initialize calendar service with user credentials.

        Args:
            credentials: Valid Google OAuth credentials
        """
        self.service = build("calendar", "v3", credentials=credentials)

    def create_event(
        self,
        calendar_id: str,
        event_data: dict,
        match_key: str,
    ) -> dict:
        """
        Create a calendar event for a tennis match.

        Args:
            calendar_id: Calendar ID (usually 'primary')
            event_data: Event data from event_builder
            match_key: Unique match identifier for deduplication

        Returns:
            Created event data from Google Calendar API
        """
        event = {
            "summary": event_data["summary"],
            "description": event_data["description"],
            "start": {
                "dateTime": event_data["start_time"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "end": {
                "dateTime": event_data["end_time"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "location": event_data.get("location", ""),
            # Extended properties for deduplication and identification
            "extendedProperties": {
                "private": {
                    "sportswatcher_match_key": match_key,
                    "sportswatcher_app": self.APP_ID,
                }
            },
            # Reminders
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},  # 1 hour before
                    {"method": "popup", "minutes": 1440},  # 24 hours before
                ],
            },
            # Color (optional - tennis green)
            "colorId": "10",  # Green
        }

        return self.service.events().insert(
            calendarId=calendar_id,
            body=event,
        ).execute()

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        event_data: dict,
    ) -> dict:
        """
        Update an existing calendar event.

        Args:
            calendar_id: Calendar ID
            event_id: Google Calendar event ID
            event_data: Updated event data

        Returns:
            Updated event data from Google Calendar API
        """
        patch_body = {
            "summary": event_data["summary"],
            "description": event_data["description"],
            "start": {
                "dateTime": event_data["start_time"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "end": {
                "dateTime": event_data["end_time"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "location": event_data.get("location", ""),
        }

        return self.service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=patch_body,
        ).execute()

    def delete_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> None:
        """
        Delete a calendar event.

        Args:
            calendar_id: Calendar ID
            event_id: Google Calendar event ID
        """
        try:
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                # Event already deleted, that's fine
                pass
            else:
                raise

    def find_event_by_match_key(
        self,
        calendar_id: str,
        match_key: str,
    ) -> Optional[dict]:
        """
        Find an existing event by match_key using extended properties.

        Used as a fallback for deduplication if Firestore record is missing.

        Args:
            calendar_id: Calendar ID
            match_key: Match key stored in extended properties

        Returns:
            Event data if found, None otherwise
        """
        try:
            events = self.service.events().list(
                calendarId=calendar_id,
                privateExtendedProperty=f"sportswatcher_match_key={match_key}",
                maxResults=1,
            ).execute()

            items = events.get("items", [])
            return items[0] if items else None

        except HttpError:
            return None

    def get_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> Optional[dict]:
        """
        Get a specific event by ID.

        Args:
            calendar_id: Calendar ID
            event_id: Google Calendar event ID

        Returns:
            Event data if found, None otherwise
        """
        try:
            return self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise

    def list_upcoming_events(
        self,
        calendar_id: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        List upcoming events from the calendar.

        Args:
            calendar_id: Calendar ID
            max_results: Maximum number of events to return

        Returns:
            List of upcoming events
        """
        now = datetime.utcnow().isoformat() + "Z"

        events = self.service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return events.get("items", [])

    def list_sportswatcher_events(
        self,
        calendar_id: str,
        max_results: int = 100,
    ) -> list[dict]:
        """
        List all events created by SportsWatcher.

        Args:
            calendar_id: Calendar ID
            max_results: Maximum number of events to return

        Returns:
            List of SportsWatcher events
        """
        events = self.service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"sportswatcher_app={self.APP_ID}",
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return events.get("items", [])

    def get_calendars(self) -> list[dict]:
        """
        Get list of user's calendars.

        Returns:
            List of calendar objects with id, summary, primary fields
        """
        calendar_list = self.service.calendarList().list().execute()

        calendars = []
        for cal in calendar_list.get("items", []):
            calendars.append({
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
            })

        return calendars
