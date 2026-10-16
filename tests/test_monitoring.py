from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from alert_history import AlertHistory, version_of
from dashboard_views import countdown
from locations import LocationProfile, contains
from WeatherService import WeatherService
from test_dashboard import alert


class LocationTests(unittest.TestCase):
    def test_states_and_counties_are_exact(self):
        self.assertTrue(LocationProfile(states=["IL"], counties=["ILC031"]).matches(alert()))
        self.assertFalse(LocationProfile(counties=["ILC003"]).matches(alert()))
        self.assertFalse(LocationProfile(states=["TX"]).matches(alert()))
        self.assertFalse(LocationProfile(enabled=False).matches(alert()))
        self.assertFalse(LocationProfile(events=["Flood Watch"]).matches(alert()))

    def test_coordinate_polygon_holes_and_zone_fallback(self):
        geometry = {"type": "Polygon", "coordinates": [
            [[0,0],[5,0],[5,5],[0,5],[0,0]], [[1,1],[2,1],[2,2],[1,2],[1,1]]]}
        self.assertTrue(contains(geometry, 3, 3))
        self.assertFalse(contains(geometry, 1.5, 1.5))
        p = LocationProfile(latitude=3, longitude=3, zones=["ILC031"])
        self.assertTrue(p.matches(alert(geometry=geometry)))
        p.latitude = 1.5
        p.longitude = 1.5
        self.assertFalse(p.matches(alert(geometry=geometry)))  # no county fallback over a precise polygon
        self.assertTrue(p.matches(alert(geometry=None)))
        self.assertFalse(p.matches(alert(geometry=None, geocode={})))

    def test_profile_validation(self):
        for params in ({"states":["ZZ"]}, {"counties":["Cook"]}, {"latitude":90},
                       {"latitude":float("nan"), "longitude":20}, {"name":" "}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                LocationProfile(**params).validate()
        self.assertEqual(LocationProfile(states=["il", "IL"]).validate().states, ["IL"])


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "history.db"
        self.store = AlertHistory(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_new_updated_extended_and_independent_receipts(self):
        a = alert(expires="2099-01-01T01:00:00Z")
        v1, kind, _ = self.store.observe(a)
        self.assertEqual(kind, "New")
        self.assertEqual(self.store.observe(a)[1], "New")
        self.store.mark_displayed(a["id"], v1)
        self.store.schedule(a["id"], v1, "home", "sound")
        self.store.schedule(a["id"], v1, "home", "desktop")
        self.store.receipt(a["id"], v1, "home", "sound")
        self.store.receipt(a["id"], v1, "home", "desktop", RuntimeError("offline"))
        self.assertFalse(self.store.pending(a["id"], v1, "home", "sound"))
        self.assertTrue(self.store.pending(a["id"], v1, "home", "desktop"))
        v2, kind, _ = self.store.observe(alert(headline="Shelter now", expires=a["expires"]))
        self.assertEqual(kind, "Updated")
        self.assertNotEqual(v1, v2)
        self.assertFalse(self.store.displayed(a["id"], v2))
        _, kind, _ = self.store.observe(alert(expires="2099-01-01T02:00:00Z"))
        self.assertEqual(kind, "Extended")

    def test_new_id_update_supersedes_referenced_alert(self):
        original = alert(expires="2099-01-01T01:00:00Z")
        self.store.observe(original)
        update = alert(id="replacement", expires="2099-01-01T02:00:00Z", message_type="Update",
                       references=[{"identifier":original["id"]}])
        _, kind, _ = self.store.observe(update)
        self.assertEqual(kind, "Extended")
        self.assertEqual([r["id"] for r in self.store.rows(active_only=True)], ["replacement"])

    def test_disappearance_is_not_called_cancellation(self):
        self.store.observe(alert())
        changes = self.store.reconcile(set())
        self.assertEqual(changes[0][1], "No longer active")
        self.assertFalse(self.store.rows(active_only=True))
        self.assertFalse(self.store.reconcile(set()))  # no duplicate lifecycle change

    def test_expiration_and_cancel_references(self):
        a = alert()
        self.store.observe(a)
        cancel = alert(id="cancel", message_type="Cancel", references=[{"identifier":a["id"]}])
        self.store.observe(cancel)
        self.assertEqual(self.store.cancel_references(cancel)[0][1], "Cancelled")
        self.assertFalse(self.store.rows(active_only=True))
        self.assertFalse(self.store.cancel_references(cancel))

    def test_restart_profiles_receipts_and_legacy_migration(self):
        a = alert()
        self.store.claim(a["id"])
        version, _, legacy = self.store.observe(a)
        self.assertTrue(legacy)
        self.assertTrue(self.store.displayed(a["id"], version))
        p = LocationProfile(name="Home", states=["IL"], desktop=False)
        self.store.save_profile(p)
        self.store.schedule(a["id"], version, p.id, "desktop")
        self.store.receipt(a["id"], version, p.id, "desktop", "offline")
        self.store.close()
        self.store = AlertHistory(self.path)
        self.assertFalse(self.store.profiles()[0].desktop)
        self.assertTrue(self.store.pending(a["id"], version, p.id, "desktop"))
        for _ in range(2):
            self.store.receipt(a["id"], version, p.id, "desktop", "offline")
        self.assertFalse(self.store.pending(a["id"], version, p.id, "desktop"))
        self.assertFalse(self.store.observe(alert(headline="Updated"))[2])

    def test_map_enrichment_does_not_make_a_new_version(self):
        self.assertEqual(version_of(alert()), version_of(alert(geometry={"type":"Polygon", "coordinates":[]}, geometry_source="NWS affected zones")))

    def test_native_polygon_changes_make_a_new_version(self):
        self.assertNotEqual(version_of(alert()), version_of(alert(geometry={
            "type":"Polygon", "coordinates":[[[0,0],[1,0],[1,1],[0,0]]]})))

    def test_countdown(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(countdown(alert(expires=(now+timedelta(seconds=75)).isoformat()), now), "Expires in 2m")
        self.assertEqual(countdown(alert(expires=(now-timedelta(seconds=1)).isoformat()), now), "Expired")


class WeatherApiTests(unittest.TestCase):
    def test_complete_pagination_and_cancel_query(self):
        service = WeatherService.__new__(WeatherService)
        service.session = Mock()
        first = Mock()
        first.json.return_value = {"features":[{"id":"one"}], "pagination":{"next":"https://api.weather.gov/alerts?cursor=2"}}
        last = Mock()
        last.json.return_value = {"features":[{"id":"two"}]}
        service.session.get.side_effect = [first, last]
        self.assertEqual(len(service.fetch_alerts()), 2)
        service.session.get.side_effect = None
        service.session.get.return_value = last
        service.fetch_cancellations()
        self.assertEqual(service.session.get.call_args.kwargs["params"]["message_type"], "cancel")

    def test_zone_geometry_is_cached_and_never_drawn_partially(self):
        service = WeatherService.__new__(WeatherService)
        service.session = Mock()
        geometry = {"type":"Polygon", "coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}
        service.session.get.return_value.json.return_value = {"geometry":geometry}
        a = alert(zones=["https://api.weather.gov/zones/county/ILC031", "https://api.weather.gov/zones/county/ILC043"])
        original_version = version_of(a)
        service.enrich_boundaries([a], [LocationProfile()], max_requests=1)
        self.assertIsNone(a["geometry"])
        service.enrich_boundaries([a], [LocationProfile()], max_requests=1)
        self.assertEqual(len(a["geometry"]["coordinates"]), 2)
        self.assertEqual(version_of(a), original_version)
        service.enrich_boundaries([a], [LocationProfile()], max_requests=1)
        self.assertEqual(service.session.get.call_count, 2)

    def test_bad_pagination_cannot_mark_alerts_inactive(self):
        service = WeatherService.__new__(WeatherService)
        service.session = Mock()
        service.session.get.return_value.json.return_value = {"features":[], "pagination":{"next":"https://untrusted.example/data"}}
        with self.assertRaises(ValueError):
            service.fetch_alerts()
        self.assertEqual(service.session.get.call_count, 1)
