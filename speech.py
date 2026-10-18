"""Offline native speech with bounded execution and cancellation; no shell interpolation."""
import platform
import shutil
import subprocess
import threading
from datetime import datetime


class SpeechCancelled(RuntimeError):
    pass


def issued_after(alert, started_at):
    """Only authoritative, timezone-aware issue times can qualify for live speech."""
    try:
        issued = datetime.fromisoformat(alert.get('sent','').replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError):
        return False
    return bool(started_at and issued.tzinfo is not None and issued>started_at)


def announcement(alert, profiles, kind='New'):
    from alert_history import instant
    names = [p.name for p in profiles]
    location = ', '.join(names[:5]) + (f', and {len(names)-5} other saved locations' if len(names)>5 else '')
    end = instant(alert.get('ends') or alert.get('expires'))
    until = f" Until {end.astimezone():%B %d at %I:%M %p %Z}." if end else ''
    prefix = 'Simulation. ' if alert.get('simulated') else ''
    update = f'{kind}. ' if kind != 'New' else ''
    return f"{prefix}{update}{alert['event']} for {location[:220]}.{until}"


def command():
    system = platform.system()
    if system == 'Windows':
        script = ("$ErrorActionPreference = 'Stop'; "
                  '[Console]::InputEncoding = New-Object System.Text.UTF8Encoding; '
                  'Add-Type -AssemblyName System.Speech; '
                  '$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                  'try { $voice.SetOutputToDefaultAudioDevice(); $voice.Speak([Console]::In.ReadToEnd()) } '
                  'finally { $voice.Dispose() }')
        return ['powershell.exe','-NoProfile','-NonInteractive','-Command',script]
    if system == 'Darwin':
        return ['/usr/bin/say','-f','-']
    executable = shutil.which('espeak-ng') or shutil.which('espeak')
    if executable:
        return [executable,'--stdin']
    raise RuntimeError('No local speech engine is available. On Linux, install espeak-ng or espeak. Windows uses System.Speech; macOS uses say.')


class SpeechService:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.epoch = 0

    def speak(self, text, should_continue=None):
        args = command()
        with self.lock:
            if should_continue is not None and not should_continue():
                raise SpeechCancelled('Speech stopped.')
            if self.process is not None:
                raise RuntimeError('A speech announcement is already running.')
            epoch = self.epoch
            try:
                process = subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if platform.system() == 'Windows' else 0)
            except OSError:
                raise RuntimeError('The local speech engine could not be started. Check its installation and audio output.') from None
            self.process = process
        try:
            try:
                process.communicate(text.encode('utf-8'),timeout=45)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise RuntimeError('Speech timed out after 45 seconds. Check the local voice engine.') from None
            with self.lock:
                if epoch != self.epoch:
                    raise SpeechCancelled('Speech stopped.')
            if process.returncode:
                raise RuntimeError('The local speech engine reported a failure. Check voices and the default audio device.')
        finally:
            with self.lock:
                self.process = None

    def stop(self):
        with self.lock:
            self.epoch += 1
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass
