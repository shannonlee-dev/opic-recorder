"""Adapt Windows desktop, privacy, playback and display APIs."""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from pathlib import Path


def windows_folder(folder_id: str) -> Path:
    """Resolve the actual Known Folder, including OneDrive redirection."""
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("data1", wintypes.DWORD),
            ("data2", wintypes.WORD),
            ("data3", wintypes.WORD),
            ("data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    pointer = ctypes.c_void_p()
    try:
        result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer))
        if result != 0:
            raise OSError(f"Windows 폴더 경로 확인 실패 (HRESULT {result:#x})")
        return Path(ctypes.wstring_at(pointer))
    finally:
        if pointer.value:
            ole.CoTaskMemFree(pointer)


def microphone_access_issue() -> str | None:
    """Read known global privacy blocks; unknown settings never block recording."""
    if sys.platform != "win32":
        return None
    import winreg

    base = (
        r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    )
    checks = [
        (winreg.HKEY_LOCAL_MACHINE, base, "마이크 액세스"),
        (winreg.HKEY_CURRENT_USER, base, "앱에서 마이크에 액세스하도록 허용"),
        (
            winreg.HKEY_CURRENT_USER,
            base + r"\NonPackaged",
            "데스크톱 앱에서 마이크에 액세스하도록 허용",
        ),
    ]
    for hive, key_path, setting in checks:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Value")
        except OSError:
            continue
        if isinstance(value, str) and value.casefold() == "deny":
            return (
                f"Windows에서 ‘{setting}’이 꺼져 있습니다.\n\n"
                "설정 → 개인 정보 및 보안(Windows 10: 개인 정보) → 마이크에서\n"
                f"‘{setting}’을 켠 뒤 다시 녹음 시작을 눌러 주세요.\n\n"
                "장치 목록이 보여도 이 설정이 꺼져 있으면 녹음할 수 없습니다."
            )
    return None


def desktop_folder() -> Path:
    return windows_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")


def settings_file() -> Path:
    local = windows_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    current = local / "SpeakingRecorder" / "settings.json"
    # Preserve the save location configured by earlier releases.
    legacy = local / "OPIcRecorder" / "settings.json"
    return legacy if not current.exists() and legacy.exists() else current


def enable_dpi_awareness() -> None:
    try:
        user32 = ctypes.WinDLL("user32")
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def play_file(path: Path) -> None:
    """Play a WAV file asynchronously using the Windows audio service."""
    import winsound

    winsound.PlaySound(
        str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
    )


def stop_playback() -> None:
    import winsound

    winsound.PlaySound(None, 0)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))
