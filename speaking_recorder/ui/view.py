"""Build the recorder window without recording or persistence logic."""

from __future__ import annotations

import sys
from pathlib import Path

from ..metadata import APP_NAME
from ..modes import Mode
from .library import LibraryView


def center_window(root, width: int, height: int) -> None:
    """Size the window and place it in the middle of the screen, above the taskbar."""
    taskbar = round(48 * root.winfo_fpixels("1i") / 96)
    # Never larger than the screen (high DPI scaling on a small display).
    width = min(width, root.winfo_screenwidth() - 16)
    height = min(height, root.winfo_screenheight() - taskbar - 16)
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - taskbar - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")


def set_app_icon(root) -> None:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    icon = base / "assets" / "speaking-recorder.ico"
    if icon.exists():
        root.iconbitmap(default=str(icon))


class RecorderView:
    """Own widgets and layout; delegate user actions to the controller."""

    def __init__(self, root, folder: Path, mode: Mode, actions):
        import tkinter as tk
        from tkinter import ttk

        root.title(f"{APP_NAME} · {mode.label}")
        set_app_icon(root)
        root.resizable(True, True)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("맑은 고딕", 10), background="#f7f7f5",
                        foreground="#37352f")
        style.configure("TButton", padding=(12, 9), background="#eeedea",
                        borderwidth=0, relief="flat", foreground="#37352f")
        style.map("TButton", background=[("disabled", "#f0efed"), ("active", "#e4e3df")],
                  foreground=[("disabled", "#a4a29d")])
        style.configure("TCombobox", padding=6, fieldbackground="#ffffff",
                        background="#eeedea", bordercolor="#e4e3df", arrowcolor="#787774")
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")],
                  selectbackground=[("readonly", "#ffffff")],
                  selectforeground=[("readonly", "#37352f")])
        style.configure("TEntry", padding=6, borderwidth=0, foreground="#787774")
        style.map("TEntry", fieldbackground=[("readonly", "#eeedea")])
        style.configure("TSeparator", background="#e4e3df")
        style.configure("Start.TButton", font=("맑은 고딕", 11, "bold"),
                        foreground="white", background="#37352f", padding=(16, 14))
        style.map("Start.TButton", background=[("disabled", "#e4e3df"), ("active", "#55534e")],
                  foreground=[("disabled", "#a4a29d"), ("!disabled", "#ffffff")])
        style.configure("Rec.TLabel", foreground="#d44c47", font=("맑은 고딕", 10, "bold"))
        style.configure("Title.TLabel", font=("맑은 고딕", 23, "bold"))
        style.configure("Muted.TLabel", foreground="#787774", font=("맑은 고딕", 9))
        style.configure("Time.TLabel", font=("Segoe UI", 52), foreground="#37352f")
        root.configure(background="#f7f7f5")
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        panel = ttk.Frame(body, padding=(28, 24))
        panel.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="halves")
        body.columnconfigure(1, weight=1, uniform="halves")
        body.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)
        panel.rowconfigure(5, weight=0)
        ttk.Sizegrip(root).place(relx=1, rely=1, anchor="se")
        heading = ttk.Frame(panel)
        heading.grid(row=0, column=0, sticky="ew")
        ttk.Label(heading, text=f"SPEAKING RECORDER  /  {mode.label.upper()} MODE",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Label(heading, text="오늘의 말하기", style="Title.TLabel").pack(anchor="w", pady=(14, 0))
        ttk.Label(panel, text="생각을 말하고, 나의 목소리를 기록하세요.",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 28))
        line = ttk.Frame(panel)
        line.grid(row=2, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Label(line, text="오디오 입력", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.refresh_button = ttk.Button(
            line, text="↻  새로 고침", command=actions["refresh_devices"]
        )
        self.refresh_button.grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self.mic = ttk.Combobox(line, state="readonly", width=28)
        self.mic.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.format_text = tk.StringVar(value="WAV · PCM 16-bit · Mono · 48,000 Hz 우선")
        ttk.Label(panel, textvariable=self.format_text, style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        clock_line = ttk.Frame(panel)
        clock_line.grid(row=4, column=0, sticky="nsew", pady=8)
        clock_center = ttk.Frame(clock_line)
        clock_center.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(clock_center, text="R E C O R D I N G", style="Muted.TLabel").pack()
        self.timer = tk.StringVar(value="00:00")
        ttk.Label(clock_center, textvariable=self.timer, style="Time.TLabel").pack(pady=(4, 2))
        self.rec_text = tk.StringVar(value="")
        ttk.Label(clock_center, textvariable=self.rec_text, style="Rec.TLabel").pack()
        ttk.Label(clock_center, text="한 번의 연습, 한 걸음의 성장", style="Muted.TLabel").pack(pady=(8, 0))
        clock_line.configure(height=220)
        self.start_button = ttk.Button(
            panel, text="●  녹음 시작      Ctrl+R", style="Start.TButton", command=actions["start"]
        )
        self.start_button.grid(row=5, column=0, sticky="nsew")
        self.stop_button = ttk.Button(
            panel, text="■  종료 및 저장      Ctrl+S", command=actions["stop"], state="disabled"
        )
        self.stop_button.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.status = tk.StringVar(value="대기")
        ttk.Label(panel, textvariable=self.status).grid(row=7, column=0, sticky="w", pady=(14, 14))
        ttk.Separator(panel).grid(row=8, column=0, sticky="ew")
        self.file_text = tk.StringVar(value="최근 저장 파일 없음")
        self.file_label = ttk.Label(panel, textvariable=self.file_text, wraplength=420)
        self.file_label.grid(row=9, column=0, sticky="ew", pady=(18, 8))
        self.file_label.bind(
            "<Configure>",
            lambda event: self.file_label.configure(wraplength=max(200, event.width)),
        )
        self.path_text = tk.StringVar(value=f"저장 위치: {folder}")
        # 긴 리디렉션 경로도 스크롤하거나 복사할 수 있도록 읽기 전용 입력창을 쓴다.
        ttk.Entry(panel, textvariable=self.path_text, state="readonly").grid(
            row=10, column=0, sticky="ew"
        )
        controls = ttk.Frame(panel)
        controls.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        for column in range(3):
            controls.columnconfigure(column, weight=1)
        self.play_button = ttk.Button(
            controls, text="▷  최근 녹음", command=actions["play"], state="disabled"
        )
        self.play_button.grid(row=0, column=0, sticky="ew")
        self.open_folder_button = ttk.Button(
            controls, text="저장 폴더", command=actions["open_folder"]
        )
        self.open_folder_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.folder_button = ttk.Button(
            controls, text="위치 변경", command=actions["change_folder"]
        )
        self.folder_button.grid(row=0, column=2, sticky="ew")
        ttk.Button(panel, text="단축키 안내 (F1)", command=actions["show_shortcuts"]).grid(
            row=12, column=0, sticky="e", pady=(8, 0)
        )
        root.update_idletasks()
        scale = root.winfo_fpixels("1i") / 96
        width = max(round(460 * scale), panel.winfo_reqwidth())
        height = max(round(490 * scale), root.winfo_reqheight())
        self.library = LibraryView(body)
        self.library.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        root.update_idletasks()
        width = max(width * 2, root.winfo_reqwidth())
        height = max(height, root.winfo_reqheight())
        center_window(root, width, height)
        root.minsize(width, height)
