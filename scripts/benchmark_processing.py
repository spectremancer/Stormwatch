"""Synthetic local GUI load test; no real alerts or notifications are sent.

DISPLAY=:99 SDL_AUDIODRIVER=dummy python -B scripts/benchmark_processing.py
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alert_history import AlertHistory
from main import StormwatchApp


def sample(key, expired=False):
    return dict(id=str(key),event='Tornado Warning',headline='SIMULATION · Load test '+str(key),
        area='Test County',severity='Severe',urgency='Immediate',sent='2026-10-16T10:00:00Z',
        expires='2020-01-01T00:00:00Z' if expired else '2099-01-01T00:00:00Z',ends='',
        instruction='Synthetic benchmark instructions. '*80,description='Synthetic text. '*80,
        url='',geocode={},geometry=None,references=[],message_type='Alert',simulated=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--incoming',type=int,default=1000)
    parser.add_argument('--stored',type=int,default=10000)
    parser.add_argument('--passes',type=int,default=3)
    args=parser.parse_args()
    if args.incoming<1 or args.stored<0 or args.passes<1:
        parser.error('Use positive incoming/passes and a nonnegative stored count.')
    with tempfile.TemporaryDirectory(prefix='stormwatch-benchmark-') as directory:
        store=AlertHistory(Path(directory)/'load.db')
        with store.connection:
            store.connection.executemany('INSERT INTO alerts (id,version,data,status,updated) VALUES (?,?,?,?,?)',
                ((str(i),'old',json.dumps(sample(i,True)),'Expired','2026-01-01') for i in range(args.stored)))
        ui=StormwatchApp(Mock(interval=60),store)
        try:
            ui.profile.sound=ui.profile.desktop=False
            ui.app.root.update()
            data={str(i):sample(i) for i in range(args.stored,args.stored+args.incoming)}
            timings=[]
            for run in range(args.passes):
                gaps=[]
                last=time.perf_counter()
                pulse_timer=None
                def pulse():
                    nonlocal last,pulse_timer
                    now=time.perf_counter()
                    gaps.append(now-last)
                    last=now
                    pulse_timer=ui.app.after(5,pulse)
                pulse_timer=ui.app.after(5,pulse)
                start=time.perf_counter()
                ui.running=True
                ui.received(ui.generation,(data,''))
                while ui.busy:
                    ui.app.root.update()
                    time.sleep(.0005)
                ui.app.root.update()
                elapsed=time.perf_counter()-start
                ui.app.root.after_cancel(pulse_timer)
                timings.append(dict(pass_number=run+1,seconds=round(elapsed,4),
                                    max_heartbeat_gap_ms=round(max(gaps,default=elapsed)*1000,2)))
                if ui.timer:
                    ui.app.root.after_cancel(ui.timer)
                    ui.timer=None
            start=time.perf_counter()
            for _ in range(10):
                ui.tick()
                ui.app.root.after_cancel(ui.health_timer)
            print(json.dumps(dict(incoming=args.incoming,stored=args.stored,passes=timings,
                                  ten_ticks_seconds=round(time.perf_counter()-start,4)),indent=2))
        finally:
            ui.close()
            ui.cleanup_thread.join(timeout=10)


if __name__=='__main__':
    main()
