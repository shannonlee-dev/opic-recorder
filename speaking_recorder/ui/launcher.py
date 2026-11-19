"""Full-window mode picker drawn on a single animated canvas."""

from __future__ import annotations

import math

from ..metadata import APP_NAME
from ..modes import ENGLISH, SONG
from .view import center_window, set_app_icon

IVORY = "#f3efe6"
INK = "#121214"
ENGLISH_ACCENT = "#c4553b"
SONG_ACCENT = "#d6b170"
FRAME_MS = 30


def _hex_mix(a: str, b: str, amount: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(ca, cb))


class ModeLauncher:
    """Show two panels; the hovered one widens and comes alive."""

    def __init__(self, root, on_choose):
        import tkinter as tk
        from tkinter import font

        self.root = root
        self.on_choose = on_choose
        families = set(font.families(root))
        serif = next((f for f in ("Georgia", "Cambria", "Times New Roman") if f in families), "Times")
        sans = next((f for f in ("Segoe UI", "Arial") if f in families), "Helvetica")
        self.title_font = (serif, 54, "italic")
        self.kicker_font = (sans, 9)
        self.hint_font = ("맑은 고딕", 10)
        root.title(APP_NAME)
        set_app_icon(root)
        root.configure(background=INK)
        scale = root.winfo_fpixels("1i") / 96
        width, height = round(1000 * scale), round(620 * scale)
        center_window(root, width, height)
        root.minsize(round(720 * scale), round(460 * scale))
        self.scale = scale
        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0, background=INK, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.split = 0.5
        self.target = 0.5
        self.hover = None
        self.glow = {ENGLISH: 0.0, SONG: 0.0}
        self.t = 0.0
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda event: self.set_hover(None))
        self.canvas.bind("<ButtonRelease-1>", self.on_click)
        self.bindings = {
            "<Key-1>": lambda event: self.choose(ENGLISH),
            "<Key-2>": lambda event: self.choose(SONG),
            "<Left>": lambda event: self.set_hover(ENGLISH),
            "<Right>": lambda event: self.set_hover(SONG),
            "<Return>": lambda event: self.hover and self.choose(self.hover),
        }
        for sequence, handler in self.bindings.items():
            root.bind(sequence, handler)
        self.after_id = root.after(0, self.tick)

    def mode_at(self, x):
        return ENGLISH if x < self.canvas.winfo_width() * self.split else SONG

    def on_motion(self, event):
        self.set_hover(self.mode_at(event.x))

    def on_click(self, event):
        self.choose(self.mode_at(event.x))

    def set_hover(self, mode):
        self.hover = mode
        self.target = {ENGLISH: 0.6, SONG: 0.4}.get(mode, 0.5)

    def choose(self, mode):
        if self.canvas is None:
            return
        self.destroy()
        self.on_choose(mode)

    def destroy(self):
        self.root.after_cancel(self.after_id)
        for sequence in self.bindings:
            self.root.unbind(sequence)
        self.canvas.destroy()
        self.canvas = None

    def tick(self):
        self.t += FRAME_MS / 1000
        self.split += (self.target - self.split) * 0.16
        for mode in self.glow:
            goal = 1.0 if self.hover is mode else 0.0
            self.glow[mode] += (goal - self.glow[mode]) * 0.14
        self.draw()
        self.after_id = self.root.after(FRAME_MS, self.tick)

    def draw(self):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 2 or h < 2:
            return
        c.delete("all")
        mid = round(w * self.split)
        self.draw_english(0, mid, h)
        self.draw_song(mid, w, h)
        c.create_line(mid, 0, mid, h, fill=_hex_mix(IVORY, INK, 0.5))

    def draw_panel_text(self, x0, x1, h, index, word, fg, accent, glow):
        c, s = self.canvas, self.scale
        cx = (x0 + x1) / 2
        pad = 36 * s
        c.create_text(x0 + pad, pad, text=index, anchor="nw", fill=fg, font=self.kicker_font)
        c.create_line(x0 + pad + 26 * s, pad + 8 * s, x0 + pad + (26 + 28 + 40 * glow) * s,
                      pad + 8 * s, fill=accent, width=max(1, round(s)))
        c.create_text(cx, h * 0.36, text=word, fill=fg, font=self.title_font)
        hint = _hex_mix(fg, accent, glow)
        label = "ENTER  →" if glow > 0.5 else "SELECT"
        c.create_text(cx, h - pad, text=" ".join(label), fill=_hex_mix(
            _hex_mix(fg, IVORY if fg == INK else INK, 0.55), hint, glow), font=self.kicker_font)

    def draw_english(self, x0, x1, h):
        c, s, glow = self.canvas, self.scale, self.glow[ENGLISH]
        c.create_rectangle(x0, 0, x1, h, fill=IVORY, outline="")
        cx, cy = (x0 + x1) / 2, h * 0.62
        bars, gap = 29, 9 * s
        rest = _hex_mix(IVORY, INK, 0.28)
        color = _hex_mix(rest, ENGLISH_ACCENT, glow)
        for i in range(bars):
            u = i / (bars - 1) * 2 - 1
            envelope = math.cos(u * math.pi / 2) ** 1.6
            wave = 0.55 + 0.45 * math.sin(self.t * 5.2 + i * 0.7) * math.sin(self.t * 1.7 + i * 0.31)
            amp = envelope * (0.22 + (wave - 0.22) * glow)
            half = max(2 * s, amp * 70 * s)
            x = cx + (i - bars // 2) * gap
            c.create_line(x, cy - half, x, cy + half, fill=color, width=max(2, round(3 * s)),
                          capstyle="round")
        self.draw_panel_text(x0, x1, h, "01", "English", INK, ENGLISH_ACCENT, glow)

    def draw_song(self, x0, x1, h):
        c, s, glow = self.canvas, self.scale, self.glow[SONG]
        c.create_rectangle(x0, 0, x1, h, fill=INK, outline="")
        cx, cy = (x0 + x1) / 2, h * 0.62
        rest = _hex_mix(INK, IVORY, 0.22)
        for ring in range(7):
            r = (24 + ring * 11) * s
            pulse = 0.5 + 0.5 * math.sin(self.t * 3 - ring * 0.8)
            color = _hex_mix(rest, SONG_ACCENT, glow * (0.35 + 0.65 * pulse))
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=max(1, round(s)))
        c.create_oval(cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s,
                      fill=_hex_mix(rest, SONG_ACCENT, 0.4 + 0.6 * glow), outline="")
        angle = self.t * (0.4 + 2.2 * glow)
        r = 90 * s
        px, py = cx + r * math.cos(angle), cy + r * math.sin(angle)
        c.create_oval(px - 3 * s, py - 3 * s, px + 3 * s, py + 3 * s,
                      fill=_hex_mix(rest, SONG_ACCENT, 0.3 + 0.7 * glow), outline="")
        self.draw_panel_text(x0, x1, h, "02", "Song", IVORY, SONG_ACCENT, glow)
