"""Shared form controls for per-location watch/warning notification rules."""
RULE_FIELDS = ('warning_sound', 'warning_desktop', 'watch_sound', 'watch_desktop')


def add_rule_fields(form, profile):
    form.add_label('Watch / warning rules', style='Heading.TLabel')
    form.add_label('The sound and desktop switches above enable each channel.\n'
                   'Use these rules to choose which selected events can use it.', wraplength=620)
    for key in RULE_FIELDS:
        kind, channel = key.split('_')
        value = getattr(profile, key)
        form.add_checkbox(key, f'{kind.title()}s · {channel.title()}',
                          True if value is None else value,
                          text=f'{"Play sound" if channel == "sound" else "Send desktop notifications"} for {kind}s')


def rule_values(values):
    return {key: values[key] for key in RULE_FIELDS}
