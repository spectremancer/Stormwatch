"""Offline endurance/fault workload with real GUI, archive readers, and bounded reports.

Example: DISPLAY=:99 SDL_AUDIODRIVER=dummy python -B scripts/soak_monitoring.py --seconds 60
Use --hours 48 for a dedicated multi-day machine run. No real notifications or API requests.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import Mock

os.environ['SDL_AUDIODRIVER']='dummy'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import StormwatchApp
from alert_history import AlertHistory
from history_store import HistoryFilter
from locations import LocationProfile
from benchmark_processing import sample


def memory_bytes():
    if sys.platform.startswith('linux'):
        return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in (
                'PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
        data=Memory();data.cb=ctypes.sizeof(data)
        handle=ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(data),data.cb):return data.WorkingSetSize
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    period=parser.add_mutually_exclusive_group()
    period.add_argument('--seconds',type=float,default=60)
    period.add_argument('--hours',type=float)
    parser.add_argument('--incoming',type=int,default=1000)
    parser.add_argument('--archive',type=int,default=10000)
    parser.add_argument('--profiles',type=int,default=5)
    parser.add_argument('--max-ui-gap-ms',type=float,default=500)
    parser.add_argument('--report',type=Path,default=Path('/tmp/stormwatch-soak.json') if os.name!='nt' else Path('stormwatch-soak.json'))
    args=parser.parse_args()
    seconds=args.hours*3600 if args.hours is not None else args.seconds
    if seconds<=0 or args.incoming<1 or args.archive<0 or not 1<=args.profiles<=50:parser.error('Use a positive duration and incoming count; archive must be nonnegative.')
    with tempfile.TemporaryDirectory(prefix='stormwatch-soak-') as directory:
        store=AlertHistory(Path(directory)/'history.db')
        cancel=threading.Event()
        archive=[sample('history-'+str(i),True) for i in range(args.archive)]
        store.import_archive(archive,'US',cancel)
        del archive
        for index in range(args.profiles):
            store.save_profile(LocationProfile(name=f'SIMULATION {index+1}',sound=False,desktop=False,speech=False))
        ui=StormwatchApp(Mock(interval=60),store)
        ui.profile.sound=ui.profile.desktop=ui.profile.speech=False
        ui.app.root.update()
        now=datetime.now(timezone.utc)
        data={str(i):dict(sample(i),sent=now.isoformat(),expires=(now+timedelta(hours=1)).isoformat(),
            geometry={'type':'Polygon','coordinates':[[[-100+.3*math.cos(j/20),35+.3*math.sin(j/20)] for j in range(127)]]})
            for i in range(args.incoming)}
        # Exercise the real raster loader with an in-memory provider, including
        # viewport invalidation and bounded tile/frame caches; never contact RainViewer.
        from PIL import Image
        from io import BytesIO
        from radar import METADATA_URL
        buffer=BytesIO()
        Image.new('RGBA',(256,256),(20,160,90,70)).save(buffer,format='PNG')
        tile=buffer.getvalue()
        def radar_fixture(url,limit):
            if url==METADATA_URL:
                latest=int(time.time())//300*300
                return json.dumps({'host':'https://tilecache.rainviewer.com','radar':{'past':[
                    {'time':latest-i*300,'path':f'/v2/radar/simulation_{latest-i*300}'} for i in range(6)]}}).encode()
            return tile
        ui.radar.service._fetch=radar_fixture
        ui.commands.show_tab('Map')
        ui.app.root.update()
        ui.radar.enabled.set(True)
        ui.radar.toggle()
        ui.running=True
        start=last_pulse=time.monotonic()
        last_cycle=start-5
        max_gap=0
        cycles=0
        memories=[]
        importer=None
        import_errors=[]
        samples=[]
        def pulse():
            nonlocal last_pulse,max_gap
            now=time.monotonic();max_gap=max(max_gap,now-last_pulse);last_pulse=now
            ui.app.after(5,pulse)
        ui.app.after(5,pulse)
        try:
            while time.monotonic()-start<seconds:
                if not ui.busy and time.monotonic()-last_cycle>=2:
                    cycles+=1
                    # Change only 1% of the snapshot per cycle: a multi-day run
                    # exercises sustained updates without generating millions of full snapshots.
                    for index in range(min(len(data),max(1,args.incoming//100))):
                        key=str(index)
                        data[key]=dict(data[key],headline=f'SIMULATION · Revision {cycles}',
                                       sent=datetime.now(timezone.utc).isoformat())
                    if cycles%5==0:
                        ending=dict(sample('ending-'+str(cycles)),expires='2020-01-01T00:00:00Z')
                        ui.history.observe(ending)
                    if cycles%7==0:
                        ui.failed(ui.generation,RuntimeError('SIMULATION · Connection interruption'))
                    ui.received(ui.generation,(data,''))
                    if cycles%3==0:ui.map.zoom(1.02 if cycles%2 else 1/1.02)
                    ui.history_panel.filters=HistoryFilter(text='synthetic')
                    ui.history_panel.refresh()
                    ui.delivery_panel.refresh()
                    if cycles%3==0 and (importer is None or not importer.is_alive()):
                        values=[sample(f'archive-{cycles}-{i}',True) for i in range(50)]
                        def import_batch(batch=values):
                            try:store.import_archive(batch,'US',cancel)
                            except Exception as error:import_errors.append(str(error))
                        importer=threading.Thread(target=import_batch)
                        importer.start()
                    memories.append(memory_bytes())
                    samples.append((round(time.monotonic()-start,1),memories[-1]))
                    last_cycle=time.monotonic()
                    if ui.timer:
                        ui.app.root.after_cancel(ui.timer);ui.timer=None
                ui.app.root.update()
                time.sleep(.001)
            # Finish the current batch; shutdown must not abandon an active transaction.
            deadline=time.monotonic()+15
            while ui.busy and time.monotonic()<deadline:
                ui.app.root.update();time.sleep(.001)
            assert not ui.busy,'Processing did not settle'
        finally:
            cancel.set()
            if importer:importer.join(15)
            ui.close();ui.cleanup_thread.join(45)
            assert not ui.cleanup_thread.is_alive(),'Shutdown did not finish'
        report=dict(seconds=round(time.monotonic()-start,2),cycles=cycles,incoming=args.incoming,profiles=args.profiles,simulated_radar=True,
                    initial_archive=args.archive,max_ui_gap_ms=round(max_gap*1000,2),
                    rss_start=memories[0] if memories else None,rss_end=memories[-1] if memories else None,
                    rss_peak=max((m for m in memories if m is not None),default=None),
                    rss_after_warmup=next((m for elapsed,m in samples if elapsed>=min(30,seconds/4)),None),
                    import_errors=import_errors,
                    real_network=False,real_notifications=False)
        args.report.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        if import_errors:raise SystemExit('Background archive import failed')
        if max_gap*1000>args.max_ui_gap_ms:
            raise SystemExit('UI heartbeat exceeded the configured regression ceiling')


if __name__=='__main__':main()
