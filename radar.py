"""Bounded RainViewer past-radar loading, projected onto the offline alert map.

Only observed frames are used. No radar-based warning or arrival predictions.
Network and Pillow work run outside Tk's thread.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import math
import re
import threading

from PIL import Image, ImageDraw
import requests

METADATA_URL = 'https://api.rainviewer.com/public/weather-maps.json'
TILE_HOST = 'https://tilecache.rainviewer.com'
MAX_FRAMES, MAX_TILES, CACHE_TILES = 6, 12, 96
HEADERS = {'User-Agent': 'Stormwatch/1.0', 'Accept': 'application/json,image/png'}


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    longitude: float
    latitude: float
    scale: float

    def bounds(self):
        return (self.longitude-self.width/self.scale/2, self.latitude-self.height/self.scale/2,
                self.longitude+self.width/self.scale/2, self.latitude+self.height/self.scale/2)


def mercator_y(latitude, world):
    lat = math.radians(max(-85.05112878, min(85.05112878, latitude)))
    return (1-math.asinh(math.tan(lat))/math.pi)/2*world


def tile_layout(view):
    west, south, east, north = view.bounds()
    west, east = max(-180, west), min(180, east)
    south, north = max(-85.05112878, south), min(85.05112878, north)
    if west >= east or south >= north:
        raise ValueError('Pan the map into the radar coverage latitude/longitude range.')
    zoom = min(7, max(0, round(math.log2(view.scale*360/256))))
    while True:
        world = 256*2**zoom
        x0, x1 = int((west+180)/360*world)//256, min(2**zoom-1,int((east+180)/360*world)//256)
        y0 = max(0,int(mercator_y(north,world))//256)
        y1 = min(2**zoom-1,int(mercator_y(south,world))//256)
        if (x1-x0+1)*(y1-y0+1) <= MAX_TILES or zoom == 0:
            return zoom, x0, y0, x1, y1
        zoom -= 1


def parse_frames(payload, now=None):
    """Accept only provider past-frame paths, bounded and ordered by observation."""
    now = now or datetime.now(timezone.utc).timestamp()
    if payload.get('host') != TILE_HOST:
        raise ValueError('Unexpected radar tile host.')
    frames = {}
    for frame in payload.get('radar',{}).get('past',[]):
        stamp, path = frame.get('time'), frame.get('path','')
        if (isinstance(stamp,int) and now-3*3600 <= stamp <= now+60
                and re.fullmatch(r'/v2/radar/\d+',path)):
            frames[stamp] = path
    if not frames:
        raise ValueError('No recent observed radar frames are available.')
    return sorted(frames.items())[-MAX_FRAMES:]


def _read(url, limit, stop):
    if stop.is_set():
        raise RuntimeError('Radar loading stopped.')
    with requests.get(url, headers=HEADERS, timeout=(5,10), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected radar response status.')
        chunks, length = [], 0
        for chunk in response.iter_content(65536):
            if stop.is_set():
                raise RuntimeError('Radar loading stopped.')
            length += len(chunk)
            if length > limit:
                raise ValueError('Radar response exceeded its size limit.')
            chunks.append(chunk)
        return b''.join(chunks)


class RadarService:
    def __init__(self):
        self.stop = threading.Event()
        self.cache = OrderedDict()

    def close(self):
        self.stop.set()

    def _tile(self, key):
        path, zoom, x, y = key
        data = _read(f'{TILE_HOST}{path}/256/{zoom}/{x}/{y}/2/1_1.png', 1024*1024, self.stop)
        with Image.open(BytesIO(data)) as image:
            if image.size != (256,256):
                raise ValueError('Unexpected radar tile dimensions.')
            return image.convert('RGBA')

    def load(self, view):
        import json
        if not (0 < view.width <= 1800 and 0 < view.height <= 1200 and view.scale > 0):
            raise ValueError('Resize the map to at most 1800 × 1200 pixels to load radar.')
        metadata = json.loads(_read(METADATA_URL, 256*1024, self.stop))
        frames = parse_frames(metadata)
        zoom, x0, y0, x1, y1 = tile_layout(view)
        world = 256*2**zoom
        result = []
        # One load at a time from the panel; cache mutations stay on its worker.
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix='radar-tile') as pool:
            for stamp, path in frames:
                if self.stop.is_set():
                    raise RuntimeError('Radar loading stopped.')
                keys = [(path,zoom,x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)]
                missing = [key for key in keys if key not in self.cache]
                for key, image in zip(missing,pool.map(self._tile,missing)):
                    self.cache[key] = image
                    while len(self.cache) > CACHE_TILES:
                        self.cache.popitem(last=False)
                mosaic = Image.new('RGBA',((x1-x0+1)*256,(y1-y0+1)*256))
                for key in keys:
                    self.cache.move_to_end(key)
                    mosaic.paste(self.cache[key],((key[2]-x0)*256,(key[3]-y0)*256))
                west, south, east, north = view.bounds()
                # Pillow mesh reprojects Web Mercator tiles into this map's
                # longitude/latitude grid; 8-pixel strips keep edges aligned.
                sx0, sx1 = (west+180)/360*world-x0*256, (east+180)/360*world-x0*256
                mesh = []
                for top in range(0,view.height,8):
                    bottom = min(view.height,top+8)
                    lat_top, lat_bottom = north-top/view.scale, north-bottom/view.scale
                    sy0, sy1 = mercator_y(lat_top,world)-y0*256, mercator_y(lat_bottom,world)-y0*256
                    mesh.append(((0,top,view.width,bottom),(sx0,sy0,sx0,sy1,sx1,sy1,sx1,sy0)))
                projected = mosaic.transform((view.width,view.height),Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
                # Keep land/boundaries legible under precipitation colors.
                projected.putalpha(projected.getchannel('A').point(lambda value: int(value*.72)))
                draw = ImageDraw.Draw(projected)
                if north > 85.05112878:
                    draw.rectangle((0,0,view.width,max(0,int((north-85.05112878)*view.scale))),fill=(0,0,0,0))
                if south < -85.05112878:
                    draw.rectangle((0,int((north+85.05112878)*view.scale),view.width,view.height),fill=(0,0,0,0))
                result.append((stamp,projected))
        return view,result
