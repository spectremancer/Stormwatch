"""Prevent concurrent CLI instances from applying a restore or competing for audio."""
class InstanceLock:
    def __init__(self, directory):
        import sys
        directory.mkdir(parents=True,exist_ok=True)
        self.stream = (directory/'application.lock').open('a+b')
        self.windows = sys.platform=='win32'
        try:
            if self.windows:
                import msvcrt
                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b'0')
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError('Stormwatch is already running. Restore it from the system tray.') from None

    def close(self):
        self.stream.close()
