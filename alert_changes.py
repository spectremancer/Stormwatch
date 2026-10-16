"""Deterministic, factual summaries of changes to official alert content."""
from datetime import datetime, timezone


def _instant(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) if value else None
    except (ValueError, AttributeError):
        return None


def summarize_change(previous, current, kind):
    if kind in ('Cancelled', 'Expired', 'No longer active'):
        return {'Cancelled': 'The issuing agency cancelled this alert.',
                'Expired': 'The alert reached its expiration time.',
                'No longer active': 'This alert is absent from the latest active snapshot; cancellation was not confirmed.'}[kind]
    if not previous:
        return 'New alert issued for the affected area.'
    changes = []
    old_end = _instant(previous.get('ends') or previous.get('expires'))
    new_end = _instant(current.get('ends') or current.get('expires'))
    if old_end and new_end and old_end != new_end:
        seconds = max(1,round(abs((new_end - old_end).total_seconds())))
        amount, unit = (seconds//60,'minute') if seconds%60 == 0 else (seconds,'second')
        changes.append(f"{'Extended' if new_end > old_end else 'Shortened'} by {amount} {unit}{'s' if amount != 1 else ''}.")
    if previous.get('event') != current.get('event'):
        changes.append(f"Event changed from {previous.get('event', 'unknown')} to {current.get('event', 'unknown')}.")
    severity = {'Minor': 1, 'Moderate': 2, 'Severe': 3, 'Extreme': 4}
    if previous.get('severity') != current.get('severity'):
        old, new = previous.get('severity', 'Unknown'), current.get('severity', 'Unknown')
        direction = 'changed'
        if old in severity and new in severity:
            direction = 'increased' if severity[new] > severity[old] else 'decreased'
        changes.append(f'Severity {direction} from {old} to {new}.')
    old_codes = set(previous.get('geocode', {}).get('UGC', []))
    new_codes = set(current.get('geocode', {}).get('UGC', []))
    for label, codes in (('Added affected counties/zones', new_codes - old_codes),
                         ('Removed affected counties/zones', old_codes - new_codes)):
        if codes:
            names = ', '.join(sorted(codes)[:8])
            changes.append(f"{label}: {names}{' and more' if len(codes) > 8 else ''}.")
    for field, message in (('area', 'Affected-area description changed.'),
                           ('geometry', 'Affected boundary changed.'),
                           ('instruction', 'Safety instructions changed.'),
                           ('headline', 'Official headline changed.'),
                           ('description', 'Official alert description changed.'),
                           ('urgency', 'Urgency changed.')):
        if previous.get(field) != current.get(field):
            # Zone-derived boundaries are enrichment, not an agency update.
            if field == 'geometry' and current.get('geometry_source') == 'NWS affected zones':
                continue
            changes.append(message)
    return ' '.join(changes) or 'The agency published a new alert version; review the full details.'
