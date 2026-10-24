"""Immutable display plans; full provider geometry remains unchanged for matching."""
from dataclasses import dataclass
from event_catalog import event_category
from locations import rings


@dataclass
class Outline:
    bounds: tuple
    points: tuple
    category: str
    alerts: list


def outline_plan(rows):
    groups={}
    for row in rows:
        alert=row['alert']
        category=event_category(alert['event'])
        for polygon in rings(alert.get('geometry')):
            for ring in polygon:
                points=tuple((point[0],point[1]) for point in ring)
                if len(points)<3:continue
                key=(category,points)
                existing=groups.get(key)
                if existing is not None:
                    existing.alerts.append(alert)
                else:
                    xs,ys=zip(*points)
                    groups[key]=Outline((min(xs),min(ys),max(xs),max(ys)),points,category,[alert])
    return tuple(groups.values())


class PreparedRows(list):
    def __init__(self, rows):
        super().__init__(rows)
        self.map_plan=outline_plan(rows)
