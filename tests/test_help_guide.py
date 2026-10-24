"""Verify the bundled guide, useful search, native navigation, and menu integration."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from help_guide import Answer, HelpGuide, load_guide


class GuideContentTests(unittest.TestCase):
    def test_comprehensive_content_has_unique_complete_questions(self):
        answers = load_guide()
        self.assertGreaterEqual(len(answers), 150)
        self.assertGreaterEqual(len({a.topic for a in answers}), 25)
        self.assertEqual(len(answers), len({(a.topic, a.question) for a in answers}))
        self.assertTrue(all(a.body.strip() and a.question.endswith('?') for a in answers))
        for topic in ('Spoken alerts', 'Seven-day downloads', 'Data & backup', 'Troubleshooting'):
            self.assertGreaterEqual(sum(a.topic == topic for a in answers), 5)

    def test_search_is_case_insensitive_and_requires_all_words(self):
        answer = Answer('Radar', 'How do I view it?', 'RainViewer tiles require a connection.')
        self.assertTrue(answer.matches('RADAR rainviewer'))
        self.assertTrue(answer.matches(''))
        self.assertFalse(answer.matches('radar tornado'))
        self.assertTrue(any(a.matches('tornado history') for a in load_guide()))
        self.assertTrue(any(a.matches('5000') or a.matches('5,000') for a in load_guide()))

    def test_parser_rejects_incomplete_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.md'
            path.write_text('# Topic\n## Empty?\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_guide(path)


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Requires a desktop')
class GuideWindowTests(unittest.TestCase):
    def setUp(self):
        from TkFlow import App
        self.app = App('Guide test')
        self.guide = HelpGuide(SimpleNamespace(app=self.app))
        self.app.root.update()

    def tearDown(self):
        self.app.close()

    def test_topic_navigation_search_highlighting_and_readonly(self):
        guide = self.guide
        self.assertIn('How do I get started', guide.area.get())
        guide.navigation.tree.selection_set('Spoken alerts')
        self.app.root.update()
        self.assertIn('How are many simultaneous alerts aggregated?', guide.area.get())
        guide.search.set('rainviewer tiles')
        self.app.root.update()
        self.assertTrue(guide.filtered)
        self.assertTrue(all(a.matches('rainviewer tiles') for a in guide.filtered))
        self.assertTrue(guide.area.text.tag_ranges('match'))
        self.assertEqual(str(guide.area.text.cget('state')), 'disabled')
        guide.search.set('no-such-topic-xyz')
        self.app.root.update()
        self.assertEqual(guide.navigation.tree.get_children(), ())
        self.assertIn('Try fewer words', guide.area.get())
        guide.search.set('')
        self.app.root.update()
        self.assertEqual(len(guide.navigation.tree.get_children()), len(guide.topics))
        guide.copy_topic()
        self.assertIn(guide.heading.get(), guide.window.root.clipboard_get())

    def test_hide_reopen_and_small_layout(self):
        guide = self.guide
        guide.show('Seven-day downloads')
        guide.search.set('download')
        guide.hide()
        self.assertEqual(guide.window.root.state(), 'withdrawn')
        guide.show()
        self.assertEqual(guide.search.get(), 'download')
        self.assertEqual(guide.current_topic, 'Seven-day downloads')
        guide.window.root.geometry('850x550')
        self.app.root.update()
        self.assertGreater(guide.area.text.winfo_width(), 450)
        self.assertGreater(guide.area.text.winfo_height(), 250)
        guide.show('Quick start')
        self.assertEqual(guide.search.get(), '')
        self.assertEqual(guide.current_topic, 'Quick start')


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Requires a desktop')
class GuideMenuTests(unittest.TestCase):
    def test_help_routes_reuse_window_without_monitoring_and_survive_disposal(self):
        from alert_history import AlertHistory
        from main import StormwatchApp
        with tempfile.TemporaryDirectory() as directory:
            service = Mock(interval=60)
            ui = StormwatchApp(service, AlertHistory(Path(directory) / 'history.db'))
            try:
                ui.commands.groups['Help'].widget.invoke('Documentation')
                guide = ui.commands.documentation
                ui.app.root.update()
                ui.commands.shortcuts()
                self.assertEqual(guide.current_topic, 'Keyboard & menus')
                guide.hide()
                ui.commands.open_documentation()
                self.assertIs(ui.commands.documentation, guide)
                ui.commands.getting_started()
                self.assertEqual(guide.current_topic, 'Quick start')
                for skin in ('Classic', 'Navy', 'Forest'):
                    ui.appearance.set(skin)
                    ui.app.root.update()
                    self.assertEqual(guide.area.text.cget('bg'), ui.app.palette['surface'])
                    self.assertEqual(guide.area.text.cget('fg'), ui.app.palette['text'])
                    self.assertEqual(guide.area.text.tag_cget('match', 'foreground'), '#000000')
                guide.search.set('radar')
                guide.window.root.focus_force()
                guide.window.root.event_generate('<Control-f>')
                ui.app.root.update()
                self.assertEqual(ui.app.root.focus_get(), guide.search.widget)
                self.assertFalse(ui.running)
                service.fetch_alerts.assert_not_called()
                self.assertEqual(ui.history.history_count(), 0)
                guide.window.close()
                ui.commands.open_documentation()
                self.assertIsNot(ui.commands.documentation, guide)
            finally:
                ui.close()
                ui.cleanup_thread.join(timeout=5)
