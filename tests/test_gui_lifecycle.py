"""Exercise native Tk teardown in a subprocess so regressions cannot kill the runner."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
import weakref

from TkFlow._workers import WorkerPool


class WorkerLifetimeTests(unittest.TestCase):
    def test_idle_worker_releases_completed_bound_method_and_result(self):
        class Owner:
            def work(self):
                return self

        pool = WorkerPool(1, 4)
        try:
            owner = Owner()
            reference = weakref.ref(owner)
            future = pool.submit(owner.work)
            self.assertIs(future.result(timeout=5), owner)
            del owner, future
            pool._tasks.join()
            self.assertIsNone(reference(), 'An idle worker retained its completed GUI owner')
        finally:
            pool.shutdown()
            for thread in pool._threads:
                thread.join(timeout=5)


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI tests require DISPLAY')
class GuiLifetimeTests(unittest.TestCase):
    def test_closed_gui_collected_by_worker_and_interpreters_reclaimed_on_main(self):
        script = textwrap.dedent('''
            import gc
            import threading
            import weakref
            from TkFlow import App, Checkbox, Dropdown, TextInput, Window
            from TkFlow import _tk_lifetime

            for iteration in range(20):
                app = App()
                window = Window(app)
                field = TextInput(window, on_change=lambda value: None)
                Checkbox(app)
                Dropdown(app, ['30 seconds', '60 seconds'])
                reference = weakref.ref(app)
                app.close()
                del field, window, app
                # Force the exact failure condition, without changing GC
                # thresholds or disabling collection elsewhere in the app.
                worker = threading.Thread(target=gc.collect)
                worker.start()
                worker.join()
                assert reference() is None, 'Closed application was retained'
                _tk_lifetime.reap()
                assert not _tk_lifetime._interpreters, 'Tcl interpreters leaked'

            # Closing must remain nonblocking while work finishes, including
            # an exception whose traceback retains a bound GUI owner.
            class Owner:
                def __init__(self):
                    self.app = App()
                    self.started = threading.Event()
                    self.release = threading.Event()
                def work(self):
                    self.started.set()
                    assert self.release.wait(5)
                    raise ValueError('finished after close')

            owner = Owner()
            future = owner.app.run_in_thread(owner.work)
            assert owner.started.wait(5)
            owner.app.close()
            owner.release.set()
            assert isinstance(future.exception(timeout=5), ValueError)
            pool = owner.app._workers
            pool._tasks.join()
            for thread in pool._threads:
                thread.join(timeout=5)
                assert not thread.is_alive()
            del future, owner, pool, thread
            worker = threading.Thread(target=gc.collect)
            worker.start()
            worker.join()
            _tk_lifetime.reap()
            assert not _tk_lifetime._interpreters, 'Failed worker retained Tcl'
        ''')
        result = subprocess.run(
            [sys.executable, '-B', '-X', 'faulthandler', '-c', script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('Exception ignored', result.stderr)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
