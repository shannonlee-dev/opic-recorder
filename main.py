"""OPIc Voice Recorder — Windows 10/11, Python 3.11+, no network access."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import struct
import sys
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

APP_NAME = "OPIc Voice Recorder"
MAX_PCM_BYTES = 0xFFFFFFFF - 36 - 1  # RIFF/WAV's 32-bit size limit, even bytes.


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


def microphone_choices(audio) -> tuple[list[tuple[int, str]], int]:
    """One endpoint list, without exposing the same hardware through every driver."""
    hosts = audio.query_hostapis()
    inputs = [
        (i, item) for i, item in enumerate(audio.query_devices()) if item["max_input_channels"] > 0
    ]
    if not inputs:
        return [], -1
    priority = {"Windows WASAPI": 1, "MME": 0, "Windows DirectSound": 2, "Windows WDM-KS": 3}
    host = min(
        (item["hostapi"] for _, item in inputs), key=lambda i: priority.get(hosts[i]["name"], 4)
    )
    selected = [(i, item) for i, item in inputs if item["hostapi"] == host]
    # Legacy APIs include aliases for the default device as well as the real endpoint.
    selected = [
        (i, item)
        for i, item in selected
        if not item["name"].startswith(
            (
                "Microsoft 사운드 매퍼",
                "Microsoft Sound Mapper",
                "주 사운드 캡처",
                "Primary Sound Capture",
            )
        )
    ]
    default = hosts[host].get("default_input_device", audio.default.device[0])
    if selected and default not in [i for i, _ in selected]:
        default = selected[0][0]
    choices = []
    counts = {}
    for index, item in sorted(selected, key=lambda pair: pair[0] != default):
        name = item["name"].strip()
        if "USB Advanced Audio Device" in name:
            name = "USB 마이크"
        elif name.startswith(
            ("머리에 거는 수화기(", "머리에 거는 수화기 (", "Headset (")
        ) and name.endswith(")"):
            name = name[name.index("(") + 1 : -1] + " 마이크"
        counts[name] = counts.get(name, 0) + 1
        label = name if counts[name] == 1 else f"{name} {counts[name]}"
        if index == default:
            label += " (기본)"
        choices.append((index, label))
    return choices, default


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
    return local / "OPIcRecorder" / "settings.json"


def load_settings(path: Path) -> tuple[Path | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data["save_folder"]
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise ValueError("저장 위치가 올바른 절대 경로가 아닙니다.")
        return Path(value), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, f"설정을 읽을 수 없어 기본 저장 위치를 사용합니다.\n{exc}"


def save_settings(path: Path, folder: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="settings-",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            json.dump({"save_folder": str(folder)}, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def reserve_recording(folder: Path, started_at: datetime) -> tuple[Path, BinaryIO]:
    day = folder / started_at.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    stem = started_at.strftime("%Hh%Mm_OPIc_%Y%m%d_%H%M%S")
    index = 0
    while True:
        suffix = f"_{index:04d}" if index else ""
        path = day / f"{stem}{suffix}.wav"
        try:
            return path, path.open("x+b")  # Atomic creation, including multiple app instances.
        except FileExistsError:
            index += 1


class WaveSink:
    """Stream PCM to disk; retain complete blocks if a later write fails."""

    def __init__(self, file: BinaryIO, rate: int):
        self.file = file
        self.rate = rate
        self.frames = 0
        self.failed = False
        self.wav = wave.open(file, "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(rate)
        self.wav.writeframes(b"")
        self.file.flush()

    def write(self, data: bytes) -> None:
        if len(data) % 2:
            raise ValueError("잘못된 PCM16 오디오 데이터입니다.")
        if self.frames * 2 + len(data) > MAX_PCM_BYTES:
            raise OSError("WAV 최대 크기에 도달하여 녹음을 종료합니다.")
        try:
            self.wav.writeframesraw(data)
        except Exception:
            self.failed = True
            raise
        self.frames += len(data) // 2

    def checkpoint(self) -> None:
        self.wav.writeframes(b"")  # Update the WAV header about once per second.
        self.file.flush()

    def close(self) -> None:
        try:
            try:
                self.wav.close()
            finally:
                if self.failed:
                    # wave may have counted a partially written block. Restore only
                    # blocks whose writes completed, without relying on wave internals.
                    size = self.frames * 2
                    self.file.seek(0)
                    self.file.write(
                        struct.pack(
                            "<4sI4s4sIHHIIHH4sI",
                            b"RIFF",
                            36 + size,
                            b"WAVE",
                            b"fmt ",
                            16,
                            1,
                            1,
                            self.rate,
                            self.rate * 2,
                            2,
                            16,
                            b"data",
                            size,
                        )
                    )
                    self.file.truncate(44 + size)
                self.file.flush()
                os.fsync(self.file.fileno())
        finally:
            self.file.close()


@dataclass(frozen=True)
class RecordingResult:
    path: Path | None
    frames: int
    rate: int
    error: str
    playable: bool


class Recorder:
    """One worker owns stream + file. Tk receives messages only via events."""

    def __init__(self, audio):
        self.audio = audio
        self.events: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.stop_requested = threading.Event()

    def start(self, folder: Path, device: int) -> None:
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("이미 녹음 또는 저장 중입니다.")
        self.stop_requested.clear()
        self.thread = threading.Thread(
            target=self._run, args=(folder, device), name="OPIc recording", daemon=False
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_requested.set()

    def _run(self, folder: Path, device: int) -> None:
        blocks: queue.Queue[bytes] = queue.Queue(maxsize=256)
        callback_fault = threading.Event()
        fault_message = ""
        last_callback = time.monotonic()
        stream = None
        sink = None
        file = None
        path = None
        rate = 48000
        errors: list[str] = []
        disk_failed = False

        def callback(indata, frames, timing, status):
            nonlocal last_callback, fault_message
            last_callback = time.monotonic()
            try:
                blocks.put_nowait(bytes(indata))
            except queue.Full:
                fault_message = "저장 버퍼가 가득 찼습니다. 일부 음성이 누락될 수 있습니다."
                callback_fault.set()
            except Exception:
                fault_message = "오디오 버퍼 처리에 실패했습니다."
                callback_fault.set()
            if status:
                fault_message = f"오디오 입력 오류 ({status}). 일부 음성이 누락될 수 있습니다."
                callback_fault.set()

        try:
            info = self.audio.query_devices(device, "input")
            native = int(round(info["default_samplerate"]))
            candidates = list(
                dict.fromkeys([48000, native, 44100, 32000, 24000, 16000, 8000, 96000])
            )
            failures = []
            for candidate in candidates:
                if candidate <= 0:
                    continue
                if self.stop_requested.is_set():
                    break
                try:
                    self.audio.check_input_settings(
                        device=device, channels=1, dtype="int16", samplerate=candidate
                    )
                    stream = self.audio.RawInputStream(
                        device=device,
                        samplerate=candidate,
                        channels=1,
                        dtype="int16",
                        blocksize=0,
                        latency="high",
                        callback=callback,
                        clip_off=True,
                        dither_off=True,
                    )
                    rate = candidate
                    break
                except Exception as exc:
                    failures.append(f"{candidate}Hz: {exc}")
            if stream is None and not self.stop_requested.is_set():
                raise RuntimeError(
                    "마이크를 열 수 없습니다. 연결, Windows 마이크 권한 및 "
                    "다른 앱의 사용 여부를 확인하세요.\n" + "\n".join(failures)
                )
            if stream is not None and not self.stop_requested.is_set():
                path, file = reserve_recording(folder, datetime.now())
                sink = WaveSink(file, rate)
                started = time.monotonic()
                last_callback = started
                stream.start()
                self.events.put(("started", {"rate": rate, "started": started}))
                checkpoint_at = started
                while not self.stop_requested.is_set():
                    if callback_fault.is_set():
                        raise RuntimeError(fault_message)
                    if not stream.active:
                        raise RuntimeError("마이크 입력이 중단되었습니다. 장치 연결을 확인하세요.")
                    if time.monotonic() - last_callback > 3:
                        raise RuntimeError(
                            "3초 동안 오디오 입력이 없습니다. 마이크 연결을 확인하세요."
                        )
                    try:
                        data = blocks.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        sink.write(data)
                        if time.monotonic() - checkpoint_at >= 1:
                            sink.checkpoint()
                            checkpoint_at = time.monotonic()
                    except Exception:
                        disk_failed = True
                        raise
        except Exception as exc:
            errors.append(str(exc))
        finally:
            # Stop/close quiesces callbacks BEFORE draining: no tail data is lost.
            if stream is not None:
                for action in (stream.stop, stream.close):
                    try:
                        action()
                    except Exception as exc:
                        errors.append(f"마이크 종료 오류: {exc}")
            if callback_fault.is_set() and fault_message not in errors:
                errors.append(fault_message)
            if sink is not None:
                if not disk_failed:
                    try:
                        while True:
                            try:
                                data = blocks.get_nowait()
                            except queue.Empty:
                                break
                            sink.write(data)
                    except Exception as exc:
                        errors.append(f"버퍼 저장 실패: {exc}")
                try:
                    sink.close()
                except Exception as exc:
                    errors.append(f"WAV 파일 마무리 실패: {exc}")
            elif file is not None:
                try:
                    file.close()
                except OSError as exc:
                    errors.append(f"파일 종료 실패: {exc}")
            frames = sink.frames if sink is not None else 0
            playable = False
            if path is not None:
                if frames == 0:
                    try:
                        path.unlink()
                        path = None
                    except OSError as exc:
                        errors.append(f"빈 파일 정리 실패: {exc}")
                else:
                    try:
                        with wave.open(str(path), "rb") as check:
                            playable = (
                                check.getnchannels() == 1
                                and check.getsampwidth() == 2
                                and check.getnframes() == frames
                                and path.stat().st_size >= 44 + frames * 2
                            )
                        if not playable:
                            errors.append(
                                "WAV 검증에 실패했습니다. 파일 복구가 필요할 수 있습니다."
                            )
                    except (OSError, EOFError, wave.Error) as exc:
                        errors.append(f"WAV 검증 실패: {exc}")
            self.events.put(
                ("finished", RecordingResult(path, frames, rate, "\n".join(errors), playable))
            )


class RecorderApp:
    def __init__(self, root, audio):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.audio = audio
        self.recorder = Recorder(audio)
        self.config = settings_file()
        saved, warning = load_settings(self.config)
        self.folder = saved if saved is not None else desktop_folder() / "OPIc_Recordings"
        self.state = "idle"
        self.started = None
        self.last_file = None
        self.playable = False
        self.close_mode = None
        self.device_events = queue.Queue()
        self.devices = []
        root.title(APP_NAME)
        icon = Path(__file__).resolve().parent / "assets" / "opic-recorder.ico"
        if icon.exists():
            root.iconbitmap(default=str(icon))
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
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
        self.refresh_button = ttk.Button(line, text="새로 고침", command=self.refresh_devices)
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
            panel, text="녹음 시작", style="Start.TButton", command=self.start
        )
        self.start_button.grid(row=5, column=0, sticky="nsew")
        self.stop_button = ttk.Button(
            panel, text="녹음 종료 및 저장", command=self.stop, state="disabled"
        )
        self.stop_button.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.status = tk.StringVar(value="대기")
        ttk.Label(panel, textvariable=self.status).grid(row=7, column=0, sticky="w", pady=(9, 5))
        ttk.Separator(panel).grid(row=8, column=0, sticky="ew")
        self.file_text = tk.StringVar(value="최근 저장 파일 없음")
        self.file_label = ttk.Label(panel, textvariable=self.file_text, wraplength=420)
        self.file_label.grid(row=9, column=0, sticky="ew", pady=(8, 4))
        self.path_text = tk.StringVar(value=f"저장 위치: {self.folder}")
        # Read-only entry allows scrolling/copying even very long redirected paths.
        ttk.Entry(panel, textvariable=self.path_text, state="readonly").grid(
            row=10, column=0, sticky="ew"
        )
        controls = ttk.Frame(panel)
        controls.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        for column in range(3):
            controls.columnconfigure(column, weight=1)
        self.play_button = ttk.Button(
            controls, text="최근 파일 재생", command=self.play, state="disabled"
        )
        self.play_button.grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="저장 폴더 열기", command=self.open_folder).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self.folder_button = ttk.Button(controls, text="위치 변경", command=self.change_folder)
        self.folder_button.grid(row=0, column=2, sticky="ew")
        self.file_label.bind(
            "<Configure>", lambda event: self.file_label.configure(wraplength=max(200, event.width))
        )
        root.update_idletasks()
        scale = root.winfo_fpixels("1i") / 96
        width = max(round(460 * scale), root.winfo_reqwidth())
        height = max(round(490 * scale), root.winfo_reqheight())
        root.geometry(f"{width}x{height}")
        root.minsize(max(round(380 * scale), root.winfo_reqwidth()), root.winfo_reqheight())
        self.refresh_devices()
        self.poll_id = root.after(50, self.poll)
        if warning:
            root.after(100, lambda: self.show_warning("설정 안내", warning))

    def show_warning(self, title, message):
        from tkinter import messagebox

        messagebox.showwarning(title, message, parent=self.root)

    def refresh_devices(self):
        if self.state != "idle":
            return
        self.state = "loading"
        self.update_buttons()
        self.status.set("마이크 확인 중…")

        audio, results = self.audio, self.device_events

        def scan():
            try:
                devices, default = microphone_choices(audio)
                results.put((devices, default, None))
            except Exception as exc:
                results.put(([], -1, str(exc)))

        threading.Thread(target=scan, name="Microphone list", daemon=True).start()

    def update_buttons(self):
        idle = self.state == "idle"
        self.start_button.configure(state="normal" if idle and self.devices else "disabled")
        self.stop_button.configure(state="normal" if self.state == "recording" else "disabled")
        self.mic.configure(state="readonly" if idle else "disabled")
        self.refresh_button.configure(state="normal" if idle else "disabled")
        self.folder_button.configure(state="normal" if idle else "disabled")
        self.play_button.configure(state="normal" if idle and self.playable else "disabled")

    @staticmethod
    def stop_playback():
        import winsound

        winsound.PlaySound(None, 0)

    def start(self):
        from tkinter import messagebox

        if self.state != "idle" or self.mic.current() < 0:
            return
        issue = microphone_access_issue()
        if issue:
            messagebox.showerror("Windows 마이크 접근 차단", issue, parent=self.root)
            return
        try:
            self.stop_playback()
            self.recorder.start(self.folder, self.devices[self.mic.current()][0])
        except Exception as exc:
            messagebox.showerror("녹음 시작 실패", str(exc), parent=self.root)
            return
        self.state = "starting"
        self.started = None
        self.timer.set("00:00")
        self.status.set("마이크 여는 중…")
        self.update_buttons()

    def stop(self):
        if self.state not in ("starting", "recording"):
            return
        self.recorder.stop()
        self.state = "saving"
        self.status.set("녹음 종료 및 저장 중…")
        self.rec_text.set("")
        self.update_buttons()

    def poll(self):
        from tkinter import messagebox

        try:
            devices, default, error = self.device_events.get_nowait()
            previous = self.mic.get()
            self.devices = devices
            self.mic["values"] = [name for _, name in devices]
            if devices:
                selected = next(
                    (i for i, (_, name) in enumerate(devices) if name == previous), None
                )
                if selected is None:
                    selected = next(
                        (i for i, (index, _) in enumerate(devices) if index == default), 0
                    )
                self.mic.current(selected)
                self.status.set("대기")
            else:
                self.mic.set("")
                self.status.set("마이크 없음")
                messagebox.showerror(
                    "마이크 확인",
                    "사용 가능한 마이크가 없습니다.\n마이크 연결과 Windows 설정 → "
                    "개인 정보(및 보안) → 마이크 권한을 확인하세요.\n"
                    "새 장치가 보이지 않으면 앱을 다시 실행하세요.\n" + (error or ""),
                    parent=self.root,
                )
            self.state = "idle"
            self.update_buttons()
        except queue.Empty:
            pass
        while True:
            try:
                kind, data = self.recorder.events.get_nowait()
            except queue.Empty:
                break
            if kind == "started":
                self.started = data["started"]
                rate = data["rate"]
                suffix = " · 호환 레이트 사용" if rate != 48000 else ""
                self.format_text.set(f"WAV · PCM 16-bit · Mono · {rate:,} Hz{suffix}")
                if self.state == "starting":
                    self.state = "recording"
                    self.status.set("녹음 중")
                    self.rec_text.set("● REC")
                    self.update_buttons()
            elif kind == "finished":
                # finished is the last worker operation; wait without blocking Tk
                # until its stack has unwound before enabling another recording.
                self.root.after(10, lambda result=data: self.finish(result))
        if self.state == "recording" and self.started is not None:
            seconds = int(time.monotonic() - self.started)
            self.timer.set(f"{seconds // 60:02d}:{seconds % 60:02d}")
        self.poll_id = self.root.after(50, self.poll)

    def finish(self, result: RecordingResult):
        from tkinter import messagebox

        if self.recorder.thread.is_alive():
            self.root.after(10, lambda: self.finish(result))
            return
        self.state = "idle"
        self.rec_text.set("")
        seconds = result.frames // result.rate
        self.timer.set(f"{seconds // 60:02d}:{seconds % 60:02d}")
        discard = self.close_mode == "discard" and not result.error
        if discard and result.path is not None:
            try:
                result.path.unlink()
            except OSError as exc:
                self.close_mode = None
                self.show_warning("녹음 삭제 실패", f"파일을 보존했습니다.\n{result.path}\n{exc}")
        if result.path is not None and not discard:
            self.last_file = result.path
            self.playable = result.playable
            self.file_text.set(f"최근 파일: {result.path.name}")
            self.path_text.set(str(result.path))
        self.status.set(
            "오류 · 보존 파일 확인"
            if result.error
            else ("저장 완료" if result.path else "대기 · 녹음 데이터 없음")
        )
        self.update_buttons()
        if result.error:
            self.close_mode = None
            messagebox.showerror(
                "녹음 / 저장 오류",
                result.error
                + "\n\n"
                + (
                    f"보존된 파일: {result.path}\n음성을 확인한 뒤 다시 녹음하세요."
                    if result.path
                    else "저장된 음성 파일이 없습니다."
                )
                + "\n마이크 권한, 연결 및 저장 공간을 확인하세요.",
                parent=self.root,
            )
        elif self.close_mode:
            self.shutdown()

    def shutdown(self):
        self.stop_playback()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()

    def open_folder(self):
        from tkinter import messagebox

        try:
            folder = (
                self.last_file.parent
                if self.last_file and self.last_file.parent.exists()
                else self.folder
            )
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            messagebox.showerror("폴더 열기 실패", str(exc), parent=self.root)

    def change_folder(self):
        from tkinter import filedialog, messagebox

        selected = filedialog.askdirectory(
            title="녹음 저장 위치 선택", initialdir=str(self.folder), parent=self.root
        )
        if not selected:
            return
        try:
            folder = Path(selected)
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=folder):
                pass
            save_settings(self.config, folder)
        except OSError as exc:
            messagebox.showerror("저장 위치 변경 실패", str(exc), parent=self.root)
            return
        self.folder = folder
        self.last_file = None
        self.playable = False
        self.file_text.set("최근 저장 파일 없음")
        self.path_text.set(f"저장 위치: {folder}")
        self.update_buttons()

    def play(self):
        import winsound
        from tkinter import messagebox

        if self.state != "idle" or self.last_file is None:
            return
        try:
            winsound.PlaySound(
                str(self.last_file),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("재생 실패", str(exc), parent=self.root)

    def on_close(self):
        from tkinter import messagebox

        if self.state in ("starting", "recording"):
            answer = messagebox.askyesnocancel(
                "녹음 중 종료",
                "현재 녹음을 저장하고 종료할까요?\n\n"
                "예: 저장 후 종료\n아니요: 현재 녹음 삭제 후 종료\n"
                "취소: 계속 녹음",
                parent=self.root,
            )
            # A recording fault can finish while the modal dialog is open.
            if answer is None:
                return
            if self.state not in ("starting", "recording"):
                return
            self.close_mode = "save" if answer else "discard"
            self.stop()
        elif self.state == "saving":
            self.show_warning("저장 중", "녹음 버퍼를 저장하고 있습니다. 잠시 기다려 주세요.")
        else:
            self.shutdown()


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


if __name__ == "__main__":
    raise SystemExit(main())
