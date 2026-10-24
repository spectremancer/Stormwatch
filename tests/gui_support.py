"""Wait for an asynchronous view without blocking its GUI callback dispatcher."""
import time


def wait_view(owner, panel, refresh=True):
    if refresh:
        panel.refresh()
    deadline = time.monotonic()+6
    while (panel.query.future is not None or panel.query.pending is not None) and time.monotonic()<deadline:
        owner.app.root.update()
        time.sleep(.001)
    assert panel.query.future is None and panel.query.pending is None, 'View query did not finish'
