"""Optional tray integration and explicit Windows launch-at-login setting."""
from pathlib import Path
import subprocess
import sys
import threading


def configure_identity(root):
    """Apply the project icon to Tk windows and a separate Windows taskbar group."""
    import tkinter as tk
    from PIL import Image, ImageTk
    path = Path(__file__).with_name('icon.ico')
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Stormwatch.WeatherIntelligence')
    with Image.open(path) as source:
        images = [ImageTk.PhotoImage(source.convert('RGBA').resize((size,size)), master=root)
                  for size in (16,32,48,64)]
    root.iconphoto(True, *images)
    # Keep Tk image objects alive; default applies to child windows too.
    root._stormwatch_icons = images
    if sys.platform == 'win32':
        try:
            root.iconbitmap(default=str(path))
        except tk.TclError:
            pass  # iconphoto still supplies the small and large window icons.


def set_login(enabled):
    if sys.platform != "win32":
        raise RuntimeError("Launch at login is currently supported on Windows only.")
    import winreg
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    command = subprocess.list2cmdline([str(executable), str(Path(__file__).with_name("main.py")), "--monitor"])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "Stormwatch", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "Stormwatch")
            except FileNotFoundError:
                pass


class Tray:
    def __init__(self, app, show, quit, ready, failed):
        self.app, self.show, self.quit = app, show, quit
        self.ready, self.failed = ready, failed
        self.icon = None
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import pystray
            if sys.platform == "darwin":
                raise RuntimeError("Background tray mode currently targets Windows and Linux.")
            if not pystray.Icon.HAS_MENU:
                raise RuntimeError("This desktop tray backend has no menu support. Use a menu-capable tray backend.")
            from PIL import Image
            with Image.open(Path(__file__).with_name('icon.ico')) as source:
                image = source.convert('RGBA').resize((64,64))
            self.icon = pystray.Icon("Stormwatch", image, "Stormwatch monitoring", pystray.Menu(
                pystray.MenuItem("Open Stormwatch", lambda *_: self.app.call_soon(self.show), default=True),
                pystray.MenuItem("Quit", lambda *_: self.app.call_soon(self.quit))))

            def setup(icon):
                icon.visible = True
                self.app.call_soon(self.ready)
            self.icon.run(setup=setup)
        except Exception as error:
            self.app.call_soon(self.failed, error)

    def stop(self):
        if self.icon:
            self.icon.stop()
