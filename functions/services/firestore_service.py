"""
Firestore database service for players, users, and synced events.
"""

from datetime import datetime, timedelta
from typing import Optional
from google.cloud import firestore


class FirestoreService:
    """Firestore database operations."""

    def __init__(self):
        self.db = firestore.Client()

    # ==================== Player Operations ====================

    def upsert_player(self, player_data: dict) -> str:
        """
        Insert or update a player record.

        Args:
            player_data: Player data including player_key

        Returns:
            The player_key
        """
        player_key = player_data["player_key"]
        doc_ref = self.db.collection("players").document(player_key)
        doc_ref.set(player_data, merge=True)
        return player_key

    def get_player(self, player_key: str) -> Optional[dict]:
        """Get a player by their key."""
        doc = self.db.collection("players").document(player_key).get()
        return doc.to_dict() if doc.exists else None

    def search_players(self, query: str, limit: int = 20) -> list[dict]:
        """
        Search players by name using array-contains on search_terms.

        Args:
            query: Search query (lowercase)
            limit: Maximum results to return

        Returns:
            List of matching player records
        """
        query_lower = query.lower().strip()
        docs = (
            self.db.collection("players")
            .where("search_terms", "array_contains", query_lower)
            .limit(limit)
            .stream()
        )
        return [doc.to_dict() for doc in docs]

    def get_all_players(self, tour: Optional[str] = None) -> list[dict]:
        """
        Get all players, optionally filtered by tour.

        Args:
            tour: Optional filter for "ATP" or "WTA"

        Returns:
            List of player records
        """
        collection = self.db.collection("players")
        if tour:
            collection = collection.where("tour", "==", tour)
        return [doc.to_dict() for doc in collection.stream()]

    def get_player_count(self) -> int:
        """Get total count of players in the database."""
        # Firestore doesn't have a direct count, so we use aggregation
        agg_query = self.db.collection("players").count()
        results = agg_query.get()
        return results[0][0].value if results else 0

    # ==================== User Operations ====================

    def upsert_user(self, user_id: str, user_data: dict) -> str:
        """
        Insert or update a user record.

        Args:
            user_id: Google user ID
            user_data: User data

        Returns:
            The user_id
        """
        doc_ref = self.db.collection("users").document(user_id)

        # Check if user exists to preserve certain fields
        existing = doc_ref.get()
        if existing.exists:
            # Preserve followed_players if not in update
            existing_data = existing.to_dict()
            if "followed_players" not in user_data:
                user_data["followed_players"] = existing_data.get("followed_players", [])
            user_data["updated_at"] = datetime.utcnow()
        else:
            user_data["created_at"] = datetime.utcnow()
            user_data["followed_players"] = user_data.get("followed_players", [])

        doc_ref.set(user_data, merge=True)
        return user_id

    def get_user(self, user_id: str) -> Optional[dict]:
        """Get a user by their ID."""
        doc = self.db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["user_id"] = doc.id
            return data
        return None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get a user by their email."""
        docs = (
            self.db.collection("users")
            .where("email", "==", email)
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            data["user_id"] = doc.id
            return data
        return None

    def add_followed_player(
        self,
        user_id: str,
        player_key: str,
        tour_player_id: Optional[str] = None,
        tour: Optional[str] = None,
        atp_player_id: Optional[str] = None,  # Backwards compatibility
    ) -> bool:
        """
        Add a player to user's followed list.

        Args:
            user_id: User ID
            player_key: Player to follow
            tour_player_id: Tour-specific player ID for web scraping
            tour: Tour type ("ATP" or "WTA")
            atp_player_id: Deprecated, use tour_player_id instead

        Returns:
            True if added, False if already following
        """
        user_ref = self.db.collection("users").document(user_id)
        user = user_ref.get()

        if not user.exists:
            return False

        user_data = user.to_dict()
        followed = user_data.get("followed_players", [])

        # Check if already following
        if any(p["player_key"] == player_key for p in followed):
            return False

        # Get player name and tour from database
        player = self.get_player(player_key)
        player_name = player["name"] if player else "Unknown Player"
        player_tour = tour or (player.get("tour") if player else "ATP")

        player_entry = {
            "player_key": player_key,
            "name": player_name,
            "added_at": datetime.utcnow(),
            "tour": player_tour,
        }

        # Add tour player ID (support both new and legacy parameter names)
        effective_tour_id = tour_player_id or atp_player_id
        if effective_tour_id:
            player_entry["tour_player_id"] = effective_tour_id
            # Also set legacy field for backward compatibility
            player_entry["atp_player_id"] = effective_tour_id

        followed.append(player_entry)

        user_ref.update({"followed_players": followed})
        return True

    def remove_followed_player(self, user_id: str, player_key: str) -> bool:
        """
        Remove a player from user's followed list.

        Args:
            user_id: User ID
            player_key: Player to unfollow

        Returns:
            True if removed, False if not following
        """
        user_ref = self.db.collection("users").document(user_id)
        user = user_ref.get()

        if not user.exists:
            return False

        user_data = user.to_dict()
        followed = user_data.get("followed_players", [])
        original_count = len(followed)

        followed = [p for p in followed if p["player_key"] != player_key]

        if len(followed) == original_count:
            return False

        user_ref.update({"followed_players": followed})
        return True

    def get_all_users_with_players(self) -> list[dict]:
        """Get all users who have followed players."""
        docs = self.db.collection("users").stream()
        users = []
        for doc in docs:
            data = doc.to_dict()
            data["user_id"] = doc.id
            if data.get("followed_players"):
                users.append(data)
        return users

    def update_user_tokens(self, user_id: str, tokens: dict) -> None:
        """Update user's Google OAuth tokens."""
        self.db.collection("users").document(user_id).update({
            "google_tokens": tokens,
            "updated_at": datetime.utcnow(),
        })

    def update_user_last_sync(self, user_id: str) -> None:
        """Update user's last sync timestamp."""
        self.db.collection("users").document(user_id).update({
            "last_sync": datetime.utcnow(),
        })

    # ==================== Synced Events Operations ====================

    def create_synced_event(self, event_data: dict) -> str:
        """
        Create a synced event record.

        Args:
            event_data: Event data including match_key and user_id

        Returns:
            The document ID
        """
        # Create composite key for deduplication
        doc_id = f"{event_data['user_id']}_{event_data['match_key']}"
        event_data["created_at"] = datetime.utcnow()
        event_data["updated_at"] = datetime.utcnow()

        self.db.collection("synced_events").document(doc_id).set(event_data)
        return doc_id

    def get_synced_event(self, user_id: str, match_key: str) -> Optional[dict]:
        """Get a synced event by user and match key."""
        doc_id = f"{user_id}_{match_key}"
        doc = self.db.collection("synced_events").document(doc_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def update_synced_event(self, doc_id: str, updates: dict) -> None:
        """Update a synced event record."""
        updates["updated_at"] = datetime.utcnow()
        self.db.collection("synced_events").document(doc_id).update(updates)

    def delete_synced_event(self, doc_id: str) -> None:
        """Delete a synced event record."""
        self.db.collection("synced_events").document(doc_id).delete()

    def get_user_synced_events(self, user_id: str) -> list[dict]:
        """Get all synced events for a user."""
        docs = (
            self.db.collection("synced_events")
            .where("user_id", "==", user_id)
            .stream()
        )
        events = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            events.append(data)
        return events

    def get_old_synced_events(self, cutoff_date: datetime) -> list[dict]:
        """Get synced events older than the cutoff date."""
        docs = (
            self.db.collection("synced_events")
            .where("scheduled_time", "<", cutoff_date)
            .stream()
        )
        events = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            events.append(data)
        return events

    # ==================== OAuth State Operations ====================

    def store_oauth_state(self, state: str, data: dict) -> None:
        """Store OAuth state for verification."""
        data["created_at"] = datetime.utcnow()
        data["expires_at"] = datetime.utcnow() + timedelta(minutes=10)
        self.db.collection("oauth_states").document(state).set(data)

    def verify_oauth_state(self, state: str) -> bool:
        """Verify and consume OAuth state."""
        doc_ref = self.db.collection("oauth_states").document(state)
        doc = doc_ref.get()

        if not doc.exists:
            return False

        data = doc.to_dict()
        expires_at = data.get("expires_at")

        # Check if expired
        if expires_at and expires_at.replace(tzinfo=None) < datetime.utcnow():
            doc_ref.delete()
            return False

        # Consume the state
        doc_ref.delete()
        return True

    # ==================== Session Operations ====================

    def create_session(self, user_id: str) -> str:
        """
        Create a session token for the user.

        Returns:
            Session token
        """
        import secrets

        token = secrets.token_urlsafe(32)
        self.db.collection("sessions").document(token).set({
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })
        return token

    def get_session_user(self, token: str) -> Optional[str]:
        """Get user ID from session token."""
        doc = self.db.collection("sessions").document(token).get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        expires_at = data.get("expires_at")

        if expires_at and expires_at.replace(tzinfo=None) < datetime.utcnow():
            doc.reference.delete()
            return None

        return data.get("user_id")

    def delete_session(self, token: str) -> None:
        """Delete a session."""
        self.db.collection("sessions").document(token).delete()

    # ==================== Sync Logs ====================

    def log_sync(self, sync_type: str, records_processed: int, errors: list) -> None:
        """Log a sync operation."""
        self.db.collection("sync_logs").add({
            "sync_type": sync_type,
            "status": "success" if not errors else "partial",
            "records_processed": records_processed,
            "errors": errors[:10],  # Limit stored errors
            "completed_at": datetime.utcnow(),
        })

    def log_error(self, message: str) -> None:
        """Log an error."""
        self.db.collection("error_logs").add({
            "message": message,
            "timestamp": datetime.utcnow(),
        })
