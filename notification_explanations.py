"""Human-readable decisions shared by scheduling, delivery, and alert details."""
from datetime import datetime, timezone
from alert_history import instant, version_of

CHANNELS = ('sound','desktop','speech')


def decisions(profile, alert, kind='New', quiet=False, legacy=False, now=None):
    matched, match_reason = profile.explain_match(alert)
    end = instant(alert.get('ends') or alert.get('expires'))
    expired = end and end <= (now or datetime.now(timezone.utc))
    cancelled = kind == 'Cancelled' or alert.get('message_type','').lower() == 'cancel'
    result = {}
    for channel in CHANNELS:
        allowed = False
        if not matched:
            reason = match_reason
        else:
            base = f"{alert['event']} selected. {match_reason} "
            if kind in ('No longer active','Superseded'):
                reason = base+f'This alert is {kind.lower()} and will not notify.'
            elif (expired or kind == 'Expired') and not cancelled:
                reason = base+'The alert has expired.'
            elif cancelled and channel in ('sound','speech'):
                reason = base+'Cancellations do not play sound or speech.'
            elif not getattr(profile,channel):
                reason = base+f'{channel.title()} is switched off for this location.'
            elif channel in ('sound','speech') and getattr(profile,channel+'_events') is not None and alert['event'] not in getattr(profile,channel+'_events'):
                reason = base+f'This event is excluded by the {channel} event filter.'
            elif not profile.allows(alert,channel):
                reason = base+f'The watch/warning {channel} rule is off.'
            elif quiet:
                reason = base+('Legacy history is treated as a quiet baseline.' if legacy else
                              'Quiet startup: existing non-tornado/hurricane alerts do not notify on the first refresh.')
            else:
                allowed = True
                reason = base+f'{channel.title()} is enabled for this event.'
        result[channel] = dict(allowed=allowed,reason=reason)
    return result


def explanation_text(store, alert, profiles):
    version = version_of(alert)
    recorded = store.decision_rows(alert['id'],version)
    lines = ['Why did I get this? / Why was it silent?',
             'Recorded decisions describe the rules used when processed; current preferences are shown separately.']
    if not recorded:
        lines.append('No recorded notification decisions for this older or simulated alert.')
    for row in recorded:
        receipt = store.delivery(row['id'],row['version'],row['profile'],row['channel'])
        outcome = {'sent':'Submitted','skipped':'Suppressed','pending':'Pending','failed':'Failed'}.get(receipt['state'],'') if receipt else 'Not scheduled'
        lines.append(f"\n{row['location_name']} · {row['channel'].title()} · {outcome}\n{row['reason']}")
        if receipt:
            lines.append(receipt.get('reason',''))
            if receipt.get('error'):
                lines.append('Last error: '+receipt['error'])
    recorded_profiles = {row['profile'] for row in recorded}
    latest = store.get_alert(alert['id'])
    kind = ('Superseded' if latest['version'] != version else latest['status']) if latest else 'New'
    for profile in profiles:
        current = decisions(profile,alert,kind)
        matched, reason = profile.explain_match(alert)
        lines.append(f"\nCurrent preferences · {profile.name}: {reason}")
        if matched or profile.id in recorded_profiles:
            for channel,value in current.items():
                lines.append(f"{channel.title()}: {'Allowed by current rules' if value['allowed'] else 'Silent / disabled'} · {value['reason']}")
    lines.append('\nA submitted result means the local engine accepted/completed the request; it does not prove you heard or saw it. '
                 'Successful channels are not replayed for the same version; overlapping locations share one submission per channel.')
    return '\n'.join(lines)
