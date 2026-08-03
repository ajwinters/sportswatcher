"""
Tests for the optional Live Tennis API source.

Standard library only - run from the functions/ directory:

    python -m unittest discover tests
"""

import unittest
from unittest.mock import Mock, patch

from services.livetennis_service import (
    LiveTennisAPIService,
    _format_surface,
    _split_scheduled_time,
    match_signature,
    normalize_livetennis_match,
)


def make_service(api_key="test-key"):
    """Build a service with settings stubbed out."""
    with patch("services.livetennis_service.get_settings") as get_settings:
        get_settings.return_value = Mock(livetennis_api_key=api_key)
        return LiveTennisAPIService()


def json_response(payload):
    """Build a stub requests response returning payload."""
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


# Shaped to the published schema: https://github.com/livetennisapi/openapi
MATCH = {
    "id": 987,
    "tournament": "Australian Open",
    "surface": "hard",
    "indoor": False,
    "round": "Round of 32",
    "status": "upcoming",
    "scheduled_time": "2026-01-20T09:00:00Z",
    "players": {
        "p1": {"id": 11, "name": "Jannik Sinner"},
        "p2": {"id": 22, "name": "Carlos Alcaraz"},
    },
    "score": None,
    "winner": None,
}


class NormalizationTests(unittest.TestCase):
    def test_maps_match_onto_the_shared_schema(self):
        result = normalize_livetennis_match(MATCH)

        self.assertEqual(result["event_key"], "ltapi-987")
        self.assertEqual(result["event_home_player"], "Jannik Sinner")
        self.assertEqual(result["event_away_player"], "Carlos Alcaraz")
        self.assertEqual(result["home_player_id"], "11")
        self.assertEqual(result["away_player_id"], "22")
        self.assertEqual(result["tournament_name"], "Australian Open")
        self.assertEqual(result["event_round"], "Round of 32")
        self.assertEqual(result["event_date"], "2026-01-20")
        self.assertEqual(result["event_time"], "09:00")
        self.assertEqual(result["event_status"], "notstarted")
        self.assertEqual(result["event_surface"], "Hard outdoor")

    def test_event_key_is_namespaced_so_provider_ids_cannot_collide(self):
        # A TennisApi1 event with the same numeric ID must stay distinct.
        self.assertEqual(normalize_livetennis_match({"id": 15373171})["event_key"],
                         "ltapi-15373171")

    def test_venue_is_left_empty_rather_than_guessed(self):
        self.assertEqual(normalize_livetennis_match(MATCH)["event_stadium"], "")

    def test_status_maps_onto_the_existing_vocabulary(self):
        cases = {
            "upcoming": "notstarted",
            "live": "inprogress",
            "completed": "finished",
            "cancelled": "cancelled",
        }
        for api_status, expected in cases.items():
            with self.subTest(api_status=api_status):
                match = dict(MATCH, status=api_status)
                self.assertEqual(
                    normalize_livetennis_match(match)["event_status"], expected
                )

    def test_missing_players_fall_back_to_tbd(self):
        result = normalize_livetennis_match({"id": 1, "players": {}})
        self.assertEqual(result["event_home_player"], "TBD")
        self.assertEqual(result["event_away_player"], "TBD")


class ScheduledTimeTests(unittest.TestCase):
    def test_splits_utc_timestamp(self):
        self.assertEqual(
            _split_scheduled_time("2026-01-20T09:00:00Z"),
            ("2026-01-20", "09:00", 1768899600),
        )

    def test_converts_offset_timestamp_to_utc(self):
        date, time, _ = _split_scheduled_time("2026-01-20T09:00:00+02:00")
        self.assertEqual((date, time), ("2026-01-20", "07:00"))

    def test_unscheduled_match_yields_empty_values(self):
        self.assertEqual(_split_scheduled_time(None), ("", "", 0))

    def test_unparseable_value_does_not_raise(self):
        self.assertEqual(_split_scheduled_time("not a date"), ("", "", 0))


class SurfaceTests(unittest.TestCase):
    def test_renders_surface_and_venue_type(self):
        self.assertEqual(_format_surface("clay", False), "Clay outdoor")
        self.assertEqual(_format_surface("hard", True), "Hard indoor")

    def test_unknown_surface_is_empty(self):
        self.assertEqual(_format_surface(None, False), "")


class SignatureTests(unittest.TestCase):
    def test_signature_ignores_player_order(self):
        a = {"event_date": "2026-01-20", "event_home_player": "Jannik Sinner",
             "event_away_player": "Carlos Alcaraz"}
        b = {"event_date": "2026-01-20", "event_home_player": "Carlos Alcaraz",
             "event_away_player": "Jannik Sinner"}
        self.assertEqual(match_signature(a), match_signature(b))

    def test_signature_ignores_accents_and_case(self):
        a = {"event_date": "2026-01-20", "event_home_player": "Stefanos Tsitsipas",
             "event_away_player": "A B"}
        b = {"event_date": "2026-01-20", "event_home_player": "stefanos tsitsipás",
             "event_away_player": "A B"}
        self.assertEqual(match_signature(a), match_signature(b))

    def test_different_days_are_different_matches(self):
        a = {"event_date": "2026-01-20", "event_home_player": "X", "event_away_player": "Y"}
        b = {"event_date": "2026-01-21", "event_home_player": "X", "event_away_player": "Y"}
        self.assertNotEqual(match_signature(a), match_signature(b))


class PlayerResolutionTests(unittest.TestCase):
    @patch("services.livetennis_service.requests.get")
    def test_resolves_exact_name(self, get):
        get.return_value = json_response(
            {"data": [{"id": 11, "name": "Jannik Sinner"}], "meta": {}}
        )
        self.assertEqual(make_service().resolve_player_id("Jannik Sinner"), 11)

    @patch("services.livetennis_service.requests.get")
    def test_resolution_ignores_accents(self, get):
        get.return_value = json_response(
            {"data": [{"id": 5, "name": "Stefanos Tsitsipás"}], "meta": {}}
        )
        self.assertEqual(make_service().resolve_player_id("Stefanos Tsitsipas"), 5)

    @patch("services.livetennis_service.requests.get")
    def test_near_miss_is_not_guessed(self, get):
        # A surname-only hit must not be accepted as the followed player.
        get.return_value = json_response(
            {"data": [{"id": 99, "name": "Some Other Sinner"}], "meta": {}}
        )
        self.assertIsNone(make_service().resolve_player_id("Jannik Sinner"))

    @patch("services.livetennis_service.requests.get")
    def test_result_is_cached(self, get):
        get.return_value = json_response(
            {"data": [{"id": 11, "name": "Jannik Sinner"}], "meta": {}}
        )
        service = make_service()
        service.resolve_player_id("Jannik Sinner")
        service.resolve_player_id("jannik  sinner")
        self.assertEqual(get.call_count, 1)


class MatchRetrievalTests(unittest.TestCase):
    @patch("services.livetennis_service.requests.get")
    def test_without_a_key_nothing_is_requested(self, get):
        service = make_service(api_key="")
        self.assertFalse(service.is_configured)
        self.assertEqual(service.get_matches_for_player_names(["Jannik Sinner"]), [])
        get.assert_not_called()

    @patch("services.livetennis_service.requests.get")
    def test_returns_only_matches_involving_followed_players(self, get):
        other = dict(MATCH, id=1000, players={
            "p1": {"id": 77, "name": "Someone Else"},
            "p2": {"id": 88, "name": "Another Player"},
        })

        def responses(url, **kwargs):
            if url.endswith("/players"):
                return json_response(
                    {"data": [{"id": 11, "name": "Jannik Sinner"}], "meta": {}}
                )
            status = kwargs["params"]["status"]
            data = [MATCH, other] if status == "upcoming" else []
            return json_response({"data": data, "meta": {"has_more": False}})

        get.side_effect = responses

        matches = make_service().get_matches_for_player_names(["Jannik Sinner"])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["event_key"], "ltapi-987")
        self.assertEqual(matches[0]["followed_player_names"], ["Jannik Sinner"])

    @patch("services.livetennis_service.requests.get")
    def test_unresolvable_players_short_circuit_without_listing_matches(self, get):
        get.return_value = json_response({"data": [], "meta": {}})

        self.assertEqual(make_service().get_matches_for_player_names(["Nobody"]), [])
        # Only the /players lookup happened; no /matches walk.
        self.assertEqual(get.call_count, 1)

    @patch("services.livetennis_service.requests.get")
    def test_api_failure_does_not_propagate(self, get):
        import requests as requests_module

        def responses(url, **kwargs):
            if url.endswith("/players"):
                return json_response(
                    {"data": [{"id": 11, "name": "Jannik Sinner"}], "meta": {}}
                )
            raise requests_module.RequestException("boom")

        get.side_effect = responses

        self.assertEqual(
            make_service().get_matches_for_player_names(["Jannik Sinner"]), []
        )

    @patch("services.livetennis_service.requests.get")
    def test_paging_stops_when_has_more_is_false(self, get):
        def responses(url, **kwargs):
            if url.endswith("/players"):
                return json_response(
                    {"data": [{"id": 11, "name": "Jannik Sinner"}], "meta": {}}
                )
            if kwargs["params"]["offset"] == 0:
                return json_response(
                    {"data": [MATCH], "meta": {"has_more": True}}
                )
            return json_response({"data": [MATCH], "meta": {"has_more": False}})

        get.side_effect = responses

        service = make_service()
        self.assertEqual(len(service._iter_matches("upcoming")), 2)

    @patch("services.livetennis_service.requests.get")
    def test_paging_is_capped(self, get):
        get.return_value = json_response({"data": [MATCH], "meta": {"has_more": True}})
        service = make_service()
        service._iter_matches("upcoming")
        self.assertEqual(get.call_count, service.MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
