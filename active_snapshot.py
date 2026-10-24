"""Prepare large current-alert views without decoding geometry on Tk's thread."""
from dashboard_views import active_sort_key
from map_geometry import PreparedRows


def active_rows(store, profiles, mode):
    with store.read_snapshot() as reader:
        rows=reader.rows(active_only=True)
    result=[]
    for row in rows:
        names=[profile.name for profile in profiles if profile.matches(row['alert'])]
        if names:result.append(dict(row,locations=names))
    return PreparedRows(sorted(result,key=lambda row:active_sort_key(row,mode)))
