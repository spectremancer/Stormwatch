"""A three-step TkFlow location wizard: find, confirm, and choose preferences."""
from dataclasses import replace
from tkinter import ttk

from TkFlow import Button, Checkbox, Form, Label, TextInput, Window
from TkFlow.widget import Widget
from dashboard_views import AlertMap
from place_search import nearby_places, search_places


class Results(Widget):
    def __init__(self, parent, selected):
        frame = ttk.Frame(parent.widget)
        self.tree = ttk.Treeview(frame, columns=('place',), show='headings', selectmode='browse', height=8)
        self.tree.heading('place', text='City / state / ZIP')
        self.tree.column('place', width=480)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind('<<TreeviewSelect>>', lambda _: selected())
        self._attach(parent, frame, expand=True, fill='both')


class LocationWizard:
    def __init__(self, owner):
        self.owner = owner
        self.window = Window(owner.app, 'Add a location · Stormwatch', width=800, height=760)
        self.step = 0
        self.places = []
        self.place = self.candidate = None
        self.busy = False
        self.request = 0
        self.heading = Label(self.window, '1 of 3 · Find your location', style='Heading.TLabel')
        self.pages = [self.window.column(padding=0, expand=True, fill='both') for _ in range(3)]
        search, confirm, preferences = self.pages
        Label(search, 'Search a US city or ZIP code', style='Heading.TLabel')
        Label(search, 'Examples: Chicago, IL · Springfield Illinois · 60601\nSearches stay on this device. Street addresses are not supported.',
              style='Muted.TLabel', wraplength=720)
        row = search.row(padding=0)
        self.query = TextInput(row, expand=True)
        self.query.bind('<Return>', lambda _: self.search())
        self.search_button = Button(row, 'Search', self.search)
        self.results = Results(search, self.selection_changed)
        self.results.tree.bind('<Double-Button-1>', lambda _: self.next())
        Button(search, 'Advanced location editor…', self.advanced)
        self.confirmation = Label(confirm, '', style='Heading.TLabel')
        Label(confirm, 'Confirm the area below. This is an approximate city/ZIP center, not your street address.\n'
              'Drag to pan, scroll to zoom, or click the map to move the pin. NWS zones are checked before saving.',
              style='Muted.TLabel', wraplength=720)
        controls = confirm.row(padding=0)
        Button(controls, '+', lambda: self.map.zoom(1.5))
        Button(controls, '−', lambda: self.map.zoom(1/1.5))
        Button(controls, 'Center on pin', lambda: self.map.fit())
        self.coordinate = Label(confirm, '', style='Muted.TLabel')
        self.map = AlertMap(confirm, lambda _: None, on_point=self.move_pin)
        self.form = Form(preferences, 'Notification preferences', scrollable=True, expand=True, fill='both')
        self.form.canvas.configure(background='#0b1424')
        self.form.add_text('name', 'Location name (for example Home, Family, Work)', 'Home')
        self.form.add_checkbox('enabled', 'Monitoring', True, text='Enable monitoring for this location')
        self.form.add_checkbox('sound', 'Sound', True, text='Play alert sound')
        self.form.add_checkbox('desktop', 'Desktop', True, text='Send desktop notifications')
        self.form.add_label('Select the events you want to follow:', style='Heading.TLabel')
        self.events = {event: Checkbox(self.form.body, event, value=True)
                       for event in owner.profile.events or ['Tornado Warning', 'Tornado Watch', 'Hurricane Warning', 'Hurricane Watch']}
        self.summary = self.form.add_label('', wraplength=680, style='Muted.TLabel')
        self.message = Label(self.window, 'Enter a city and state, or a ZIP code.', style='Muted.TLabel', wraplength=740)
        actions = self.window.row(padding=0)
        self.back = Button(actions, 'Back', self.previous)
        self.forward = Button(actions, 'Next', self.next)
        Button(actions, 'Cancel', self.close)
        self.show_step(0)
        self.query.widget.focus_set()

    def show_step(self, step):
        self.step = step
        for i, page in enumerate(self.pages):
            page.show() if i == step else page.hide()
        self.heading.set(('1 of 3 · Find your location', '2 of 3 · Confirm the pin', '3 of 3 · Make it yours')[step])
        self.back.disable() if step == 0 or self.busy else self.back.enable()
        self.forward.set('Save location' if step == 2 else 'Next')
        if self.busy or (step == 0 and self.place is None):
            self.forward.disable()
        else:
            self.forward.enable()

    def search(self):
        if self.busy:
            return
        self.request += 1
        request = self.request
        query = self.query.get()
        self.place = None
        self.results.tree.delete(*self.results.tree.get_children())
        self.forward.disable()
        self.search_button.disable()
        self.message.set('Searching the offline city/ZIP catalog…')
        self.owner.app.run_in_thread(search_places, query,
            on_result=lambda rows: self.searched(request, rows), on_error=lambda error: self.search_failed(request, error))

    def searched(self, request, places):
        if self.window._closed or request != self.request:
            return
        self.search_button.enable()
        self.places = places
        for i, place in enumerate(places):
            self.results.tree.insert('', 'end', iid=str(i), values=(place.label,))
        self.message.set(f'{len(places)} matches shown. Select a result to confirm its pin.' if places else
                         'No matches in the bundled catalog. Try a nearby city, another ZIP, or the advanced editor.')

    def search_failed(self, request, error):
        if not self.window._closed and request == self.request:
            self.search_button.enable()
            self.message.set(f'Location search failed: {error}')

    def selection_changed(self):
        selection = self.results.tree.selection()
        if selection:
            self.place = self.places[int(selection[0])]
            self.forward.enable()

    def next(self):
        if self.busy:
            return
        if self.step == 0:
            if self.place is None:
                return
            self.candidate = self.place.profile()
            self.confirmation.set(self.place.label)
            self.update_pin()
            self.show_step(1)
            self.window.root.update_idletasks()
            self.map.fit()
            self.message.set('Check the city/state and the approximate pin before continuing.')
        elif self.step == 1:
            self.summary.set(f'{self.place.label}\nPin: {self.candidate.latitude:.5f}, {self.candidate.longitude:.5f}\n'
                             'Matching uses a storm polygon when available, otherwise the resolved NWS zones.')
            self.show_step(2)
            self.message.set('Choose a name, notification channels, and event types. You can change these later.')
        else:
            self.save()

    def previous(self):
        if not self.busy and self.step > 0:
            self.show_step(self.step - 1)

    def move_pin(self, latitude, longitude):
        if self.candidate and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            self.candidate.latitude, self.candidate.longitude = latitude, longitude
            self.candidate.zones = []
            self.update_pin()
            self.message.set('Pin moved. The new coordinates will be resolved through NWS before saving.')

    def update_pin(self):
        self.coordinate.set(f'Latitude {self.candidate.latitude:.5f} · Longitude {self.candidate.longitude:.5f}')
        self.map.place_labels = nearby_places(self.candidate.latitude, self.candidate.longitude)
        self.map.render([], [self.candidate])

    def save(self):
        try:
            values = self.form.get()
            candidate = replace(self.candidate, name=values['name'], enabled=values['enabled'],
                sound=values['sound'], desktop=values['desktop'],
                events=[event for event, control in self.events.items() if control.get()]).validate()
            if any(p.name.casefold() == candidate.name.casefold() for p in self.owner.profiles):
                raise ValueError('That location name already exists. Choose a different name.')
            if candidate.enabled and not candidate.events:
                raise ValueError('Select at least one event type, or disable monitoring for this location.')
        except ValueError as error:
            self.message.set(str(error))
            return
        self.busy = True
        self.show_step(2)
        self.message.set('Checking official NWS zones for this pin…')
        self.owner.app.run_in_thread(self.owner.resolve_location, candidate,
            on_result=lambda zones: self.resolved(candidate, zones), on_error=self.save_failed)

    def resolved(self, candidate, zones):
        if self.window._closed:
            return
        try:
            if not zones:
                raise ValueError('NWS did not return coverage zones for this pin. Choose another location.')
            if any(p.name.casefold() == candidate.name.casefold() for p in self.owner.profiles):
                raise ValueError('That location name was just used. Choose another name.')
            candidate.zones = zones
            self.owner.history.save_profile(candidate)
            self.owner.refresh_profiles(candidate)
        except Exception as error:
            self.save_failed(error)
            return
        self.owner.status.set(f'{candidate.name} saved · Monitoring preferences apply on the next refresh.')
        self.close()

    def save_failed(self, error):
        if not self.window._closed:
            self.busy = False
            self.show_step(2)
            self.message.set(f'Location not saved: {error}')

    def advanced(self):
        self.close()
        self.owner.edit_profile(new=True)

    def close(self):
        self.request += 1
        self.window.close()
