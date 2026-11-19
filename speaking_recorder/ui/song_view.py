"""Song mode: a dark stage with one record disc, live monitoring and a takes list.

Only what singing needs is on screen. The controller is shared with English mode,
so this view exposes the same attribute names; controls it leaves out are None.
"""

from __future__ import annotations

import collections
import math
import queue
import threading
from datetime import datetime

from ..autotune import (NOTE_NAMES, RAW_FOLDER, SOLFEGE, describe_pitch, is_tuned, note_label,
                        notes_name, scale_notes)
from ..library import scan_recordings
from ..metadata import APP_NAME
from ..modes import Mode
from ..windows import play_file, recycle_file, set_playback_volume, stop_playback
from .launcher import ENGLISH_ACCENT as RED
from .launcher import INK, IVORY
from .launcher import SONG_ACCENT as GOLD
from .launcher import _hex_mix
from .view import center_window, set_app_icon

PANEL = "#19191c"
RAISED = "#232327"
MUTED = _hex_mix(IVORY, INK, 0.55)
FAINT = _hex_mix(IVORY, INK, 0.78)
VIOLET = "#8f6bd8"  # Hard Tune: the one "electronic" accent on the stage
HOT = "#e0457b"     # Hard Tune MAX
FRAME_MS = 30
PITCH_POINTS = 80  # 4 s of history at the controller's 50 ms poll
ROW_MIN = 20       # px per semitone row (before DPI scale); sets how many rows fit


class _Action:
    """A keyboard-invokable action with Tk-button-like state, drawn by the disc."""

    def __init__(self, command, state="normal"):
        self.command = command
        self.state = state

    def configure(self, state=None, **unused):
        if state is not None:
            self.state = state

    def cget(self, option):
        return self.state

    def invoke(self):
        if self.state != "disabled":
            self.command()


class SongView:
    def __init__(self, root, folder, mode: Mode, actions):
        import tkinter as tk
        from tkinter import font, ttk

        self.root = root
        root.title(f"{APP_NAME} · {mode.label}")
        set_app_icon(root)
        root.configure(background=INK)
        families = set(font.families(root))
        serif = next((f for f in ("Georgia", "Cambria", "Times New Roman") if f in families),
                     "Times")
        light = next((f for f in ("Segoe UI Light", "Segoe UI") if f in families), "Helvetica")
        self.fonts = {
            "kicker": ("Segoe UI", 9),
            "title": (serif, 26, "italic"),
            "timer": (light, 46),
            "small": ("맑은 고딕", 9),
            "body": ("맑은 고딕", 10),
            "take": (serif, 18, "italic"),
            "note": ("맑은 고딕", 22, "bold"),
        }
        self.scale = root.winfo_fpixels("1i") / 96
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Song.TCombobox", fieldbackground=RAISED, background=RAISED,
                        foreground=IVORY, arrowcolor=GOLD, bordercolor=RAISED,
                        lightcolor=RAISED, darkcolor=RAISED, padding=5)
        style.map("Song.TCombobox", fieldbackground=[("readonly", RAISED), ("disabled", PANEL)],
                  foreground=[("readonly", IVORY), ("disabled", FAINT)],
                  selectbackground=[("readonly", RAISED)], selectforeground=[("readonly", IVORY)])
        root.option_add("*TCombobox*Listbox.background", RAISED)
        root.option_add("*TCombobox*Listbox.foreground", IVORY)
        root.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        root.option_add("*TCombobox*Listbox.selectForeground", INK)

        body = tk.Frame(root, bg=INK)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2, minsize=round(340 * self.scale))  # pitch
        body.columnconfigure(2, weight=2, minsize=round(320 * self.scale))  # takes
        body.rowconfigure(0, weight=1)
        stage = tk.Frame(body, bg=INK)
        stage.grid(row=0, column=0, sticky="nsew")

        # Top: where the voice comes from.
        top = tk.Frame(stage, bg=INK, padx=28, pady=22)
        top.pack(fill="x")
        tk.Label(top, text="0 2   S O N G", bg=INK, fg=GOLD,
                 font=self.fonts["kicker"]).pack(side="left")
        self.refresh_button = self._flat(top, "↻", actions["refresh_devices"])
        self.refresh_button.pack(side="right", padx=(6, 0))
        self.mic = ttk.Combobox(top, state="readonly", width=24, style="Song.TCombobox")
        self.mic.pack(side="right")
        tk.Label(top, text="마이크", bg=INK, fg=MUTED,
                 font=self.fonts["small"]).pack(side="right", padx=(0, 8))

        # Bottom: hear yourself.
        bar = tk.Frame(stage, bg=PANEL, padx=20, pady=14)
        bar.pack(side="bottom", fill="x", padx=24, pady=(0, 24))
        line = tk.Frame(bar, bg=PANEL)
        line.pack(fill="x")
        tk.Label(line, text="내 목소리 듣기", bg=PANEL, fg=IVORY,
                 font=("맑은 고딕", 10, "bold")).pack(side="left")
        self.monitor_button = tk.Button(
            line, command=actions["toggle_monitor"], relief="flat", bd=0, padx=12, pady=3,
            cursor="hand2", font=("Segoe UI", 9, "bold"), disabledforeground=FAINT,
        )
        self.monitor_button.pack(side="left", padx=(12, 0))
        tk.Label(line, text="하드튠", bg=PANEL, fg=IVORY,
                 font=("맑은 고딕", 10, "bold")).pack(side="left", padx=(22, 0))
        self.autotune_button = tk.Button(
            line, command=actions["toggle_autotune"], relief="flat", bd=0, padx=12, pady=3,
            cursor="hand2", font=("Segoe UI", 9, "bold"), disabledforeground=FAINT,
        )
        self.autotune_button.pack(side="left", padx=(12, 0))
        self.autotune_level = 0
        self.monitor_volume_text = tk.Label(line, text="100%", width=5, anchor="e", bg=PANEL,
                                            fg=IVORY, font=("Segoe UI", 9))
        self.monitor_volume_text.pack(side="right")
        self.monitor_volume = tk.Scale(
            line, from_=0, to=150, orient="horizontal", showvalue=False,
            command=actions["monitor_volume"], bg=PANEL, troughcolor=RAISED,
            activebackground=GOLD, highlightthickness=0, bd=0, sliderrelief="flat",
            sliderlength=16, width=6, cursor="hand2", length=round(120 * self.scale),
        )
        self.monitor_volume.set(100)
        self.monitor_volume.pack(side="right", padx=(12, 4))
        # Beat key for Hard Tune: automatic, or the key/scale of the beat.
        keys = tk.Frame(bar, bg=PANEL)
        keys.pack(fill="x", pady=(10, 0))
        tk.Label(keys, text="비트 키", bg=PANEL, fg=MUTED, font=self.fonts["small"]).pack(side="left")
        self.key_box = ttk.Combobox(keys, state="readonly", width=6, style="Song.TCombobox",
                                    values=["자동", *NOTE_NAMES])
        self.key_box.current(0)
        self.key_box.pack(side="left", padx=(10, 6))
        self.scale_box = ttk.Combobox(keys, state="readonly", width=7, style="Song.TCombobox",
                                      values=["Minor", "Major"])
        self.scale_box.current(0)
        self.scale_box.pack(side="left")
        self.key_hint = tk.StringVar(value="")
        tk.Label(keys, textvariable=self.key_hint, bg=PANEL, fg=MUTED, font=self.fonts["small"],
                 anchor="e").pack(side="right")
        self._key_action = actions["key_changed"]
        for box in (self.key_box, self.scale_box):
            box.bind("<<ComboboxSelected>>", lambda event: self._key_action(self.selected_key()))
        second = tk.Frame(bar, bg=PANEL)
        second.pack(fill="x", pady=(10, 0))
        self.monitor_status = tk.StringVar(value="헤드폰을 끼고 켜 보세요")
        tk.Label(second, textvariable=self.monitor_status, bg=PANEL, fg=MUTED,
                 font=self.fonts["small"], anchor="w").pack(side="left", fill="x", expand=True)
        self.monitor_output = ttk.Combobox(second, state="readonly", width=22,
                                           style="Song.TCombobox")
        self.monitor_output.pack(side="right")
        self.monitor_output.bind("<<ComboboxSelected>>",
                                 lambda event: actions["monitor_output_changed"]())
        self.set_monitor(False, False)
        self.set_autotune(0, False)

        # Pitch: the note being sung right now, and where Hard Tune puts it.
        # Its own column between the stage and the takes, full height: more notes fit.
        pitch_column = tk.Frame(body, bg=INK, pady=22)
        pitch_column.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        self.pitch_canvas = tk.Canvas(pitch_column, bg=PANEL, highlightthickness=0, bd=0)
        self.pitch_canvas.pack(fill="both", expand=True)
        self.pitch_history = collections.deque(maxlen=PITCH_POINTS)  # (sung midi, target midi)
        self.pitch_now = None      # describe_pitch() of the last voiced moment
        self.pitch_target = None
        self.pitch_quiet = 0       # polls since the voice was last pitched
        self.pitch_live = False
        self.pitch_center = 57.0   # graph centre (midi), follows the singer smoothly

        # Center: the disc is the record button.
        self.canvas = tk.Canvas(stage, bg=INK, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.start_button = _Action(actions["start"])
        self.stop_button = _Action(actions["stop"], "disabled")
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda event: self._set_hover(False))
        self.canvas.bind("<ButtonRelease-1>", self._click)
        self.hovered = False
        self.level = 0.0
        self.t = 0.0
        self.spin = 0.0

        # State the shared controller writes; this view shows only some of it.
        self.timer = tk.StringVar(value="00:00")
        self.status = tk.StringVar(value="대기")
        self.rec_text = tk.StringVar(value="")
        self.format_text = tk.StringVar()
        self.file_text = tk.StringVar()
        self.path_text = tk.StringVar(value=str(folder))
        self.play_button = None
        self.folder_button = None

        self.library = SongTakes(body, self.fonts, self.scale)
        self.library.grid(row=0, column=2, sticky="nsew")
        self.open_folder_button = self.library.folder_button
        self.open_folder_button.configure(command=actions["open_folder"])

        width, height = round(1360 * self.scale), round(700 * self.scale)
        root.update_idletasks()
        width = max(width, root.winfo_reqwidth())
        height = max(height, root.winfo_reqheight())
        center_window(root, width, height)
        root.minsize(round(1180 * self.scale), round(620 * self.scale))
        self.after_id = root.after(FRAME_MS, self._tick)
        self.canvas.bind("<Destroy>", lambda event: self._cancel_tick())

    def _cancel_tick(self):
        try:
            self.root.after_cancel(self.after_id)
        except Exception:
            pass

    @staticmethod
    def _flat(parent, text, command):
        import tkinter as tk

        return tk.Button(parent, text=text, command=command, bg=RAISED, fg=IVORY,
                         activebackground=GOLD, activeforeground=INK, relief="flat", bd=0,
                         padx=10, pady=3, cursor="hand2", font=("Segoe UI", 10),
                         disabledforeground=FAINT)

    # Monitoring controls the controller drives.
    def set_monitor(self, on: bool, enabled: bool) -> None:
        self.monitor_button.configure(
            text="ON" if on else "OFF",
            bg=GOLD if on else RAISED,
            fg=INK if on else IVORY,
            activebackground=_hex_mix(GOLD, IVORY, 0.25) if on else FAINT,
            state="normal" if enabled else "disabled",
        )

    def set_autotune(self, level: int, enabled: bool) -> None:
        self.autotune_level = level
        color = {0: RAISED, 1: VIOLET, 2: HOT}[level]
        self.autotune_button.configure(
            text={0: "OFF", 1: "ON", 2: "MAX"}[level],
            bg=color,
            fg=IVORY,
            activebackground=_hex_mix(color, IVORY, 0.25) if level else FAINT,
            state="normal" if enabled else "disabled",
        )

    def selected_key(self):
        index = self.key_box.current()
        if index <= 0:
            return None
        return (index - 1, self.scale_box.current() == 0)

    def set_key(self, key, enabled: bool) -> None:
        self.key_box.current(0 if key is None else key[0] + 1)
        if key is not None:
            self.scale_box.current(0 if key[1] else 1)
        self.key_box.configure(state="readonly" if enabled else "disabled")
        # Scale only matters once a key is chosen.
        self.scale_box.configure(state="readonly" if enabled and key is not None else "disabled")
        self.manual_key = key

    def show_notes_in_use(self, major_tonic) -> None:
        """Auto mode: show the key the tuner detected so it can be matched to the beat."""
        manual = getattr(self, "manual_key", None)
        if manual is not None:
            self.key_hint.set(scale_notes(manual))  # what the tuner will actually use
        elif not self.autotune_level:
            self.key_hint.set("")
        elif major_tonic is None:
            self.key_hint.set("")
        elif major_tonic < 0:
            self.key_hint.set("반음 단위" if self.autotune_level == 1 else "키 듣는 중…")
        else:
            self.key_hint.set("감지: " + notes_name(major_tonic))

    def show_pitch(self, sample) -> None:
        """~20x/s from the controller: (detected Hz, target Hz, confidence), or None when the
        microphone is not being analysed (monitoring off)."""
        self.pitch_live = sample is not None
        if sample is None:
            self.pitch_history.clear()
            self.pitch_now = self.pitch_target = None
            return
        detected, target, _ = sample
        info = describe_pitch(detected)
        if info is None:
            self.pitch_quiet += 1
            self.pitch_history.append((None, None))
            return
        self.pitch_now = info
        self.pitch_target = describe_pitch(target)
        self.pitch_quiet = 0
        self.pitch_history.append((info["exact"], self.pitch_target["midi"] if self.pitch_target else None))

    def show_level(self, peak: float) -> None:
        self.level = max(peak, self.level * 0.85)

    # The disc.
    def _geometry(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        radius = min(w * 0.30, h * 0.30)
        return w / 2, h * 0.42, radius

    def _inside(self, x, y):
        cx, cy, r = self._geometry()
        return math.hypot(x - cx, y - cy) <= r

    def _set_hover(self, value):
        self.hovered = value
        self.canvas.configure(cursor="hand2" if value else "")

    def _hover(self, event):
        self._set_hover(self._inside(event.x, event.y))

    def _click(self, event):
        if not self._inside(event.x, event.y):
            return
        if self.stop_button.state != "disabled":
            self.stop_button.invoke()
        else:
            self.start_button.invoke()

    def _tick(self):
        try:
            self.t += FRAME_MS / 1000
            recording = self.stop_button.state != "disabled"
            self.spin += (FRAME_MS / 1000) * (1.6 if recording else 0.25)
            self._draw(recording)
            self._draw_pitch()
            self.after_id = self.root.after(FRAME_MS, self._tick)
        except Exception:
            pass  # The window is closing.

    def _draw_pitch(self):
        c = self.pitch_canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 2 or h < 2:
            return
        c.delete("all")
        s = self.scale
        c.create_rectangle(0, 0, w, h, fill=PANEL, outline="")
        x = 20 * s
        c.create_text(x, 30 * s, anchor="w", text="Pitch", fill=IVORY, font=self.fonts["title"])
        if not self.pitch_live:
            c.create_text(w / 2, h / 2, text="내 목소리 듣기를 켜면\n지금 부르는 음이 여기 보여요",
                          fill=MUTED, font=self.fonts["body"], justify="center")
            return
        tuned = self.autotune_level != 0
        accent = HOT if self.autotune_level == 2 else VIOLET
        # Top: the note in words.
        now, fresh = self.pitch_now, self.pitch_quiet < 6  # hold ~0.3 s through breaths
        if now is not None:
            c.create_text(x, 76 * s, anchor="w", text=now["label"],
                          fill=IVORY if fresh else FAINT, font=self.fonts["note"])
            c.create_text(x, 106 * s, anchor="w", text=f"{now['letter']}  ·  {now['hz']:.0f} Hz",
                          fill=MUTED, font=self.fonts["small"])
            off = abs(now["cents"])
            tone = GOLD if off <= 10 else (RED if off > 25 else IVORY)
            c.create_text(x, 128 * s, anchor="w", text=f"{now['cents']:+d}센트  ·  {now['advice']}",
                          fill=tone if fresh else FAINT, font=self.fonts["small"])
            if tuned and self.pitch_target is not None:
                c.create_text(x, 152 * s, anchor="w", text=f"→ 하드튠: {self.pitch_target['label']}",
                              fill=accent if fresh else FAINT, font=("맑은 고딕", 10, "bold"))
        else:
            c.create_text(x, 100 * s, anchor="w", text="소리를 내 보세요", fill=MUTED,
                          font=self.fonts["body"])
        # Below: scrolling pitch graph, one labelled row per semitone.
        x0, x1 = 12 * s, w - 14 * s
        top, bottom = 178 * s, h - 14 * s
        if bottom - top < 80 * s or x1 - x0 < 120 * s:
            return
        span = max(5, min(12, int((bottom - top) / (ROW_MIN * s) / 2)))
        sung = [m for m, _ in list(self.pitch_history)[-30:] if m is not None]
        if sung:
            middle = sorted(sung)[len(sung) // 2]
            self.pitch_center += (middle - self.pitch_center) * 0.12
        lo, hi = round(self.pitch_center) - span, round(self.pitch_center) + span
        row = (bottom - top) / (hi - lo)

        def y(m):
            return top + (hi - min(max(m, lo - 0.5), hi + 0.5)) * row

        target_now = self.pitch_target["midi"] if (self.pitch_target and fresh) else None
        if target_now is not None and lo <= target_now <= hi:
            band = _hex_mix(PANEL, accent if tuned else GOLD, 0.22)
            c.create_rectangle(x0, y(target_now) - row / 2, x1, y(target_now) + row / 2, fill=band, outline="")
        label_w = 86 * s
        for m in range(lo, hi + 1):
            natural = "#" not in SOLFEGE[m % 12]
            c.create_line(x0 + label_w, y(m), x1, y(m), fill=_hex_mix(PANEL, IVORY, 0.16 if natural else 0.07))
            # Every semitone is named; the black-key ones a little dimmer.
            c.create_text(x0 + 4 * s, y(m), anchor="w", text=note_label(m),
                          fill=_hex_mix(PANEL, IVORY, 0.6 if natural else 0.32),
                          font=("맑은 고딕", 8, "bold" if natural else "normal"))
        points = list(self.pitch_history)
        step = (x1 - (x0 + label_w)) / PITCH_POINTS

        def px(i):
            return x1 - (len(points) - 1 - i) * step

        # Target: where Hard Tune puts the voice (a faint guide when it is off).
        for i in range(1, len(points)):
            a, b = points[i - 1][1], points[i][1]
            if a is not None and a == b:
                c.create_line(px(i - 1), y(a), px(i), y(b), width=max(3, round(5 * s)),
                              fill=accent if tuned else _hex_mix(PANEL, GOLD, 0.45), capstyle="round")
        # The voice itself.
        for i in range(1, len(points)):
            a, b = points[i - 1][0], points[i][0]
            if a is not None and b is not None and abs(a - b) < 3:
                c.create_line(px(i - 1), y(a), px(i), y(b), width=max(2, round(2 * s)), fill=IVORY)
        if points and points[-1][0] is not None:
            r = 4 * s
            c.create_oval(x1 - r, y(points[-1][0]) - r, x1 + r, y(points[-1][0]) + r, fill=IVORY, outline="")

    def _draw(self, recording):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 2 or h < 2:
            return
        c.delete("all")
        cx, cy, r = self._geometry()
        s = self.scale
        ready = self.start_button.state != "disabled" or recording
        live = min(1.0, self.level ** 0.5)
        breath = 0.5 + 0.5 * math.sin(self.t * (4.0 if recording else 1.4))
        accent = RED if recording else GOLD
        if recording:
            glow = r * (1.08 + 0.05 * breath + 0.10 * live)
            c.create_oval(cx - glow, cy - glow, cx + glow, cy + glow,
                          outline=_hex_mix(INK, RED, 0.35 + 0.3 * breath), width=max(1, round(2 * s)))
        rings = 9
        for ring in range(rings):
            k = ring / (rings - 1)
            rr = r * (0.42 + 0.58 * k) * (1 + 0.04 * live * math.sin(self.t * 9 + ring))
            heat = (0.15 + 0.35 * self.hovered) if not recording else 0.35
            heat = min(1.0, heat + live * (1 - k) * 0.8)
            color = _hex_mix(_hex_mix(INK, IVORY, 0.14), accent, heat if ready else 0.05)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=color, width=max(1, round(s)))
        # The spinning groove highlight makes the disc feel like a record.
        start = math.degrees(self.spin) % 360
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=38, style="arc",
                     outline=_hex_mix(INK, accent, 0.8 if ready else 0.2), width=max(2, round(3 * s)))
        core = r * (0.34 + (0.02 * breath if recording else 0.015 * self.hovered))
        core_color = RED if recording else (_hex_mix(RED, IVORY, 0.12) if self.hovered else RED)
        if not ready:
            core_color = _hex_mix(INK, RED, 0.3)
        c.create_oval(cx - core, cy - core, cx + core, cy + core, fill=core_color, outline="")
        if recording:
            q = core * 0.32
            c.create_rectangle(cx - q, cy - q, cx + q, cy + q, fill=IVORY, outline="")
        else:
            c.create_oval(cx - 4 * s, cy - 4 * s, cx + 4 * s, cy + 4 * s, fill=INK, outline="")
        if self.autotune_level:
            text = "H A R D   T U N E" + ("   M A X" if self.autotune_level == 2 else "")
            c.create_text(cx, cy - r - 22 * s, text=text,
                          fill=HOT if self.autotune_level == 2 else VIOLET, font=self.fonts["kicker"])
        label = "탭해서 멈추기" if recording else ("탭해서 녹음" if ready else self.status.get())
        c.create_text(cx, cy + r + 30 * s, text=self.timer.get(), fill=IVORY, font=self.fonts["timer"])
        c.create_text(cx, cy + r + 66 * s, text=label,
                      fill=RED if recording else MUTED, font=self.fonts["small"])


class SongTakes:
    """Newest-first list of takes: tap to play, ✕ to send to the Recycle Bin."""

    def __init__(self, parent, fonts, scale):
        import tkinter as tk

        self.fonts = fonts
        self.scale = scale
        self.frame = tk.Frame(parent, bg=PANEL, padx=22, pady=22)
        self.records = []
        self.folder = None
        self.generation = 0
        self.results = queue.Queue()
        self.idle = True
        self.playing = None
        self.play_timer = None
        self.on_deleted = lambda path: None
        head = tk.Frame(self.frame, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Takes", bg=PANEL, fg=IVORY, font=fonts["title"]).pack(side="left")
        self.folder_button = SongView._flat(head, "폴더", None)
        self.folder_button.configure(font=fonts["small"], bg=PANEL)
        self.folder_button.pack(side="right")
        self.count = tk.Label(self.frame, text="", bg=PANEL, fg=MUTED, font=fonts["small"],
                              anchor="w")
        self.count.pack(fill="x", pady=(2, 14))
        holder = tk.Frame(self.frame, bg=PANEL)
        holder.pack(fill="both", expand=True)
        self.list_canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, bd=0)
        self.list_canvas.pack(fill="both", expand=True)
        self.rows = tk.Frame(self.list_canvas, bg=PANEL)
        window = self.list_canvas.create_window(0, 0, anchor="nw", window=self.rows)
        self.list_canvas.bind(
            "<Configure>", lambda e: self.list_canvas.itemconfigure(window, width=e.width)
        )
        self.rows.bind(
            "<Configure>",
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")),
        )
        self.frame.bind("<Enter>", lambda e: self.frame.bind_all("<MouseWheel>", self._wheel))
        self.frame.bind("<Leave>", lambda e: self.frame.unbind_all("<MouseWheel>"))
        foot = tk.Frame(self.frame, bg=PANEL)
        foot.pack(fill="x", pady=(12, 0))
        tk.Label(foot, text="재생 음량", bg=PANEL, fg=MUTED, font=fonts["small"]).pack(side="left")
        self.volume_text = tk.Label(foot, text="100%", width=5, anchor="e", bg=PANEL, fg=IVORY,
                                    font=("Segoe UI", 9))
        self.volume_text.pack(side="right")
        self.volume_scale = tk.Scale(
            foot, from_=0, to=100, orient="horizontal", showvalue=False,
            command=self.volume_changed, bg=PANEL, troughcolor=RAISED, activebackground=GOLD,
            highlightthickness=0, bd=0, sliderrelief="flat", sliderlength=16, width=6,
            cursor="hand2",
        )
        self.volume_scale.set(100)
        self.volume_scale.pack(side="left", fill="x", expand=True, padx=(10, 4))
        self.volume_changed(100)
        self.render()

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def _wheel(self, event):
        self.list_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def volume_changed(self, value):
        percent = int(float(value))
        self.volume_text.config(text=f"{percent}%")
        try:
            set_playback_volume(percent / 100)
        except OSError:
            self.volume_text.config(text="—")

    def load(self, folder):
        self.folder = folder
        self.refresh()

    def refresh(self):
        if self.folder is None:
            return
        self.generation += 1
        generation, folder, results = self.generation, self.folder, self.results

        def scan():
            try:
                results.put((generation, scan_recordings(folder)))
            except OSError:
                results.put((generation, []))

        threading.Thread(target=scan, daemon=True).start()

    def poll(self):
        try:
            while True:
                generation, records = self.results.get_nowait()
                if generation == self.generation:
                    self.records = records
                    self.render()
        except queue.Empty:
            pass

    def set_idle(self, idle):
        if idle != self.idle:
            self.idle = idle
            self.render()

    def render(self):
        import tkinter as tk

        for child in self.rows.winfo_children():
            child.destroy()
        total = len(self.records)
        self.count.config(text=f"{total}개의 테이크" if total else "")
        if not total:
            tk.Label(self.rows, text="아직 테이크가 없어요\n\n가운데 원을 눌러\n첫 곡을 불러 보세요",
                     bg=PANEL, fg=MUTED, font=self.fonts["body"], pady=60).pack(fill="x")
            return
        for position, record in enumerate(self.records):
            number = total - position
            playing = record.path == self.playing
            bg = RAISED if playing else PANEL
            row = tk.Frame(self.rows, bg=bg, padx=12, pady=9,
                           cursor="hand2" if self.idle else "")
            row.pack(fill="x", pady=(0, 2))
            tk.Label(row, text=f"{number:02d}", width=3, anchor="w", bg=bg,
                     fg=GOLD if playing or position == 0 else MUTED,
                     font=self.fonts["take"]).pack(side="left")
            when = datetime.fromtimestamp(record.modified)
            info = tk.Frame(row, bg=bg)
            info.pack(side="left", fill="x", expand=True, padx=(8, 0))
            tk.Label(info, text=("■  재생 중" if playing else f"{when:%m월 %d일}"),
                     anchor="w", bg=bg, fg=GOLD if playing else IVORY,
                     font=self.fonts["body"]).pack(fill="x")
            seconds = int(record.seconds)
            badge = "   ·   하드튠" if is_tuned(record.path) else ""
            tk.Label(info, text=f"{when:%H:%M}   ·   {seconds // 60:02d}:{seconds % 60:02d}{badge}",
                     anchor="w", bg=bg, fg=MUTED, font=("Segoe UI", 9)).pack(fill="x")
            delete = tk.Label(row, text="✕", bg=bg, fg=FAINT, font=("Segoe UI", 10),
                              cursor="hand2" if self.idle else "", padx=4)
            delete.pack(side="right")
            if self.idle:
                delete.bind("<Enter>", lambda e, w=delete: w.config(fg=RED))
                delete.bind("<Leave>", lambda e, w=delete: w.config(fg=FAINT))
                delete.bind("<ButtonRelease-1>", lambda e, p=record.path: self.delete(p))
            for widget in (row, info, *row.winfo_children(), *info.winfo_children()):
                if widget is not delete:
                    widget.bind("<ButtonRelease-1>",
                                lambda e, r=record: self.toggle(r))

    def toggle(self, record):
        from tkinter import messagebox

        if not self.idle:
            return
        if self.playing == record.path:
            self.stop()
            return
        try:
            if not record.path.is_file():
                raise OSError("파일이 이동되었거나 삭제되었습니다.")
            play_file(record.path)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("재생 실패", str(exc), parent=self.frame)
            return
        self.playing = record.path
        if self.play_timer is not None:
            self.frame.after_cancel(self.play_timer)
        # winsound has no end event; clear the highlight when the take should be over.
        self.play_timer = self.frame.after(int(record.seconds * 1000) + 300, self._ended)
        self.render()

    def _ended(self):
        self.play_timer = None
        self.playing = None
        self.render()

    def stop(self):
        stop_playback()
        if self.play_timer is not None:
            self.frame.after_cancel(self.play_timer)
        self._ended()

    def delete(self, path):
        from tkinter import messagebox

        if not self.idle:
            return
        if not messagebox.askyesno("테이크 삭제", f"이 테이크를 휴지통으로 보낼까요?\n\n{path.name}",
                                   parent=self.frame, icon="warning", default="no"):
            return
        try:
            if self.playing == path:
                self.stop()
            recycle_file(path)
            raw = path.parent / RAW_FOLDER / path.name
            if raw.exists():
                recycle_file(raw)  # the untuned original goes with its take
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("삭제 실패", str(exc), parent=self.frame)
            return
        self.records = [r for r in self.records if r.path != path]
        self.on_deleted(path)
        self.render()
        self.refresh()
