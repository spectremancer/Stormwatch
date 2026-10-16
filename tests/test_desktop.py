import sys
import unittest
from unittest.mock import Mock, patch

from desktop import Tray, set_login


class DesktopTests(unittest.TestCase):
    def test_windows_login_is_explicit_and_per_user(self):
        registry = Mock()
        registry.CreateKey.return_value.__enter__ = Mock(return_value="key")
        registry.CreateKey.return_value.__exit__ = Mock(return_value=False)
        with patch("desktop.sys.platform", "win32"), patch.dict(sys.modules, {"winreg":registry}):
            set_login(True)
            registry.CreateKey.assert_called_once_with(registry.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run")
            self.assertIn("--monitor", registry.SetValueEx.call_args.args[-1])
            set_login(False)
            registry.DeleteValue.assert_called_with("key", "Stormwatch")

    def test_unsupported_tray_backend_reports_failure_without_hiding(self):
        pystray = Mock()
        pystray.Icon.HAS_MENU = False
        app, show, quit, ready, failure = (Mock() for _ in range(5))
        tray = Tray(app, show, quit, ready, failure)
        with patch.dict(sys.modules, {"pystray":pystray}):
            tray._run()
        app.call_soon.assert_called_once()
        self.assertIs(app.call_soon.call_args.args[0], failure)
        ready.assert_not_called()
