"""Location setup, isolated simulations, and channel-specific delivery controls."""
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock

from alert_history import AlertHistory
from delivery_panel import delivery_status
from main import StormwatchApp
from place_search import search_places
from test_dashboard import alert
from WeatherService import WeatherService


class PlaceSearchTests(unittest.TestCase):
    def test_zip_city_state_and_leading_zeroes(self):
        self.assertEqual(search_places('60601')[0].city, 'Chicago')
        self.assertEqual(search_places('60601-1234')[0].zip, '60601')
        self.assertEqual(search_places('02108')[0].city, 'Boston')
        self.assertTrue(all(p.state == 'IL' for p in search_places('Springfield Illinois')))
        self.assertTrue(all(p.state == 'CA' for p in search_places('San José CA')))

    def test_no_match_and_invalid_input(self):
        self.assertEqual(search_places('zzzzzzzzzz nowhere'), [])
        with self.assertRaises(ValueError):
            search_places('')

    def test_result_is_an_approximate_point_profile(self):
        point = search_places('60601')[0].profile('Home')
        self.assertEqual(point.name, 'Home')
        self.assertIsNotNone(point.latitude)
        self.assertEqual(point.zones, [])  # zones are resolved by NWS before saving


class DeliveryMigrationTests(unittest.TestCase):
    def test_old_channel_receipts_survive_schema_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.db'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE deliveries (id TEXT,version TEXT,profile TEXT,channel TEXT,state TEXT,attempts INTEGER,error TEXT,PRIMARY KEY(id,version,profile,channel))')
            connection.execute("INSERT INTO deliveries VALUES ('one','v1','home','desktop','failed',3,'Offline')")
            connection.commit()
            connection.close()
            store = AlertHistory(path)
            try:
                row = store.delivery_rows()[0]
                self.assertEqual(row['error'], 'Offline')
                self.assertEqual(row['attempts'], 3)
                self.assertEqual(row['last_attempt'], '')
                self.assertEqual(delivery_status(row), 'Failed · retries exhausted')
            finally:
                store.close()


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'GUI tests require a desktop display')
class UsabilityTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock(interval=60, base_dir=Path(__file__).resolve().parents[1])
        self.service.parse_alert.side_effect = lambda f: WeatherService.parse_alert(None, f)
        self.service.resolve_location.return_value = ['ILC031', 'ILZ104']
        self.service.fetch_alerts.return_value = []
        self.service.fetch_cancellations.return_value = []
        self.directory = tempfile.TemporaryDirectory()
        self.owner = StormwatchApp(self.service, AlertHistory(Path(self.directory.name) / 'live.db'))
        self.owner.app.root.update()

    def tearDown(self):
        self.owner.close()
        self.owner.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, condition):
        deadline = time.monotonic() + 4
        while not condition() and time.monotonic() < deadline:
            self.owner.app.root.update()
            time.sleep(.01)
        self.assertTrue(condition())

    def wizard_to_preferences(self):
        self.owner.add_location()
        wizard = self.owner.location_wizard
        wizard.query.set('60601')
        wizard.search()
        self.pump(lambda: len(wizard.results.tree.get_children()) > 0)
        wizard.results.tree.selection_set('0')
        wizard.selection_changed()
        wizard.next()
        self.assertEqual(wizard.step, 1)
        wizard.move_pin(41.88, -87.63)
        wizard.next()
        self.assertEqual(wizard.step, 2)
        return wizard

    def settle_live(self):
        if self.owner.timer:
            self.owner.app.root.after_cancel(self.owner.timer)
            self.owner.timer = None
        if self.owner.delivery_future:
            self.owner.delivery_future.result(timeout=3)
            self.pump(lambda: not self.owner.delivery_busy)

    def receive(self):
        self.owner.running = True
        self.owner.received(self.owner.generation, ({'Tornado Warning': alert()}, ''))
        self.settle_live()

    def test_wizard_saves_named_profile_after_pin_confirmation(self):
        wizard = self.wizard_to_preferences()
        wizard.form.set({'name':'Home', 'sound':False, 'desktop':True})
        wizard.save()
        self.pump(lambda: wizard.window._closed)
        home = next(p for p in self.owner.profiles if p.name == 'Home')
        self.assertEqual((home.latitude,home.longitude), (41.88,-87.63))
        self.assertEqual(home.zones, ['ILC031','ILZ104'])
        self.assertFalse(home.sound)
        self.assertTrue(home.desktop)
        self.service.resolve_location.assert_called_once_with(41.88,-87.63)

    def test_wizard_network_failure_never_saves_partial_profile(self):
        self.service.resolve_location.side_effect = RuntimeError('NWS unavailable')
        wizard = self.wizard_to_preferences()
        wizard.save()
        self.pump(lambda: not wizard.busy)
        self.assertEqual(len(self.owner.history.profiles()), 1)
        self.assertIn('NWS unavailable', wizard.message.get())
        self.assertFalse(wizard.window._closed)

    def test_wizard_rejects_duplicate_name_before_resolving(self):
        wizard = self.wizard_to_preferences()
        wizard.form.set({'name':'United States'})
        wizard.save()
        self.assertIn('already exists', wizard.message.get())
        self.service.resolve_location.assert_not_called()

    def test_delivery_panel_preserves_sound_when_manually_retrying_exhausted_desktop(self):
        self.service.deliver_desktop.side_effect = RuntimeError('Offline')
        for _ in range(3):
            self.receive()
        panel = self.owner.delivery_panel
        failed = next(r for r in panel.rows if r['channel'] == 'desktop')
        self.assertEqual(delivery_status(failed), 'Failed · retries exhausted')
        self.assertIn('Offline', panel.details.get())
        self.service.deliver_desktop.side_effect = None
        self.owner.retry_delivery(failed)
        self.settle_live()
        row = self.owner.history.delivery(failed['id'], failed['version'], failed['profile'], 'desktop')
        self.assertEqual(row['state'], 'sent')
        self.assertEqual(row['attempts'], 4)
        self.service.deliver_sound.assert_called_once()
        self.assertEqual(self.service.deliver_desktop.call_count, 4)
        self.assertTrue(row['last_attempt'])

    def test_manual_retry_rejects_paused_or_disabled_live_channel(self):
        self.service.deliver_desktop.side_effect = RuntimeError('Offline')
        self.receive()
        desktop = next(r for r in self.owner.delivery_panel.rows if r['channel'] == 'desktop')
        self.owner.toggle_monitoring()
        self.owner.retry_delivery(desktop)
        self.assertIn('Start monitoring', self.owner.status.get())
        self.owner.running = True
        self.owner.profile.desktop = False
        self.owner.retry_delivery(desktop)
        self.assertIn('disabled', self.owner.status.get())
        self.service.deliver_desktop.assert_called_once()

    def test_successful_channel_cannot_be_replayed_from_panel(self):
        self.receive()
        sound = next(r for r in self.owner.delivery_panel.rows if r['channel'] == 'sound')
        self.owner.retry_delivery(sound)
        self.assertIn('Only failed channels', self.owner.status.get())
        self.service.deliver_sound.assert_called_once()

    def test_demo_scenarios_never_touch_live_history_or_devices_by_default(self):
        self.owner.open_demo()
        demo = self.owner.demo
        for scenario in ('new', 'update', 'extend', 'cancel'):
            demo.run_scenario(scenario)
        for word in ('SIMULATION', 'UPDATED', 'EXTENDED', 'CANCELLED'):
            self.assertIn(word, demo.feed.get())
        self.assertEqual(self.owner.history.rows(), [])
        self.assertEqual(self.owner.history.delivery_count(), 0)
        self.assertEqual(demo.model.store.rows(active_only=True), [])
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()

    def test_demo_connection_failure_retains_sample_cards(self):
        self.owner.open_demo()
        demo = self.owner.demo
        demo.run_scenario('new')
        demo.run_scenario('offline')
        self.assertIn('CONNECTION FAILED', demo.health.get())
        self.assertEqual(len(demo.model.store.rows(active_only=True)), 1)
        self.assertEqual(self.owner.last_error, '')
        demo.run_scenario('recover')
        self.assertIn('recovered', demo.health.get())

    def test_demo_fabricated_failure_retries_only_desktop_without_any_device(self):
        self.owner.open_demo()
        demo = self.owner.demo
        demo.simulate_delivery_failure()
        desktop = next(r for r in demo.deliveries.rows if r['channel'] == 'desktop')
        demo.retry(desktop)
        self.pump(lambda: not demo.busy)
        rows = demo.model.store.delivery_rows()
        self.assertEqual(next(r for r in rows if r['channel'] == 'sound')['attempts'], 1)
        self.assertEqual(next(r for r in rows if r['channel'] == 'desktop')['attempts'], 2)
        self.assertIn('No device was used', demo.message.get())
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()
        self.assertEqual(self.owner.history.delivery_count(), 0)

    def test_demo_results_remain_visible_at_minimum_window_size(self):
        self.owner.app.root.geometry('1000x760')
        self.owner.open_demo()
        self.owner.demo_window.root.geometry('850x680')
        self.owner.demo.simulate_delivery_failure()
        self.owner.app.root.update()
        self.assertGreaterEqual(self.owner.demo.deliveries.table.tree.winfo_height(), 80)

    def test_real_demo_desktop_preview_is_explicit_and_labeled(self):
        self.owner.open_demo()
        demo = self.owner.demo
        demo.desktop.set(True)
        demo.run_scenario('new')
        self.pump(lambda: not demo.busy)
        self.assertEqual(self.service.deliver_desktop.call_args.args[1], 'SIMULATION')
        self.service.deliver_sound.assert_not_called()
        self.assertEqual(self.owner.history.rows(), [])
