"""Persistent color skins for themed controls and native Tk content."""
from tkinter import TclError

SKINS = {
    'Navy': dict(bg='#0b1424', panel='#142238', surface='#101c30', button='#243a56',
                 hover='#355474', accent='#176caa', land='#192c40', shore='#456079', muted='#9aaec7'),
    'Graphite': dict(bg='#15171b', panel='#24272e', surface='#1c1f25', button='#383d47',
                     hover='#454c59', accent='#596b8a', land='#2c333f', shore='#626f84', muted='#a8b1c2'),
    'Forest': dict(bg='#0b1a16', panel='#142e25', surface='#10251e', button='#244b3a',
                   hover='#34634d', accent='#247a5b', land='#1a3b2e', shore='#4b7863', muted='#a6c3b2'),
    'Plum': dict(bg='#1a1225', panel='#2a1e3a', surface='#221930', button='#453259',
                 hover='#5e4675', accent='#7950a3', land='#362647', shore='#7e6098', muted='#bca9ce'),
}


class Appearance:
    def __init__(self, app, history):
        self.app, self.history = app, history
        self.name = history.setting('appearance_theme', 'Navy')
        if self.name not in SKINS:
            self.name = 'Navy'
        # Color roles allow switching back and forth, including widgets created
        # by dialogs or paginated cards after the original theme was applied.
        self.roles = {value:role for palette in SKINS.values() for role,value in palette.items()}
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
            '.':dict(background=colors['bg'],foreground='#e5edf8'),
            'TFrame':dict(background=colors['bg']), 'TLabel':dict(background=colors['bg']),
            'Panel.TFrame':dict(background=colors['panel']),
            'Muted.TLabel':dict(foreground=colors['muted']),
            'TNotebook':dict(background=colors['bg']),
            'TNotebook.Tab':dict(background=colors['button']),
            'TButton':dict(background=colors['button']),
            'Primary.TButton':dict(background=colors['accent']),
            'TCombobox':dict(fieldbackground=colors['panel'],background=colors['button']),
            'Treeview':dict(background=colors['surface'],fieldbackground=colors['surface']),
            'Treeview.Heading':dict(background=colors['button']),
            'TLabelframe':dict(background=colors['bg']),
            'TLabelframe.Label':dict(background=colors['bg'],foreground='#e5edf8'),
        }.items():
            style.configure(kind,**options)
        style.map('TNotebook.Tab',background=[('selected',colors['accent']),('active',colors['hover'])])
        style.map('TButton',background=[('active',colors['hover'])])
        style.map('TCheckbutton',background=[('active',colors['button'])])
        style.map('Treeview',background=[('selected',colors['accent'])])
        style.map('TCombobox',fieldbackground=[('readonly',colors['panel'])])
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
                widget.configure(background=self.app.palette['panel'],foreground='#e5edf8',
                                 activebackground=self.app.palette['accent'],activeforeground='#ffffff')
            if widget.winfo_class() in ('Tk','Toplevel'):
                widget.configure(background=self.app.palette['bg'])
            options = widget.keys()
            changes = {}
            for option in ('background','foreground','insertbackground','selectbackground',
                           'selectforeground','highlightbackground','activebackground','activeforeground','troughcolor'):
                if option in options:
                    role = self.roles.get(str(widget.cget(option)).lower())
                    if role:
                        changes[option] = self.app.palette[role]
            if changes:
                widget.configure(**changes)
            if widget.winfo_class() == 'Text':
                for tag in widget.tag_names():
                    role = self.roles.get(str(widget.tag_cget(tag,'foreground')).lower())
                    if role:
                        widget.tag_configure(tag,foreground=self.app.palette[role])
            alert_map = getattr(widget,'_stormwatch_map',None)
            if alert_map is not None:
                alert_map.request_draw()
        except (TclError, AttributeError):
            # Tk may map a widget while its parent is being disposed.
            pass
