"""Offline acceptance check that also runs inside the packaged executable."""
import json
import hashlib
import sys
import logging
import os
from pathlib import Path
import tempfile
from version import IDENTITY, BUILD_INFO


def run(report):
    previous = {key:os.environ.get(key) for key in ('LOCALAPPDATA','XDG_STATE_HOME','SDL_AUDIODRIVER')}
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    try:
        with tempfile.TemporaryDirectory(prefix='stormwatch-self-test-') as directory:
            os.environ['LOCALAPPDATA'] = os.environ['XDG_STATE_HOME'] = directory
            from main import StormwatchApp
            from help_guide import load_guide
            from place_search import search_places
            from map_context import read_layer
            ui = StormwatchApp()
            try:
                ui.app.root.update()
                ui.commands.show_tab('Map')
                ui.app.root.update()
                assert ui.app.root._stormwatch_icons
                assert load_guide() and search_places('60601')
                assert read_layer('states') and read_layer('counties')
                ui.service.deliver_sound()
                assert not ui.running
                payload = dict(application=IDENTITY,status='passed',executable_sha256=None,
                    source_commit=BUILD_INFO['commit'],source_dirty=BUILD_INFO['dirty'],checks=[
                    'GUI startup','icons','bundled guide','city search','state/county geometry',
                    'map rendering','temporary writable state','MP3 decoding','clean shutdown'])
            finally:
                ui.close()
                ui.cleanup_thread.join(timeout=45)
                assert not ui.cleanup_thread.is_alive(),'Cleanup did not finish'
                for handler in list(logging.getLogger('WeatherService').handlers):
                    handler.close()
                    logging.getLogger('WeatherService').removeHandler(handler)
        if getattr(sys,'frozen',False):
            with Path(sys.executable).open('rb') as executable:
                payload['executable_sha256'] = hashlib.file_digest(executable,'sha256').hexdigest()
        Path(report).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    finally:
        for key,value in previous.items():
            if value is None:
                os.environ.pop(key,None)
            else:
                os.environ[key] = value
