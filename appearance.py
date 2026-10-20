"""Persistent color skins for themed controls and native Tk content."""
from tkinter import TclError

SKINS = {
    'Classic': dict(bg='#f0f0f0', panel='#e4e4e4', surface='#ffffff', button='#d9d9d9',
                    hover='#c6d7e7', accent='#2463a0', land='#d8e2cd', shore='#627455',
                    muted='#525b66', text='#161b22', good='#146c43', bad='#b42318',
                    warning='#985000', watch='#164e9b', advisory='#795600',
                    statement='#1d6256', outlook='#68479c', other='#8a3e74'),
    'Navy': dict(bg='#0b1424', panel='#142238', surface='#101c30', button='#243a56',
                 hover='#355474', accent='#176caa', land='#192c40', shore='#456079', muted='#9aaec7'),
    'Graphite': dict(bg='#15171b', panel='#24272e', surface='#1c1f25', button='#383d47',
                     hover='#454c59', accent='#596b8a', land='#2c333f', shore='#626f84', muted='#a8b1c2'),
    'Forest': dict(bg='#0b1a16', panel='#142e25', surface='#10251e', button='#244b3a',
                   hover='#34634d', accent='#247a5b', land='#1a3b2e', shore='#4b7863', muted='#a6c3b2'),
    'Plum': dict(bg='#1a1225', panel='#2a1e3a', surface='#221930', button='#453259',
                 hover='#5e4675', accent='#7950a3', land='#362647', shore='#7e6098', muted='#bca9ce'),
}


for _palette in SKINS.values():
    for _role, _value in dict(text='#e5edf8',good='#7ce3bf',bad='#ff6b6b',warning='#ffbc87',
                             watch='#85caff',advisory='#f6d365',statement='#8ee2cf',
                             outlook='#c4b5fd',other='#f0a6d6').items():
        _palette.setdefault(_role,_value)


class Appearance:
    def __init__(self, app, history):
        self.app, self.history = app, history
        self.name = history.setting('appearance_theme', 'Classic')
        if self.name not in SKINS:
            self.name = 'Classic'
        # Color roles allow switching back and forth, including widgets created
        # by dialogs or paginated cards after the original theme was applied.
        self.roles = {value:role for palette in SKINS.values() for role,value in palette.items()}
        self.roles['#f5f9ff'] = 'text'
        app.root.bind_all('<Map>', self.mapped, add='+')
        self.apply(self.name)

    def set(self, name):
        if name not in SKINS:
            raise ValueError('Choose a supported appearance skin.')
        self.history.save_setting('appearance_theme', name)
        self.apply(name)

    def apply(self, name):
        self.name = name
        colors = self.app.palette = SKINS[name].copy()
        style = self.app.style
        for kind, options in {
            '.':dict(background=colors['bg'],foreground=colors['text']),
            'TFrame':dict(background=colors['bg']), 'TLabel':dict(background=colors['bg']),
            'Panel.TFrame':dict(background=colors['panel']),
            'Brand.TLabel':dict(foreground=colors['text']),
            'Muted.TLabel':dict(foreground=colors['muted']),
            'TNotebook':dict(background=colors['bg']),
            'TNotebook.Tab':dict(background=colors['button'],foreground=colors['text']),
            'TButton':dict(background=colors['button']),
            'Primary.TButton':dict(background=colors['accent'],foreground='#ffffff'),
            'TCombobox':dict(fieldbackground=colors['panel'],background=colors['button']),
            'Treeview':dict(background=colors['surface'],fieldbackground=colors['surface'],foreground=colors['text']),
            'Treeview.Heading':dict(background=colors['button'],foreground=colors['text']),
            'TLabelframe':dict(background=colors['bg']),
            'TLabelframe.Label':dict(background=colors['bg'],foreground=colors['text']),
        }.items():
            style.configure(kind,**options)
        style.map('TNotebook.Tab',background=[('selected',colors['accent']),('active',colors['hover'])],
                  foreground=[('selected','#ffffff'),('active',colors['text'])])
        style.map('TButton',background=[('active',colors['hover'])])
        style.map('Primary.TButton',background=[('active',colors['accent'])])
        style.map('TCheckbutton',background=[('active',colors['button'])])
        style.map('Treeview',background=[('selected',colors['accent'])],foreground=[('selected','#ffffff')])
        style.map('TCombobox',fieldbackground=[('readonly',colors['panel'])],foreground=[('readonly',colors['text'])])
        # Preserve black-on-white editable inputs, independent of skin.
        style.configure('Input.TCombobox',fieldbackground='#ffffff',foreground='#000000')
        style.map('Input.TCombobox',fieldbackground=[('!disabled','#ffffff'),('disabled','#eeeeee')],
                  foreground=[('!disabled','#000000'),('disabled','#555555')])
        self.walk(self.app.root)

    def mapped(self, event):
        if not self.app._closed:
            self.color_widget(event.widget)

    def walk(self, widget):
        self.color_widget(widget)
        for child in widget.winfo_children():
            self.walk(child)

    def color_widget(self, widget):
        try:
            if widget.winfo_class() == 'Menu':
                widget.configure(background=self.app.palette['panel'],foreground=self.app.palette['text'],
                                 activebackground=self.app.palette['accent'],activeforeground='#ffffff')
            if widget.winfo_class() in ('Tk','Toplevel'):
                widget.configure(background=self.app.palette['bg'])
            options = widget.keys()
            changes = {}
            for option in ('background','foreground','insertbackground','selectbackground',
                           'selectforeground','highlightbackground','activebackground','activeforeground','troughcolor'):
                if option in options:
                    value = str(widget.cget(option)).lower()
                    if option in ('selectforeground','activeforeground') and value == '#ffffff':
                        continue
                    if widget.winfo_class() in ('Text','Entry') and str(widget.cget('foreground')) == '#000000' and str(widget.cget('background')) == '#ffffff':
                        continue
                    role = self.roles.get(value)
                    if role:
                        changes[option] = self.app.palette[role]
            if changes:
                widget.configure(**changes)
            if widget.winfo_class() == 'Text':
                for tag in widget.tag_names():
                    if tag == 'sel':
                        continue
                    role = self.roles.get(str(widget.tag_cget(tag,'foreground')).lower())
                    if role:
                        widget.tag_configure(tag,foreground=self.app.palette[role])
            alert_map = getattr(widget,'_stormwatch_map',None)
            if alert_map is not None:
                alert_map.request_draw()
        except (TclError, AttributeError):
            # Tk may map a widget while its parent is being disposed.
            pass
