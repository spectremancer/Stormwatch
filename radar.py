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
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw
import requests

METADATA_URL = 'https://api.rainviewer.com/public/weather-maps.json'
TILE_HOST = 'https://tilecache.rainviewer.com'
MAX_FRAMES, MAX_TILES, CACHE_TILES = 6, 12, 96
HEADERS = {'User-Agent': 'Stormwatch/1.0', 'Accept': 'application/json,image/png'}


class RadarError(ValueError):
    """Safe, actionable diagnostics; excludes response bodies and proxy credentials."""


def connection_error(error, host):
    if isinstance(error,requests.exceptions.ProxyError):
        if '403' in str(error):
            return RadarError(f'Proxy refused HTTPS access to {host} (CONNECT HTTP 403). '
                              'Allow this host in the network policy or ask your proxy administrator.')
        return RadarError(f'Proxy connection failed for {host}. Check your system proxy settings.')
    if isinstance(error,requests.exceptions.SSLError):
        return RadarError(f'TLS certificate validation failed for {host}. Check the system clock and trusted certificates.')
    if isinstance(error,requests.exceptions.Timeout):
        return RadarError(f'The request to {host} timed out. Check the connection and try Refresh radar.')
    return RadarError(f'Could not connect to {host}. Check DNS, firewall, and internet access, then try Refresh radar.')


def error_description(error):
    if isinstance(error,RadarError):
        return str(error)
    if isinstance(error,ValueError):
        return str(error)
    return 'Radar could not be loaded. Try Refresh radar; verify access to api.rainviewer.com and tilecache.rainviewer.com.'


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


def image_host(payload):
    """Use the API's host after checking the supported HTTPS tile origin."""
    host = payload.get('host') if isinstance(payload,dict) else None
    if not isinstance(host,str) or host.rstrip('/') != TILE_HOST:
        raise RadarError('The radar provider advertised an unsupported tile host. The provider response may have changed; update Stormwatch.')
    return host.rstrip('/')


def parse_frames(payload, now=None):
    """Paths are opaque API values; time is frame generation time, not a path ID."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    image_host(payload)
    radar = payload.get('radar')
    if not isinstance(radar,dict) or not isinstance(radar.get('past'),list):
        raise RadarError('The radar metadata has no past-frame list. The provider response may have changed; try again later or update Stormwatch.')
    frames = {}
    for frame in radar['past']:
        if not isinstance(frame,dict):
            continue
        stamp, path = frame.get('time'), frame.get('path','')
        if (type(stamp) is int and isinstance(path,str) and now-3*3600 <= stamp <= now+60
                and re.fullmatch(r'/v2/radar/[A-Za-z0-9_-]+',path)):
            frames[stamp] = path
    if not frames:
        raise RadarError('No radar frames generated in the last three hours are available. Check the system clock or try again later.')
    return sorted(frames.items())[-MAX_FRAMES:]


def _read(url, limit, stop):
    for _ in range(4):
        if stop.is_set():
            raise RuntimeError('Radar loading stopped.')
        host = urlparse(url).hostname
        try:
            with requests.get(url, headers=HEADERS, timeout=(5,10), stream=True, allow_redirects=False) as response:
                code = response.status_code
                if code in (301,302,303,307,308):
                    target = urljoin(url,response.headers.get('Location',''))
                    parsed = urlparse(target)
                    if (parsed.scheme != 'https' or parsed.hostname not in ('api.rainviewer.com','tilecache.rainviewer.com')
                            or parsed.username or parsed.password or parsed.port not in (None,443)):
                        raise RadarError('The radar provider redirected to an unsupported destination. Update Stormwatch or check the provider status.')
                    url = target
                    continue
                if code == 429:
                    raise RadarError(f'{host} returned HTTP 429 (rate limit). Wait a few minutes before refreshing radar.')
                if code in (401,403):
                    raise RadarError(f'{host} returned HTTP {code} (access denied). Check firewall/provider access rules.')
                if code != 200:
                    raise RadarError(f'{host} returned HTTP {code}. The radar service may be unavailable; try again later.')
                chunks, length = [], 0
                for chunk in response.iter_content(65536):
                    if stop.is_set():
                        raise RuntimeError('Radar loading stopped.')
                    length += len(chunk)
                    if length > limit:
                        raise RadarError('The radar response exceeded its size limit; the provider response may have changed.')
                    chunks.append(chunk)
                return b''.join(chunks)
        except requests.RequestException as error:
            raise connection_error(error,host) from None
    raise RadarError('The radar provider redirected too many times. Try again later or check the provider status.')


class RadarService:
    def __init__(self):
        self.stop = threading.Event()
        self.cache = OrderedDict()
        self.connection_lock = threading.Lock()
        self.connections = {}

    def connection_info(self):
        with self.connection_lock:
            return {host:dict(values) for host,values in self.connections.items()}

    def _fetch(self, url, limit):
        host = urlparse(url).hostname
        with self.connection_lock:
            item = self.connections.setdefault(host,dict(requests=0,successes=0,failures=0,active=0,
                last_attempt=None,last_success=None,result='Not attempted'))
            item['requests'] += 1
            item['active'] += 1
            item['last_attempt'] = datetime.now(timezone.utc)
        try:
            data = _read(url,limit,self.stop)
        except Exception as error:
            with self.connection_lock:
                item['failures'] += 1
                item['result'] = error_description(error)
            raise
        else:
            with self.connection_lock:
                item['successes'] += 1
                item['last_success'] = datetime.now(timezone.utc)
                # _read returns bytes only after a complete HTTP 200 response.
                item['result'] = 'HTTP 200 · response received'
            return data
        finally:
            with self.connection_lock:
                item['active'] -= 1

    def close(self):
        self.stop.set()

    def _tile(self, key):
        host, path, zoom, x, y = key
        # Weather Maps API: {host}{path}/{size}/{z}/{x}/{y}/{color}/{smooth}_{snow}.png
        # 2 = Universal Blue; 1_1 = smoothing on, separate snow colors on.
        data = self._fetch(f'{host}{path}/256/{zoom}/{x}/{y}/2/1_1.png', 1024*1024)
        try:
            with Image.open(BytesIO(data)) as image:
                if image.size != (256,256):
                    raise RadarError('The provider returned unexpected radar tile dimensions. Try again later or update Stormwatch.')
                return image.convert('RGBA')
        except OSError:
            raise RadarError('The radar host returned an unreadable image. A firewall or provider error page may have replaced the tile.') from None

    def load(self, view):
        import json
        if not (0 < view.width <= 1800 and 0 < view.height <= 1200 and view.scale > 0):
            raise ValueError('Resize the map to at most 1800 × 1200 pixels to load radar.')
        try:
            metadata = json.loads(self._fetch(METADATA_URL, 256*1024))
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise RadarError('The radar metadata was not valid JSON. A firewall or provider error page may have replaced the response.') from None
        frames = parse_frames(metadata)
        host = image_host(metadata)
        zoom, x0, y0, x1, y1 = tile_layout(view)
        world = 256*2**zoom
        result = []
        # One load at a time from the panel; cache mutations stay on its worker.
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix='radar-tile') as pool:
            for stamp, path in frames:
                if self.stop.is_set():
                    raise RuntimeError('Radar loading stopped.')
                keys = [(host,path,zoom,x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)]
                missing = [key for key in keys if key not in self.cache]
                for key, image in zip(missing,pool.map(self._tile,missing)):
                    self.cache[key] = image
                    while len(self.cache) > CACHE_TILES:
                        self.cache.popitem(last=False)
                mosaic = Image.new('RGBA',((x1-x0+1)*256,(y1-y0+1)*256))
                for key in keys:
                    self.cache.move_to_end(key)
                    mosaic.paste(self.cache[key],((key[3]-x0)*256,(key[4]-y0)*256))
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
