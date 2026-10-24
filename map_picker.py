"""Inspect coincident outlines without silently hiding the underlying messages."""
from tkinter import ttk
from TkFlow import Button, Label, TextInput, Window
from TkFlow.widget import Widget


class PickerTable(Widget):
    def __init__(self,parent):
        frame=ttk.Frame(parent.widget)
        self.tree=ttk.Treeview(frame,columns=('event','area'),show='headings',selectmode='browse')
        for name,title,width in (('event','Event',240),('area','Affected area',480)):
            self.tree.heading(name,text=title);self.tree.column(name,width=width,minwidth=100)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        self._attach(parent,frame,expand=True,fill='both')


def overlapping_alerts(app, alerts, open_alert):
    window=Window(app,'Overlapping alert messages',width=820,height=550,min_width=650,min_height=400)
    Label(window,f'{len(alerts)} alerts share this outline',style='Heading.TLabel')
    Label(window,'Snapshot when opened. Check Active Alerts for the latest status.',style='Muted.TLabel')
    def search(value):
        query=value.casefold()
        table.tree.delete(*table.tree.get_children())
        for index,alert in enumerate(alerts):
            if query in (alert['event']+' '+alert.get('area','')+' '+alert.get('headline','')).casefold():
                table.tree.insert('','end',iid=str(index),values=(alert['event'],alert.get('area','')))
        children=table.tree.get_children()
        if children:table.tree.selection_set(children[0])
        view.enable() if children else view.disable()
    Label(window,'Search event, affected area, or headline',style='Muted.TLabel')
    field=TextInput(window,on_change=search)
    table=PickerTable(window)
    def choose():
        selection=table.tree.selection()
        if selection:open_alert(alerts[int(selection[0])])
    table.tree.bind('<Double-Button-1>',lambda _:choose())
    view=Button(window,'View selected alert',choose)
    Button(window,'Close',window.close)
    search('')
    field.widget.focus_set()
    return window
