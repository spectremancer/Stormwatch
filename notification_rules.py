"""Shared form controls for per-location event-category notification rules."""
from event_catalog import CATEGORY_LABELS

RULE_FIELDS = tuple(f'{kind}_{channel}' for kind in CATEGORY_LABELS for channel in ('sound','desktop'))


def add_rule_fields(form, profile):
    form.add_label('Event-category rules', style='Heading.TLabel')
    form.add_label('The sound and desktop switches above enable each channel.\n'
                   'Use these rules to choose which selected events can use it.', wraplength=620)
    for key in RULE_FIELDS:
        kind, channel = key.split('_')
        value = getattr(profile, key)
        form.add_checkbox(key, f'{CATEGORY_LABELS[kind]} · {channel.title()}',
                          True if value is None else value,
                          text=f'{"Play sound" if channel == "sound" else "Send desktop notifications"} for {CATEGORY_LABELS[kind].lower()}')


def rule_values(values):
    return {key: values[key] for key in RULE_FIELDS}
