"""Start and close the real desktop app with temporary state and dummy audio.

Run from the repository root with a desktop display (or xvfb-run on Linux).
No live requests, speech, or desktop notifications are sent.
"""
import logging
import os
from pathlib import Path
import sys
import tempfile

os.environ['SDL_AUDIODRIVER'] = 'dummy'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame
from main import StormwatchApp


def main():
    previous = {name: os.environ.get(name) for name in ('LOCALAPPDATA','XDG_STATE_HOME')}
    try:
        with tempfile.TemporaryDirectory() as directory:
            os.environ['LOCALAPPDATA'] = os.environ['XDG_STATE_HOME'] = directory
            ui = StormwatchApp()
            try:
                ui.app.root.update()
                expected = Path(directory)/'Stormwatch'
                assert ui.history.path == expected/'processed-alerts.sqlite3'
                assert (expected/'storm_monitor.log').exists()
                assert len(ui.app.root._stormwatch_icons) == 4
                ui.commands.show_tab('Map')
                ui.app.root.update()
                assert ui.map.canvas.winfo_ismapped()
                window = ui.commands.general()
                ui.app.root.update()
                window.close()
                ui.service.deliver_sound()
                assert pygame.mixer.get_init()
                assert pygame.mixer.music.get_busy()
                assert not ui.running
                assert ui.history.history_count() == 0
            finally:
                ui.close()
                ui.cleanup_thread.join(timeout=10)
                assert not ui.cleanup_thread.is_alive(), 'Application cleanup did not finish'
                # Windows requires the log file handle closed before deleting test state.
                logger = logging.getLogger('WeatherService')
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)
            print(f'{sys.platform}: native app startup, icon, map, settings, writable state, MP3 decoding, and shutdown passed.')
            print('Dummy audio verifies decoding/submission, not physical speakers. Optional tray, notification service, and speech need desktop integration checks.')
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name,None)
            else:
                os.environ[name] = value


if __name__ == '__main__':
    main()
