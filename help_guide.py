"""Bundled, searchable how-to documentation; opening help never starts monitoring."""
from dataclasses import dataclass
from pathlib import Path
from tkinter import font, ttk

from TkFlow import Button, Label, TextArea, TextInput, Window
from TkFlow.widget import Widget


@dataclass(frozen=True)
class Answer:
    topic: str
    question: str
    body: str

    def matches(self, query):
        text = f'{self.topic} {self.question} {self.body}'.casefold()
        return all(word in text for word in query.casefold().split())


def load_guide(path=None):
    """Read the small heading-based document without a Markdown dependency."""
    source = Path(path) if path else Path(__file__).with_name('data') / 'user_guide.md'
    answers = []
    topic = question = ''
    body = []

    def finish():
        if question:
            if not topic or not ''.join(body).strip():
                raise ValueError(f'Incomplete guide answer: {question}')
            answers.append(Answer(topic, question, '\n'.join(body).strip()))

    for line in source.read_text(encoding='utf-8').splitlines():
        if line.startswith('# '):
            finish()
            topic, question, body = line[2:].strip(), '', []
        elif line.startswith('## '):
            finish()
            question, body = line[3:].strip(), []
        else:
            body.append(line)
    finish()
    if not answers:
        raise ValueError('The user guide contains no answers')
    return tuple(answers)


class TopicTabs(Widget):
    """Scrollable vertical topic tabs, accessible with the arrow keys."""
    def __init__(self, parent, command):
        frame = ttk.Frame(parent.widget)
        self.tree = ttk.Treeview(frame, show='tree', selectmode='browse', height=15)
        self.tree.column('#0', width=245, minwidth=200, stretch=True)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind('<<TreeviewSelect>>', lambda _: command())
        self._attach(parent, frame, fill='both')


class HelpGuide:
    def __init__(self, owner):
        self.answers = load_guide()
        self.filtered = self.answers
        self.topics = tuple(dict.fromkeys(answer.topic for answer in self.answers))
        self.current_topic = self.topics[0]
        self.rebuilding = False
        self.window = Window(owner.app, 'Stormwatch · Documentation', width=1120, height=780,
                             min_width=850, min_height=550)
        self.window.root.protocol('WM_DELETE_WINDOW', self.hide)
        Label(self.window, 'Stormwatch user guide', style='Heading.TLabel')
        search_row = self.window.row(padding=0)
        Label(search_row, 'Search all topics')
        self.search = TextInput(search_row, on_change=self.filter, expand=True)
        Button(search_row, 'Clear', lambda: self.search.set(''))
        Label(self.window, 'Choose a topic on the left. Search matches all words across questions and answers.',
              style='Muted.TLabel')
        body = self.window.row(padding=0, expand=True, fill='both')
        self.navigation = TopicTabs(body, self.select_topic)
        reader = body.column(padding=0, expand=True, fill='both')
        self.heading = Label(reader, '', style='Heading.TLabel')
        self.area = TextArea(reader, readonly=True, autoscroll=False, expand=True, fill='both',
                             bg='#101c30', fg='#e5edf8', font='TkDefaultFont', padx=18, pady=14, spacing1=4, spacing3=6)
        base = font.nametofont('TkDefaultFont', root=self.window.root).actual()
        self.area.text.tag_configure('question', font=(base['family'], base['size'], 'bold'), spacing1=12)
        self.area.text.tag_configure('match', background='#ffdf80', foreground='#000000')
        footer = self.window.row(padding=0)
        self.status = Label(footer, '', style='Muted.TLabel', expand=True)
        Button(footer, 'Copy topic', self.copy_topic)
        Button(footer, 'Close', self.hide)
        self.window.root.bind('<Control-f>', self.focus_search)
        self.window.root.bind('<Escape>', lambda _: self.hide())
        self.filter('')

    def focus_search(self, event=None):
        self.search.widget.focus_set()
        self.search.widget.selection_range(0, 'end')
        return 'break'

    def show(self, topic=None):
        if topic in self.topics:
            self.current_topic = topic
            self.search.set('')
        self.window.root.deiconify()
        self.window.root.lift()

    def hide(self):
        self.window.root.withdraw()

    def filter(self, query):
        if self.window._closed:
            return
        self.filtered = tuple(answer for answer in self.answers if answer.matches(query))
        tree = self.navigation.tree
        self.rebuilding = True
        try:
            tree.delete(*tree.get_children())
            topics = tuple(dict.fromkeys(answer.topic for answer in self.filtered))
            for topic in topics:
                tree.insert('', 'end', iid=topic, text=f'{topic}  ({sum(a.topic == topic for a in self.filtered)})')
            if topics:
                if self.current_topic not in topics:
                    self.current_topic = topics[0]
                tree.selection_set(self.current_topic)
                tree.see(self.current_topic)
        finally:
            self.rebuilding = False
        self.render()

    def select_topic(self):
        if self.window._closed or self.rebuilding:
            return
        selected = self.navigation.tree.selection()
        if selected:
            self.current_topic = selected[0]
            self.render()

    def render(self):
        entries = [answer for answer in self.filtered if answer.topic == self.current_topic]
        self.heading.set(self.current_topic if entries else 'No matching answers')
        segments = []
        for answer in entries:
            segments.extend(((answer.question + '\n', 'question'), (answer.body + '\n\n', None)))
        if not entries:
            segments = [('Try fewer words, an event name, or terms such as radar, speech, or download.\n'
                         'Clear the search to browse the complete guide.', None)]
        self.area.set('')
        self.area.append_segments(segments)
        self.area.text.yview_moveto(0)
        for word in dict.fromkeys(self.search.get().split()):
            start = '1.0'
            while True:
                found = self.area.text.search(word, start, stopindex='end', nocase=True)
                if not found:
                    break
                end = f'{found}+{len(word)}c'
                self.area.text.tag_add('match', found, end)
                start = end
        topic_count = len({answer.topic for answer in self.filtered})
        self.status.set(f'{len(entries)} answers in this topic · {len(self.filtered)} matching answers '
                        f'in {topic_count} topics · {len(self.answers)} total')

    def copy_topic(self):
        self.window.root.clipboard_clear()
        self.window.root.clipboard_append(self.heading.get() + '\n\n' + self.area.get())
