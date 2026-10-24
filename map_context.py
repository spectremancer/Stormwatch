"""Offline geographic context loaded outside Tk; viewport-culling limits draw work."""
import json
from pathlib import Path
from types import SimpleNamespace
from locations import rings

CITIES = [('Seattle',47.61,-122.33),('Portland',45.52,-122.68),('San Francisco',37.77,-122.42),
 ('Los Angeles',34.05,-118.24),('San Diego',32.72,-117.16),('Las Vegas',36.17,-115.14),
 ('Phoenix',33.45,-112.07),('Denver',39.74,-104.99),('Billings',45.78,-108.50),
 ('Salt Lake City',40.76,-111.89),('Dallas',32.78,-96.80),('Houston',29.76,-95.37),
 ('Oklahoma City',35.47,-97.52),('Kansas City',39.10,-94.58),('Minneapolis',44.98,-93.27),
 ('Chicago',41.88,-87.63),('Detroit',42.33,-83.05),('St. Louis',38.63,-90.20),
 ('Memphis',35.15,-90.05),('New Orleans',29.95,-90.07),('Atlanta',33.75,-84.39),
 ('Miami',25.76,-80.19),('Tampa',27.95,-82.46),('Orlando',28.54,-81.38),
 ('Charlotte',35.23,-80.84),('Washington',38.91,-77.04),('New York',40.71,-74.01),
 ('Boston',42.36,-71.06),('Pittsburgh',40.44,-79.99),('Nashville',36.16,-86.78),
 ('Anchorage',61.22,-149.90),('Honolulu',21.31,-157.86)]


def read_layer(name):
    data = json.loads((Path(__file__).with_name('data')/f'us_{name}.geojson').read_text())
    result = []
    for feature in data['features']:
        for polygon in rings(feature['geometry']):
            for ring in polygon:
                points = [(lon,lat) for lon,lat,*_ in ring]
                if points:
                    xs,ys = zip(*points)
                    result.append(((min(xs),min(ys),max(xs),max(ys)),points))
    return result


class MapContext:
    def __init__(self, alert_map):
        self.map = alert_map
        self.enabled = dict(states=True,counties=False,cities=True)
        self.layers = {}
        self.loading = set()

    def draw(self, palette):
        view = self.map.viewport()
        west,south,east,north = view.bounds()
        for name in ('states','counties'):
            if not self.enabled[name] or name=='counties' and view.scale<20:
                continue
            if name not in self.layers:
                if name not in self.loading:
                    self.loading.add(name)
                    def done(result, layer=name):
                        self.loading.discard(layer)
                        self.layers[layer] = result
                        if not self.map._destroyed:
                            self.map.request_draw()
                    try:
                        self.map.app.run_in_thread(read_layer,name,on_result=done,
                            on_error=lambda error,layer=name:self.loading.discard(layer))
                    except RuntimeError:
                        self.loading.discard(name)
                continue
            for (left,bottom,right,top),points in self.layers[name]:
                if right<west or left>east or top<south or bottom>north:
                    continue
                coords = [value for lon,lat in points for value in self.map.project(lon,lat)]
                if len(coords)>=4:
                    self.map.canvas.create_line(*coords,fill=palette['shore'],width=1,
                                                tags='geography')
        if self.enabled['cities'] and not self.map.place_labels:
            return [SimpleNamespace(city=city,latitude=lat,longitude=lon) for city,lat,lon in CITIES]
        return self.map.place_labels
