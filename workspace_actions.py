"""Workspace navigation, filtering, and view preferences."""
from event_catalog import event_category
from monitoring_runtime import defer_store_work


class WorkspaceActions:
    def toggle_sidebar(self):
        if not hasattr(self,'sidebar'):
            return
        if self.sidebar_visible:
            self.workspace.widget.forget(self.sidebar.widget)
        else:
            self.workspace.widget.insert(0,self.sidebar.widget,weight=0)
        self.sidebar_visible = not self.sidebar_visible


    def filter_events(self):
        if not hasattr(self,'choices'):
            return
        query = self.event_search.get().strip().casefold()
        group = self.event_group.get()
        categories = dict(Warnings='warning',Watches='watch',Advisories='advisory',Statements='statement',Outlooks='outlook',Other='other')
        for event,choice in self.choices.items():
            visible = query in event.casefold() and (group=='All' or group=='Selected' and choice.get() or
                       event_category(event)==categories.get(group))
            choice.show() if visible else choice.hide()
        self.filters.canvas.yview_moveto(0)


    def apply_event_preset(self, name):
        groups = {'Severe Weather':('Tornado','Severe Thunderstorm','Flash Flood','Flood Warning'),
                  'Winter':('Winter','Blizzard','Snow','Ice','Freeze','Cold','Freezing','Frost'),
                  'Marine':('Marine','Gale','Storm Warning','Storm Watch','Hazardous Seas','Freezing Spray','Small Craft','Coastal','Lakeshore'),
                  'Tropical':('Hurricane','Tropical','Storm Surge','Typhoon','Extreme Wind')}
        if name not in groups:
            return
        for event,choice in self.choices.items():
            choice.set(any(part in event for part in groups[name]))
        self.update_selection()
        self.filter_events()


    @defer_store_work
    def set_card_view(self, enabled):
        self.history.save_setting('compact_cards',enabled)
        self.cards.compact = enabled
        self.cards._page_signature = None
        self.cards.draw_page()


    @defer_store_work
    def set_alert_sort(self, mode):
        self.history.save_setting('alert_sort',mode)
        self.render_active()


    def show_alert_on_map(self, alert):
        self.commands.show_tab('Map')
        self.app.root.update_idletasks()
        self.map.focus(alert)


    def map_alert_selected(self, alert):
        self.cards.select(alert['id'])
        self.open_alert(alert)
