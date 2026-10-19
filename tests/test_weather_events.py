"""Weather-wide event coverage across parsing, preferences, downloads and GUI."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from TkFlow import Form
from alert_history import AlertHistory
from dashboard_views import threat_priority
from event_catalog import (CATEGORY_LABELS, DEFAULT_EVENTS, NON_WEATHER_EVENTS, WEATHER_EVENTS,
                           event_category, event_color, is_supported_event, is_weather_event)
from historical_alerts import ArchiveQuery, download_recent
from history_download import EVENTS
from locations import LocationProfile
from main import StormwatchApp
from notification_explanations import decisions
from test_dashboard import alert
from test_historical_download import feature, parse, response


ADDED_EVENTS = '''Air Quality Alert
Air Stagnation Advisory
Ashfall Advisory
Avalanche Advisory
Beach Hazards Statement
Blowing Dust Advisory
Brisk Wind Advisory
Coastal Flood Advisory
Coastal Flood Statement
Cold Weather Advisory
Dense Fog Advisory
Dense Smoke Advisory
Dust Advisory
Extreme Fire Danger
Flash Flood Statement
Flood Advisory
Flood Statement
Freezing Fog Advisory
Freezing Spray Advisory
Frost Advisory
Hazardous Weather Outlook
Heat Advisory
High Surf Advisory
Hydrologic Outlook
Lake Wind Advisory
Lakeshore Flood Advisory
Lakeshore Flood Statement
Low Water Advisory
Marine Weather Statement
Rip Current Statement
Severe Weather Statement
Short Term Forecast
Small Craft Advisory
Special Weather Statement
Tropical Cyclone Local Statement
Tsunami Advisory
Wind Advisory
Winter Weather Advisory'''.splitlines()


class WeatherCatalogTests(unittest.TestCase):
    def test_every_new_weather_type_is_parsed_and_available_in_the_shared_catalog(self):
        self.assertEqual(len(ADDED_EVENTS),38)
        for event in ADDED_EVENTS:
            with self.subTest(event=event):
                self.assertIn(event,WEATHER_EVENTS)
                self.assertEqual(parse(feature(event=event))['event'],event)
        self.assertTrue(set(WEATHER_EVENTS).isdisjoint(NON_WEATHER_EVENTS))
        for event in WEATHER_EVENTS:
            with self.subTest(event=event):
                self.assertTrue(is_weather_event(event))
                self.assertEqual(parse(feature(event=event))['event'],event)
                self.assertIn(event_category(event),CATEGORY_LABELS)

    def test_nonweather_messages_stay_excluded_and_legacy_warning_names_remain_compatible(self):
        for event in NON_WEATHER_EVENTS:
            with self.subTest(event=event):
                self.assertFalse(is_weather_event(event))
                if not event.endswith((' Watch',' Warning')):
                    self.assertIsNone(parse(feature(event=event)))
        for event in ('Wind Chill Warning','Excessive Heat Warning','Hard Freeze Watch'):
            self.assertTrue(is_supported_event(event))
            self.assertIsNotNone(parse(feature(event=event)))
            LocationProfile(events=[event],sound_events=[event],speech_events=[event]).validate()
        self.assertFalse(is_supported_event(None))
        self.assertFalse(is_supported_event('Not an NWS event'))

    def test_category_rules_event_filters_and_speech_are_independent_for_every_catalog_entry(self):
        for event in WEATHER_EVENTS:
            with self.subTest(event=event):
                kind = event_category(event)
                profile = LocationProfile(events=[event],sound_events=[event],speech=True,speech_events=[event]).validate()
                self.assertTrue(profile.allows(event,'sound'))
                self.assertTrue(profile.allows(event,'desktop'))
                self.assertTrue(profile.allows(event,'speech'))
                setattr(profile,kind+'_sound',False)
                self.assertFalse(profile.allows(event,'sound'))
                self.assertTrue(profile.allows(event,'desktop'))
                self.assertTrue(profile.allows(event,'speech'))
                choices = decisions(profile,alert(event=event))
                self.assertFalse(choices['sound']['allowed'])
                self.assertIn('event-category',choices['sound']['reason'])
                restored = LocationProfile.from_json(profile.to_json())
                self.assertFalse(restored.allows(event,'sound'))
                self.assertEqual(restored.sound_events,[event])
                restored.desktop = False
                self.assertFalse(restored.allows(event,'desktop'))

    def test_legacy_profiles_keep_selections_and_inherit_new_rules(self):
        profile = LocationProfile.from_json(json.dumps(dict(name='Home',events=['Tornado Warning'],watch_sound=False)))
        self.assertEqual(profile.events,['Tornado Warning'])
        self.assertEqual(LocationProfile().events,list(DEFAULT_EVENTS))
        self.assertFalse(profile.speech)
        self.assertIsNone(profile.advisory_sound)
        self.assertTrue(profile.allows('Winter Weather Advisory','sound'))
        self.assertFalse(profile.allows('Tornado Watch','sound'))
        with self.assertRaises(ValueError):
            LocationProfile(advisory_sound='yes').validate()

    def test_forecast_and_other_types_have_categories_and_distinct_presentation(self):
        self.assertEqual(event_category('Short Term Forecast'),'outlook')
        self.assertEqual(event_category('Air Quality Alert'),'other')
        self.assertEqual(event_category('Extreme Fire Danger'),'other')
        self.assertNotEqual(event_color('Winter Weather Advisory'),event_color('Tornado Watch'))
        self.assertGreater(threat_priority(alert(event='Tornado Warning',severity='Minor')),
                           threat_priority(alert(event='Heat Advisory',severity='Extreme')))

    def test_archive_queries_and_category_presets_cover_the_complete_catalog(self):
        today = str(datetime.now().astimezone().date())
        self.assertEqual(EVENTS['All weather events'],'')
        for event in WEATHER_EVENTS:
            with self.subTest(event=event):
                self.assertEqual(ArchiveQuery(today,today,'US',event).parameters()['event'],event)
                self.assertIn(event,EVENTS[CATEGORY_LABELS[event_category(event)]].split(','))
        for invalid in ('Administrative Message','Blue Alert','Test','Heat Advisory&status=test'):
            with self.assertRaises(ValueError):
                ArchiveQuery(today,today,'US',invalid).parameters()

    def test_all_weather_download_imports_new_categories_and_excludes_civil_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertHistory(Path(directory)/'history.db')
            try:
                session = MagicMock()
                values = [feature(identifier=str(i),event=event) for i,event in enumerate(ADDED_EVENTS)]
                values += [feature(identifier=event,event=event) for event in NON_WEATHER_EVENTS]
                session.get.return_value = response(dict(features=values))
                today = str(datetime.now().astimezone().date())
                result = download_recent(ArchiveQuery(today,today,'US'),store,parse,session=session)
                self.assertEqual(result['imported'],38)
                self.assertEqual(result['skipped'],len(NON_WEATHER_EVENTS))
                self.assertEqual({row['event'] for row in store.search_history(limit=100)},set(ADDED_EVENTS))
                self.assertFalse(store.rows(active_only=True))
                self.assertEqual(store.delivery_count(),0)
            finally:
                store.close()


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),'GUI tests require a desktop display')
class WeatherCoverageGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.service = Mock(interval=60)
        self.ui = StormwatchApp(self.service,AlertHistory(Path(self.directory.name)/'history.db'))
        self.ui.profile.sound = self.ui.profile.desktop = False
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, condition):
        deadline = time.monotonic()+8
        while not condition() and time.monotonic()<deadline:
            self.ui.app.root.update()
            time.sleep(.005)
        self.assertTrue(condition())

    def receive(self, values):
        self.ui.running = True
        self.ui.received(self.ui.generation,({a['id']:a for a in values},''))
        self.pump(lambda:not self.ui.busy and not self.ui.delivery_busy and not self.ui.speech_busy)
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def test_every_selector_lists_weather_events_before_they_are_active(self):
        expected = set(WEATHER_EVENTS)
        self.assertTrue(expected.issubset(self.ui.choices))
        self.assertFalse(self.ui.choices['Winter Weather Advisory'].get())
        self.assertTrue(expected.issubset(self.ui.history_panel.event.values))
        self.ui.add_location()
        wizard = self.ui.location_wizard
        self.assertTrue(expected.issubset(wizard.events))
        self.assertFalse(wizard.events['Heat Advisory'].get())
        wizard.close()
        self.ui.edit_sound_events()
        prefs = self.ui.sound_preferences
        self.assertTrue(expected.issubset(prefs.choices))
        prefs.none()
        prefs.choices['Air Quality Alert'].set(True)
        prefs.save()
        self.assertEqual(self.ui.profile.sound_events,['Air Quality Alert'])
        self.ui.edit_speech_events()
        prefs = self.ui.speech_preferences
        self.assertTrue(expected.issubset(prefs.choices))
        prefs.enabled.set(True)
        prefs.none()
        prefs.choices['Short Term Forecast'].set(True)
        prefs.save()
        self.assertEqual(self.ui.profile.speech_events,['Short Term Forecast'])
        self.ui.history_panel.open_download()
        self.assertTrue(expected.issubset(self.ui.history_panel.downloader.event.values))
        self.assertIn('All weather events',self.ui.history_panel.downloader.event.values)

    def test_all_catalog_types_reach_feed_cards_history_map_and_metrics(self):
        self.ui.select_all(True)
        values = [alert(id=event,event=event) for event in WEATHER_EVENTS]
        self.receive(values)
        self.assertEqual(len(self.ui.snapshot),len(WEATHER_EVENTS))
        self.assertEqual(self.ui.history.history_count(),len(WEATHER_EVENTS))
        self.assertEqual(len(self.ui.map.rows),len(WEATHER_EVENTS))
        for event in ADDED_EVENTS:
            self.assertIn(event,self.ui.feed.get())
            index = self.ui.feed.text.search('NEW  ·  '+event,'1.0')
            self.assertIn(event_category(event),self.ui.feed.text.tag_names(index))
        self.ui.open_metrics()
        self.pump(lambda:not self.ui.metrics.busy)
        self.assertEqual(len(self.ui.metrics.table.tree.get_children()),len(WEATHER_EVENTS))
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()

    def test_new_category_rules_can_be_edited_and_saved(self):
        self.ui.edit_profile()
        form = next(child for child in self.ui.app._windows[-1]._children if isinstance(child,Form))
        for category in ('advisory','statement','outlook','other'):
            self.assertIn(category+'_sound',form.fields)
            self.assertIn(category+'_desktop',form.fields)
        form.set(dict(sound=True,desktop=True,advisory_sound=False,advisory_desktop=True,
                      statement_sound=False,other_desktop=False))
        save = next(child for child in form.actions._children if child.widget.cget('text')=='Save location')
        save.invoke()
        self.assertFalse(self.ui.profile.allows('Heat Advisory','sound'))
        self.assertTrue(self.ui.profile.allows('Heat Advisory','desktop'))
        self.assertFalse(self.ui.profile.allows('Air Quality Alert','desktop'))

    def test_new_advisory_speech_respects_session_cutoff_and_version_deduplication(self):
        self.ui.choices['Winter Weather Advisory'].set(True)
        self.ui.profile.speech = True
        self.ui.profile.speech_events = ['Winter Weather Advisory']
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        started = self.ui.speech_started_at
        with patch.object(self.ui.speaker,'speak') as speak:
            old = alert(id='old',event='Winter Weather Advisory',sent=(started-timedelta(hours=1)).isoformat())
            new = alert(id='new',event='Winter Weather Advisory',sent=(started+timedelta(microseconds=1)).isoformat())
            self.receive([old,new])
            self.receive([old,new])
            speak.assert_called_once()
            self.assertIn('Winter Weather Advisory',speak.call_args.args[0])
            rows = [row for row in self.ui.history.delivery_rows() if row['channel']=='speech']
            self.assertEqual({row['id']:row['state'] for row in rows},{'old':'skipped','new':'sent'})
