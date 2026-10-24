import json
from datetime import datetime, timedelta, timezone
from gui_support import wait_view
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from TkFlow import Form, TextArea
from alert_history import AlertHistory
from locations import LocationProfile
from main import StormwatchApp
from notification_explanations import decisions, explanation_text
from speech import SpeechService, SpeechCancelled, announcement, command, issued_after
from test_dashboard import alert


class SpeechRuleTests(unittest.TestCase):
    def test_session_cutoff_requires_a_new_timezone_aware_issue_time(self):
        started = datetime(2026,10,18,11,tzinfo=timezone.utc)
        self.assertTrue(issued_after(alert(sent='2026-10-18T06:00:01-05:00'),started))
        for sent in ('2026-10-18T11:00:00Z','2026-10-18T10:59:59Z','2026-10-18T12:00:00',None,'Unknown'):
            with self.subTest(sent=sent):
                self.assertFalse(issued_after(alert(sent=sent),started))
        self.assertFalse(issued_after(alert(sent='2026-10-18T12:00:00Z'),None))

    def test_legacy_profiles_stay_silent_and_speech_is_independent(self):
        legacy = LocationProfile.from_json(json.dumps({'name':'Home'}))
        self.assertFalse(legacy.speech)
        self.assertFalse(legacy.allows('Tornado Warning','speech'))
        profile = LocationProfile(speech=True,sound=False,desktop=False,warning_sound=False,speech_events=['Tornado Warning'])
        self.assertTrue(profile.allows('Tornado Warning','speech'))
        self.assertFalse(profile.allows('Tornado Watch','speech'))
        restored = LocationProfile.from_json(profile.to_json())
        self.assertTrue(restored.speech)
        self.assertEqual(restored.speech_events,['Tornado Warning'])

    def test_match_and_channel_explanations_agree_with_rules(self):
        profile = LocationProfile(name='Home',states=['IL'],counties=['ILC031'],sound_events=['Hurricane Warning'])
        value = decisions(profile,alert())
        self.assertIn('county ILC031',value['desktop']['reason'])
        self.assertIn('Tornado Warning selected',value['desktop']['reason'])
        self.assertFalse(value['sound']['allowed'])
        self.assertIn('event filter',value['sound']['reason'])
        self.assertTrue(value['desktop']['allowed'])
        self.assertIn('switched off',value['speech']['reason'])
        profile.enabled = False
        self.assertFalse(profile.matches(alert()))
        self.assertIn('monitoring is disabled',decisions(profile,alert())['desktop']['reason'])

    def test_quiet_startup_expiration_and_cancellation_are_explained(self):
        profile = LocationProfile(speech=True,speech_events=None)
        self.assertIn('Quiet startup',decisions(profile,alert(),quiet=True)['speech']['reason'])
        self.assertIn('Legacy history',decisions(profile,alert(),quiet=True,legacy=True)['sound']['reason'])
        self.assertIn('expired',decisions(profile,alert(expires='2020-01-01T00:00:00Z'))['speech']['reason'])
        cancelled = decisions(profile,alert(message_type='Cancel'),'Cancelled')
        self.assertFalse(cancelled['speech']['allowed'])
        self.assertTrue(cancelled['desktop']['allowed'])
        self.assertIn('Cancellations',cancelled['sound']['reason'])

    def test_decision_snapshot_freezes_success_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.db'
            store = AlertHistory(path)
            profile = LocationProfile(name='Home')
            a = alert()
            version,_,_ = store.observe(a)
            store.record_decision(a['id'],version,profile,'sound',False,'Event excluded by sound filter.')
            store.record_decision(a['id'],version,profile,'sound',True,'Tornado Warning selected. Matched county ILC031.')
            store.schedule(a['id'],version,profile.id,'sound')
            store.receipt(a['id'],version,profile.id,'sound')
            store.record_decision(a['id'],version,profile,'sound',False,'Now disabled.')
            store.close()
            store = AlertHistory(path)
            try:
                self.assertIn('Matched county',store.decision_rows(a['id'],version)[0]['reason'])
                profile.sound = False
                text = explanation_text(store,a,[profile])
                self.assertIn('Submitted',text)
                self.assertIn('switched off',text)
                self.assertIn('current preferences',text.lower())
            finally:
                store.close()


class NativeSpeechTests(unittest.TestCase):
    def test_windows_speech_text_is_passed_through_stdin(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (b'',b'')
        message = "Tornado Warning for Family's home; $(not a command)."
        with patch('speech.platform.system',return_value='Windows'),patch('speech.subprocess.Popen',return_value=process) as launch:
            SpeechService().speak(message)
        self.assertNotIn(message,' '.join(launch.call_args.args[0]))
        self.assertIn('System.Speech',' '.join(launch.call_args.args[0]))
        self.assertIn("$ErrorActionPreference = 'Stop'",' '.join(launch.call_args.args[0]))
        self.assertEqual(process.communicate.call_args.args[0],message.encode('utf-8'))
        self.assertNotIn('shell',launch.call_args.kwargs)

    def test_missing_linux_engine_reports_installation_requirement(self):
        with patch('speech.platform.system',return_value='Linux'),patch('speech.shutil.which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'espeak-ng'):
                command()

    def test_timeout_and_cancellation_stop_the_owned_process(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [subprocess.TimeoutExpired('voice',45),(b'',b'')]
        with patch('speech.command',return_value=['voice']),patch('speech.subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(RuntimeError,'timed out'):
                SpeechService().speak('Test')
        process.kill.assert_called_once()
        speaker = SpeechService()
        process = Mock(returncode=0)
        process.poll.return_value = None
        process.communicate.side_effect = lambda *args,**kwargs:speaker.stop()
        with patch('speech.command',return_value=['voice']),patch('speech.subprocess.Popen',return_value=process):
            with self.assertRaises(SpeechCancelled):
                speaker.speak('Test')
        process.terminate.assert_called_once()
        with patch('speech.command',return_value=['voice']),patch('speech.subprocess.Popen') as launch:
            with self.assertRaises(SpeechCancelled):
                speaker.speak('Test',should_continue=lambda:False)
        launch.assert_not_called()

    def test_announcement_is_brief_and_labels_simulations_and_updates(self):
        text = announcement(alert(simulated=True),[LocationProfile(name='Home'),LocationProfile(name='Family')],'Extended')
        self.assertIn('Simulation. Extended. Tornado Warning for Cook County.',text)
        self.assertIn('Until',text)
        self.assertNotIn('Seek shelter',text)


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),'GUI tests require a desktop display')
class ExplanationSpeechGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(Path(self.directory.name)/'history.db'))
        # Most tests model an already-running session before the fixture's
        # 10:00 UTC issue time. Startup regressions below use the real Start action.
        self.ui.speech_started_at = datetime(2026,10,16,9,tzinfo=timezone.utc)
        self.ui.app.root.update()
        self.voice = patch.object(self.ui.speaker,'speak').start()
        self.addCleanup(patch.stopall)
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, predicate):
        deadline = time.monotonic()+4
        while not predicate() and time.monotonic()<deadline:
            self.ui.app.root.update()
            time.sleep(.005)
        self.assertTrue(predicate())

    def receive(self, items, wait_voice=True):
        self.ui.running = True
        self.ui.received(self.ui.generation,({a['id']:a for a in items},''))
        self.pump(lambda:not self.ui.busy)
        self.pump(lambda:not self.ui.delivery_busy)
        if wait_voice:
            self.pump(lambda:not self.ui.speech_busy and not self.ui.speech_pending)
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def test_default_speech_is_off_and_silent_reasons_are_visible(self):
        a = alert()
        self.receive([a])
        self.voice.assert_not_called()
        self.ui.show_notification_explanation(a)
        text = next(c for c in self.ui.app._windows[-1]._children if isinstance(c,TextArea)).get()
        self.assertIn('Speech is switched off',text)
        self.assertIn('Tornado Warning selected',text)
        self.assertIn('Submitted',text)
        wait_view(self.ui,self.ui.delivery_panel)
        self.assertIn('Why this notification:',self.ui.delivery_panel.details.get())

    def test_startup_backlog_is_silent_and_only_post_start_alerts_are_spoken(self):
        self.ui.profile.speech = True
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        started = self.ui.speech_started_at
        backlog = [alert(id=f'old-{i}',sent=(started-timedelta(hours=1)).isoformat()) for i in range(40)]
        self.receive(backlog)
        self.voice.assert_not_called()
        self.assertFalse(self.ui.speech_pending)
        receipts = [r for r in self.ui.history.delivery_rows(limit=500) if r['channel']=='speech']
        self.assertEqual(len(receipts),40)
        self.assertTrue(all(r['state']=='skipped' for r in receipts))
        self.assertTrue(all('after this monitoring session started' in r['reason'] for r in receipts))
        self.assertEqual(len(self.ui.snapshot),40)
        self.ui.service.deliver_desktop.assert_called()
        new = alert(id='new',sent=(started+timedelta(microseconds=1)).isoformat())
        self.receive(backlog+[new])
        self.voice.assert_called_once()
        self.assertEqual(next(r for r in self.ui.history.delivery_rows(limit=500)
                              if r['id']=='new' and r['channel']=='speech')['state'],'sent')

    def test_new_alert_on_first_refresh_is_spoken_but_unknown_issue_time_is_not(self):
        self.ui.profile.speech = True
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        started = self.ui.speech_started_at
        self.receive([alert(id='unknown',sent='Unknown'),
                      alert(id='new',sent=(started+timedelta(microseconds=1)).isoformat())])
        self.voice.assert_called_once()
        rows = [r for r in self.ui.history.delivery_rows() if r['channel']=='speech']
        self.assertEqual({r['id']:r['state'] for r in rows},{'new':'sent','unknown':'skipped'})

    def test_restart_retires_failed_speech_and_establishes_a_new_cutoff(self):
        self.ui.profile.speech = True
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        first_start = self.ui.speech_started_at
        a = alert(id='earlier-session',sent=(first_start+timedelta(microseconds=1)).isoformat())
        self.voice.side_effect = RuntimeError('voice offline')
        self.receive([a])
        old = next(r for r in self.ui.history.delivery_rows() if r['channel']=='speech')
        self.assertEqual(old['state'],'failed')
        self.ui.toggle_monitoring()
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        self.assertGreater(self.ui.speech_started_at,first_start)
        self.voice.side_effect = None
        self.receive([a])
        self.voice.assert_called_once()
        receipt = self.ui.history.delivery(old['id'],old['version'],old['profile'],'speech')
        self.assertEqual(receipt['state'],'skipped')
        # Even a stale job retained outside the normal queue cannot play.
        self.ui.send_notifications(self.ui.generation,[(a,old['version'],old['profile'],'speech','New')],True)
        self.voice.assert_called_once()
        new = alert(id='after-resume',sent=(self.ui.speech_started_at+timedelta(microseconds=1)).isoformat())
        self.receive([a,new])
        self.assertEqual(self.voice.call_count,2)

    def test_new_noncritical_event_on_first_refresh_uses_speech_session_policy(self):
        self.ui.profile.speech = True
        self.ui.profile.speech_events = None
        self.ui.choices['Flood Warning'].set(True)
        with patch.object(self.ui,'poll'):
            self.ui.toggle_monitoring()
        self.receive([alert(event='Flood Warning',sent=(self.ui.speech_started_at+timedelta(microseconds=1)).isoformat())])
        self.voice.assert_called_once()
        self.ui.service.deliver_sound.assert_not_called()
        self.ui.service.deliver_desktop.assert_not_called()

    def test_speech_is_deduplicated_per_version_and_overlap(self):
        self.ui.profile.speech = True
        self.ui.profiles.append(LocationProfile(name='Family',speech=True))
        a = alert()
        self.receive([a])
        self.receive([a])
        self.voice.assert_called_once()
        self.assertIn('Cook County',self.voice.call_args.args[0])
        self.assertNotIn('United States',self.voice.call_args.args[0])
        version = self.ui.history.get_alert(a['id'])['version']
        self.assertEqual(set(json.loads(self.ui.history.submission(a['id'],version,'speech')['members'])),
                         {'Family','United States'})
        self.receive([dict(a,headline='Changed')])
        self.assertEqual(self.voice.call_count,2)
        self.assertNotIn('Matched nationwide',self.ui.feed.get())

    def test_speech_failure_retries_independently_and_manual_retry_does_not_replay_audio(self):
        self.ui.profile.speech = True
        self.voice.side_effect = RuntimeError('voice offline')
        for _ in range(4):
            self.receive([alert()])
        self.assertEqual(self.voice.call_count,3)
        self.ui.service.deliver_sound.assert_called_once()
        self.ui.service.deliver_desktop.assert_called_once()
        row = next(r for r in self.ui.history.delivery_rows() if r['channel']=='speech')
        self.voice.side_effect = None
        self.ui.retry_delivery(row)
        self.pump(lambda:not self.ui.speech_busy)
        self.assertEqual(self.voice.call_count,4)
        self.ui.service.deliver_sound.assert_called_once()

    def test_slow_speech_does_not_block_new_desktop_notifications(self):
        self.ui.profile.speech = True
        entered = threading.Event()
        def slow(*args,**kwargs):
            entered.set()
            self.release.wait(3)
        self.voice.side_effect = slow
        first = alert(id='first')
        self.receive([first],wait_voice=False)
        self.pump(entered.is_set)
        self.receive([first,alert(id='second')],wait_voice=False)
        self.assertTrue(self.ui.speech_busy)
        self.assertEqual(self.ui.service.deliver_desktop.call_count,2)
        self.release.set()
        self.pump(lambda:not self.ui.speech_busy and not self.ui.speech_pending)

    def test_preferences_save_and_older_location_editor_preserves_speech_selection(self):
        self.ui.edit_profile()
        window = self.ui.app._windows[-1]
        form = next(c for c in window._children if isinstance(c,Form))
        self.ui.edit_speech_events()
        prefs = self.ui.speech_preferences
        prefs.enabled.set(True)
        prefs.none()
        prefs.choices['Tornado Warning'].set(True)
        prefs.save()
        save = next(c for c in form.actions._children if c.widget.cget('text') == 'Save location')
        save.widget.invoke()
        self.assertTrue(self.ui.profile.speech)
        self.assertEqual(self.ui.profile.speech_events,['Tornado Warning'])
        self.assertIsNone(self.ui.profile.sound_events)

    def test_cancelled_queued_alert_is_not_spoken(self):
        self.ui.profile.speech = True
        entered = threading.Event()
        def slow(*args,**kwargs):
            entered.set();self.release.wait(3)
        self.voice.side_effect = slow
        a,b = alert(id='a'),alert(id='b')
        self.receive([a],wait_voice=False)
        self.pump(entered.is_set)
        self.receive([a,b],wait_voice=False)
        self.receive([a,alert(id='cancel',message_type='Cancel',references=[{'identifier':'b'}])],wait_voice=False)
        self.release.set()
        self.pump(lambda:not self.ui.speech_busy and not self.ui.speech_pending)
        self.voice.assert_called_once()

    def test_queue_is_bounded_and_waits_for_fresh_data(self):
        self.ui.running = True
        jobs = []
        for i in range(100):
            a = alert(id=str(i),event=f'Synthetic {i} Warning')
            version,_,_ = self.ui.history.observe(a)
            jobs.append((a,version,self.ui.profile.id,'speech','New'))
        self.ui.enqueue_speech(self.ui.generation,jobs)
        self.assertEqual(len(self.ui.speech_pending),32)
        self.assertFalse(self.ui.speech_busy)
        self.voice.assert_not_called()
        self.ui.speech_pending.clear()
