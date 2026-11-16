"""Build the recorder window without recording or persistence logic."""

from __future__ import annotations

import sys
from pathlib import Path

from ..metadata import APP_NAME


class RecorderView:
    """Own widgets and layout; delegate user actions to the controller."""

    def __init__(self, root, folder: Path, actions):
        import tkinter as tk
        from tkinter import ttk

        root.title(APP_NAME)
        icon = (
            (
                Path(sys._MEIPASS)
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2]
            )
            / "assets"
            / "speaking-recorder.ico"
        )
        if icon.exists():
            root.iconbitmap(default=str(icon))
        root.resizable(True, True)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("맑은 고딕", 10), background="#f5f6fa")
        style.configure("TButton", padding=(10, 8))
        style.configure(
            "Start.TButton",
            font=("맑은 고딕", 13, "bold"),
            foreground="white",
            background="#2459cf",
            padding=(12, 14),
        )
        style.map("Start.TButton", background=[("disabled", "#c2c8d4"), ("active", "#1945a7")])
        style.configure("Rec.TLabel", foreground="#c62828", font=("맑은 고딕", 11, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Time.TLabel", font=("Segoe UI", 29, "bold"))
        root.configure(background="#f5f6fa")
        panel = ttk.Frame(root, padding=18)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)
        panel.rowconfigure(5, weight=1)
        ttk.Sizegrip(root).place(relx=1, rely=1, anchor="se")
        ttk.Label(panel, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="영어 말하기 연습 · 원본 음성 녹음").grid(
            row=1, column=0, sticky="w", pady=(0, 12)
        )
        line = ttk.Frame(panel)
        line.grid(row=2, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Label(line, text="사용할 마이크").grid(row=0, column=0, sticky="w")
        self.refresh_button = ttk.Button(
            line, text="새로 고침 (F5)", command=actions["refresh_devices"]
        )
        self.refresh_button.grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self.mic = ttk.Combobox(line, state="readonly", width=28)
        self.mic.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.format_text = tk.StringVar(value="WAV · PCM 16-bit · Mono · 48,000 Hz 우선")
        ttk.Label(panel, textvariable=self.format_text).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        clock_line = ttk.Frame(panel)
        clock_line.grid(row=4, column=0, sticky="nsew", pady=8)
        self.timer = tk.StringVar(value="00:00")
        ttk.Label(clock_line, textvariable=self.timer, style="Time.TLabel").pack(side="left")
        self.rec_text = tk.StringVar(value="")
        ttk.Label(clock_line, textvariable=self.rec_text, style="Rec.TLabel").pack(side="right")
        self.start_button = ttk.Button(
            panel, text="녹음 시작 (Ctrl+R)", style="Start.TButton", command=actions["start"]
        )
        self.start_button.grid(row=5, column=0, sticky="nsew")
        self.stop_button = ttk.Button(
            panel, text="녹음 종료 및 저장 (Ctrl+S)", command=actions["stop"], state="disabled"
        )
        self.stop_button.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.status = tk.StringVar(value="대기")
        ttk.Label(panel, textvariable=self.status).grid(row=7, column=0, sticky="w", pady=(9, 5))
        ttk.Separator(panel).grid(row=8, column=0, sticky="ew")
        self.file_text = tk.StringVar(value="최근 저장 파일 없음")
        self.file_label = ttk.Label(panel, textvariable=self.file_text, wraplength=420)
        self.file_label.grid(row=9, column=0, sticky="ew", pady=(8, 4))
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
            controls, text="최근 파일 재생 (Ctrl+P)", command=actions["play"], state="disabled"
        )
        self.play_button.grid(row=0, column=0, sticky="ew")
        self.open_folder_button = ttk.Button(
            controls, text="저장 폴더 열기 (Ctrl+O)", command=actions["open_folder"]
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
        width = max(round(460 * scale), root.winfo_reqwidth())
        height = max(round(490 * scale), root.winfo_reqheight())
        root.geometry(f"{width}x{height}")
        root.minsize(max(round(380 * scale), root.winfo_reqwidth()), root.winfo_reqheight())
