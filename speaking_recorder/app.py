"""Compose the Windows GUI and concrete audio backend at startup."""

from __future__ import annotations

import sys

from .metadata import APP_NAME
from .ui.app import RecorderApp
from .windows import enable_dpi_awareness


def main() -> int:
    if sys.platform != "win32":
        print("Windows 10/11 전용 앱입니다. Windows Python에서 main.py 또는 EXE를 실행하세요.")
        return 1
    enable_dpi_awareness()
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        import sounddevice as sd

        RecorderApp(root, sd)
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"앱을 시작할 수 없습니다.\n{exc}", parent=root)
        root.destroy()
        return 1
    root.deiconify()
    root.mainloop()
    return 0
