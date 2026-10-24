"""Archive coverage and message-level analysis, explicitly separate from storm counts."""
from collections import Counter, defaultdict
from alert_history import instant, expiration_of


def analyze_archive(store):
    days,severities,sources,counties = Counter(),Counter(),Counter(),defaultdict(set)
    latest = {}
    first = last = None
    unknown = 0
    with store.read_snapshot() as reader:
        cursor = reader.connection.execute('SELECT id,event,recorded_at,source,time_basis,data FROM history_events ORDER BY sequence')
        import json
        for row in cursor:
            stamp = instant(row['recorded_at'])
            if stamp:
                day = stamp.date().isoformat()
                days[day] += 1
                first = min(first,day) if first else day
                last = max(last,day) if last else day
            else:
                unknown += 1
            alert = json.loads(row['data'])
            sources[row['source']+' · '+row['time_basis']] += 1
            severities[alert.get('severity','Unknown')] += 1
            issued = instant(alert.get('sent'))
            previous = latest.get(row['id'])
            if previous is None or issued and (instant(previous[0]) is None or issued>=instant(previous[0])):
                latest[row['id']] = (alert.get('sent'),alert.get('ends'),alert.get('expires'))
            for county in set(alert.get('geocode',{}).get('UGC',[])):
                if len(county)==6 and county[2]=='C':
                    counties[county].add(row['id'])
    durations = []
    for sent,ends,expires in latest.values():
        issued = instant(sent)
        end = expiration_of(dict(ends=ends,expires=expires))
        if issued and end and end>=issued:
            durations.append((end-issued).total_seconds()/3600)
    return dict(days=sorted(days.items()),severities=severities,sources=sources,
                counties=sorted(((name,len(ids)) for name,ids in counties.items()),key=lambda x:(-x[1],x[0]))[:25],
                first=first,last=last,unknown=unknown,duration_count=len(durations),
                mean_duration=sum(durations)/len(durations) if durations else None)


def coverage_text(result):
    lines = [f"Record dates (UTC): {result['first'] or 'unknown'} through {result['last'] or 'unknown'}",
        f"Records with unknown time: {result['unknown']}",'',
        'Sources and time basis:']
    lines.extend(f'{source}: {count:,} recorded changes' for source,count in sorted(result['sources'].items()))
    lines.extend(['','Severity distribution (recorded changes, including versions):'])
    lines.extend(f'{severity}: {count:,}' for severity,count in sorted(result['severities'].items()))
    if result['mean_duration'] is not None:
        lines.extend(['',f"Mean latest-message validity: {result['mean_duration']:.2f} hours across {result['duration_count']:,} distinct IDs.",
                      'Validity is issue-to-effective-expiration time, not observed storm duration.'])
    lines.extend(['','Top county UGC codes by distinct alert IDs:'])
    lines.extend(f'{county}: {count:,}' for county,count in result['counties'])
    lines.extend(['','Coverage limitations:',
        'Live history depends on enabled profiles, selected event types, app uptime, and connectivity.',
        'NWS archive downloads cover a recent rolling period and may omit intermediate versions.',
        'Missing dates do not establish that no weather occurred. Sources/time bases are not interchangeable.',
        'Alert IDs are messages, not counts of physical storms. This archive is not a climatological dataset.'])
    return '\n'.join(lines)
