"""Platform boundaries: writable state, notifications, and executable startup."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from application_paths import state_directory
from desktop import set_login
from WeatherService import WeatherService


class PlatformCompatibilityTests(unittest.TestCase):
    def test_windows_and_linux_state_roots_are_separate_from_assets(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'LOCALAPPDATA':directory+'/windows','XDG_STATE_HOME':directory+'/linux'}):
            with patch('application_paths.sys.platform','win32'):
                self.assertEqual(state_directory(),Path(directory)/'windows'/'Stormwatch')
            with patch('application_paths.sys.platform','linux'):
                self.assertEqual(state_directory(),Path(directory)/'linux'/'Stormwatch')

    def test_packaged_windows_startup_uses_executable_without_temporary_main_script(self):
        registry = Mock()
        registry.CreateKey.return_value.__enter__ = Mock(return_value='key')
        registry.CreateKey.return_value.__exit__ = Mock(return_value=False)
        with patch('desktop.sys.platform','win32'), patch('desktop.sys.frozen',True,create=True), \
             patch('desktop.sys.executable','C:/Program Files/Stormwatch/Stormwatch.exe'), \
             patch.dict('sys.modules',{'winreg':registry}):
            set_login(True)
        command = registry.SetValueEx.call_args.args[-1]
        self.assertIn('Stormwatch.exe',command)
        self.assertIn('--monitor',command)
        self.assertNotIn('main.py',command)
        self.assertNotIn('_MEI',command)
        self.assertTrue(command.startswith('"'))

    def test_service_reads_legacy_state_but_saves_only_to_user_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = WeatherService.__new__(WeatherService)
            service.base_dir = root/'installed'
            service.base_dir.mkdir()
            service.state_dir = root/'user'
            service.state_dir.mkdir()
            service.state_file = service.state_dir/'storm_alert_state.json'
            service.logger = Mock()
            legacy = service.base_dir/'storm_alert_state.json'
            legacy.write_text(json.dumps({'old':'fingerprint'}))
            self.assertEqual(service._load_state(),{'old':'fingerprint'})
            service._save_state({'new':'fingerprint'})
            self.assertEqual(json.loads(service.state_file.read_text()),{'new':'fingerprint'})
            self.assertEqual(json.loads(legacy.read_text()),{'old':'fingerprint'})
            self.assertEqual(service._load_state(),{'new':'fingerprint'})

    def test_linux_notification_uses_checked_argument_list_and_never_shell_text(self):
        service = WeatherService.__new__(WeatherService)
        with patch('WeatherService.platform.system',return_value='Linux'), \
             patch('WeatherService.shutil.which',return_value='/usr/bin/notify-send'), \
             patch('WeatherService.subprocess.run') as run:
            service.deliver_desktop({'event':'Gale Warning','area':"Family's home; $(echo ignored)"},location='Home')
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1],"Home: Family's home; $(echo ignored)")
        self.assertEqual(args[0][-3],'--')
        self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['timeout'],10)
        self.assertNotIn('shell',kwargs)

    def test_linux_notification_missing_tool_or_failed_session_is_retryable(self):
        service = WeatherService.__new__(WeatherService)
        alert = dict(event='Tornado Warning',area='Cook County')
        with patch('WeatherService.platform.system',return_value='Linux'):
            with patch('WeatherService.shutil.which',return_value=None), self.assertRaisesRegex(RuntimeError,'libnotify-bin'):
                service.deliver_desktop(alert)
            for failure in (subprocess.CalledProcessError(1,['notify-send']), subprocess.TimeoutExpired(['notify-send'],10)):
                with patch('WeatherService.shutil.which',return_value='/usr/bin/notify-send'), \
                     patch('WeatherService.subprocess.run',side_effect=failure), self.assertRaisesRegex(RuntimeError,'D-Bus'):
                    service.deliver_desktop(alert)

    def test_windows_notification_keeps_native_backend(self):
        service = WeatherService.__new__(WeatherService)
        with patch('WeatherService.platform.system',return_value='Windows'), \
             patch('WeatherService.notification.notify') as notify:
            service.deliver_desktop(dict(event='Tornado Warning',area='Cook County'),location='Home')
        self.assertEqual(notify.call_args.kwargs['app_name'],'Stormwatch')
        self.assertEqual(notify.call_args.kwargs['message'],'Home: Cook County')
