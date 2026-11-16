"""A light, card-based audio library with asynchronous discovery."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from ..library import scan_recordings
from ..windows import play_file, stop_playback, recycle_file

BG = '#ffffff'
CARD = '#f7f7f5'
TEXT = '#37352f'
MUTED = '#787774'
ACCENT = '#7a65b5'


class LibraryView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG, padx=24, pady=24)
        self.records = []
        self.selected = None
        self.folder = None
        self.generation = 0
        self.results = queue.Queue()
        self.page = 0
        self.idle = True
        self.delete_buttons = []
        self.on_deleted = lambda path: None
        self.label('MY WORKSPACE  /  LIBRARY', MUTED, 9).pack(anchor='w')
        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', pady=(14, 4))
        tk.Label(header, text='녹음 라이브러리', bg=BG, fg=TEXT,
                 font=('맑은 고딕', 23, 'bold')).pack(side='left')
        self.button(header, '↻  새로 고침', self.refresh).pack(side='right')
        self.summary = self.label('나의 목소리, 차곡차곡.', MUTED, 10)
        self.summary.pack(anchor='w', pady=(0, 18))
        filters = tk.Frame(self, bg=BG)
        filters.pack(fill='x')
        self.query = tk.StringVar()
        search_box = tk.Frame(filters, bg=CARD, padx=10)
        search_box.pack(side='left', fill='x', expand=True)
        tk.Label(search_box, text='검색', bg=CARD, fg=MUTED, font=('맑은 고딕', 9)).pack(side='left', padx=(0, 8))
        search = tk.Entry(search_box, textvariable=self.query, bg=CARD, fg=TEXT,
                          insertbackground=ACCENT, relief='flat', font=('맑은 고딕', 11))
        search.pack(side='left', fill='x', expand=True, ipady=10)
        self.date = tk.StringVar(value='모든 날짜')
        style = ttk.Style(self)
        style.configure('Library.TCombobox', fieldbackground=CARD, background=CARD,
                        foreground=TEXT, arrowcolor=ACCENT, borderwidth=0)
        style.map('Library.TCombobox', fieldbackground=[('readonly', CARD)],
                  foreground=[('readonly', TEXT)], selectbackground=[('readonly', CARD)],
                  selectforeground=[('readonly', TEXT)])
        self.dates = ttk.Combobox(filters, style='Library.TCombobox', textvariable=self.date, values=['모든 날짜'],
                                  state='readonly', width=12)
        self.dates.pack(side='right', padx=(10, 0), ipady=5)
        self.label('파일명 검색  ·  최신순  ·  더블클릭으로 재생', MUTED, 9).pack(anchor='w', pady=(8, 12))
        self.cards = tk.Frame(self, bg=BG, height=round(390 * self.winfo_fpixels('1i') / 96))
        self.cards.pack_propagate(False)
        self.cards.pack(fill='both', expand=True)
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill='x', pady=8)
        self.button(nav, '‹ 이전', lambda: self.turn(-1)).pack(side='left')
        self.page_label = tk.Label(nav, bg=BG, fg=MUTED, font=('맑은 고딕', 9))
        self.page_label.pack(side='left', expand=True)
        self.button(nav, '다음 ›', lambda: self.turn(1)).pack(side='right')
        player = tk.Frame(self, bg='#f7f7f5', padx=16, pady=14)
        player.pack(fill='x', pady=(8, 0))
        tk.Label(player, text='선택한 녹음', bg='#f7f7f5', fg='#8c78b6',
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        self.track = tk.Label(player, text='다시 듣고 싶은 녹음을 선택하세요', bg='#f7f7f5',
                              fg=TEXT, font=('맑은 고딕', 11, 'bold'), anchor='w', wraplength=360)
        self.track.pack(fill='x', pady=(8, 12))
        controls = tk.Frame(player, bg='#f7f7f5')
        controls.pack(fill='x')
        self.play_button = self.button(controls, '▶  선택한 녹음 재생', self.play, ACCENT)
        self.play_button.pack(side='left', fill='x', expand=True)
        self.button(controls, '■  정지', self.stop).pack(side='right', padx=(8, 0))
        self.query.trace_add('write', self.filter_changed)
        self.date.trace_add('write', self.filter_changed)
        self.render()

    def label(self, text, color, size):
        return tk.Label(self, text=text, bg=BG, fg=color, font=('맑은 고딕', size))

    @staticmethod
    def button(parent, text, command, color=TEXT):
        return tk.Button(parent, text=text, command=command, bg=CARD, fg=color,
                         activebackground='#eeedea', activeforeground=ACCENT,
                         relief='flat', bd=0, padx=12, pady=8, cursor='hand2',
                         font=('맑은 고딕', 10), disabledforeground='#a4a29d')

    def load(self, folder):
        self.folder = folder
        self.refresh()

    def refresh(self):
        if self.folder is None:
            return
        self.generation += 1
        generation, folder, results = self.generation, self.folder, self.results
        self.summary.config(text='녹음을 불러오는 중…')
        def scan():
            try:
                results.put((generation, scan_recordings(folder), None))
            except OSError as exc:
                results.put((generation, [], str(exc)))
        threading.Thread(target=scan, daemon=True).start()

    def poll(self):
        try:
            while True:
                generation, records, error = self.results.get_nowait()
                if generation != self.generation:
                    continue
                self.records = records
                if self.selected not in [r.path for r in records]:
                    self.selected = None
                    self.track.config(text='다시 듣고 싶은 녹음을 선택하세요')
                dates = ['모든 날짜'] + sorted({r.date for r in records}, reverse=True)
                self.dates.config(values=dates)
                if self.date.get() not in dates:
                    self.date.set('모든 날짜')
                self.summary.config(text=error or f'{len(records):02d}개의 녹음  ·  나만의 말하기 기록')
                self.render()
        except queue.Empty:
            pass

    def filtered(self):
        return [r for r in self.records if self.query.get().casefold() in r.path.name.casefold()
                and (self.date.get() == '모든 날짜' or self.date.get() == r.date)]

    def filter_changed(self, *args):
        self.page = 0
        self.render()

    def turn(self, delta):
        self.page = max(0, min(self.page + delta, max(0, (len(self.filtered()) - 1) // 5)))
        self.render()

    def render(self):
        self.delete_buttons = []
        for child in self.cards.winfo_children():
            child.destroy()
        records = self.filtered()
        pages = max(1, (len(records) + 4) // 5)
        self.page = min(self.page, pages - 1)
        self.page_label.config(text=f'{self.page + 1} / {pages}')
        if not records:
            tk.Label(self.cards, text='아직 녹음이 없어요\n\n왼쪽에서 첫 번째 이야기를 녹음해 보세요.\n검색 중이라면 조건을 바꿔보세요.',
                     bg=BG, fg=MUTED, font=('맑은 고딕', 12), pady=50).pack(expand=True)
        for r in records[self.page * 5:self.page * 5 + 5]:
            selected = self.selected == r.path
            card = tk.Frame(self.cards, bg='#f0ebf8' if selected else CARD,
                            highlightbackground=ACCENT if selected else CARD, highlightthickness=1,
                            padx=12, pady=10, cursor='hand2', takefocus=True)
            card.pack(fill='x', pady=(0, 7))
            icon = tk.Label(card, text='▶' if selected else '♫', bg=card['bg'],
                            fg=ACCENT if selected else '#8c78b6', font=('Segoe UI', 19))
            icon.pack(side='left', padx=(0, 12))
            delete_button = self.button(card, '삭제', lambda path=r.path: self.delete(path), '#b24d45')
            delete_button.config(bg=card['bg'], padx=8, pady=5)
            delete_button.pack(side='right', padx=(8, 0))
            self.delete_buttons.append(delete_button)
            info = tk.Frame(card, bg=card['bg'])
            info.pack(side='left', fill='x', expand=True)
            name = r.path.stem
            tk.Label(info, text=name if len(name) < 34 else name[:31] + '…', anchor='w',
                     bg=card['bg'], fg=TEXT, font=('맑은 고딕', 10, 'bold')).pack(fill='x')
            tk.Label(info, text=f'{r.date}   ·   {int(r.seconds)//60:02d}:{int(r.seconds)%60:02d}   ·   {r.size/1048576:.1f} MB',
                     anchor='w', bg=card['bg'], fg=MUTED, font=('Segoe UI', 9)).pack(fill='x', pady=(4, 0))
            def bind(widget, path):
                if isinstance(widget, tk.Button):
                    return
                widget.bind('<Button-1>', lambda e: self.select(path))
                widget.bind('<Double-Button-1>', lambda e: self.play_path(path))
                widget.bind('<Return>', lambda e: self.play_path(path))
                widget.bind('<space>', lambda e: self.select(path))
                for child in widget.winfo_children():
                    bind(child, path)
            bind(card, r.path)
        self.set_idle(self.idle)

    def select(self, path):
        self.selected = path
        self.track.config(text=path.name)
        # Update selection without destroying the widget receiving double-clicks.
        for card, r in zip(self.cards.winfo_children(), self.filtered()[self.page*5:self.page*5+5]):
            if isinstance(card, tk.Frame):
                selected = r.path == path
                color = '#f0ebf8' if selected else CARD
                card.config(highlightbackground=ACCENT if selected else CARD)
                def recolor(widget):
                    widget.config(bg=color)
                    for child in widget.winfo_children():
                        recolor(child)
                recolor(card)
                card.winfo_children()[0].config(text='▶' if selected else '♫',
                                               fg=ACCENT if selected else '#8c78b6')
        self.set_idle(self.idle)

    def set_idle(self, idle):
        self.idle = idle
        for button in self.delete_buttons:
            button.config(state='normal' if idle else 'disabled')
        self.play_button.config(state='normal' if idle and self.selected else 'disabled')

    def play_path(self, path):
        self.select(path)
        self.play()

    def play(self):
        if not self.idle or self.selected is None:
            return
        try:
            if not self.selected.is_file():
                raise OSError('파일이 이동되었거나 삭제되었습니다. 목록을 새로 고침해 주세요.')
            play_file(self.selected)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror('재생 실패', str(exc), parent=self)

    def stop(self):
        stop_playback()

    def delete(self, path):
        if not self.idle:
            return
        if not messagebox.askyesno(
            '녹음 삭제', f'이 녹음을 삭제할까요?\n\n{path.name}\n\n휴지통으로 이동합니다.',
            parent=self, icon='warning', default='no',
        ):
            return
        if not self.idle:
            return
        try:
            stop_playback()
            recycle_file(path)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror('삭제 실패', str(exc), parent=self)
            return
        self.records = [record for record in self.records if record.path != path]
        if self.selected == path:
            self.selected = None
            self.track.config(text='다시 듣고 싶은 녹음을 선택하세요')
        self.on_deleted(path)
        self.render()
        self.refresh()
