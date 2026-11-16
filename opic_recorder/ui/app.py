"""Translate user actions and recording events into desktop state."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
from pathlib import Path

from ..devices import microphone_choices
from ..recording import Recorder, RecordingResult
from ..settings import load_settings, save_settings
from ..windows import (
    desktop_folder,
    microphone_access_issue,
    open_folder,
    play_file,
    settings_file,
    stop_playback,
)
from .view import RecorderView


class RecorderApp:
    def __init__(self, root, audio):
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
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.view = RecorderView(
            root,
            self.folder,
            {
                "refresh_devices": self.refresh_devices,
                "start": self.start,
                "stop": self.stop,
                "play": self.play,
                "open_folder": self.open_folder,
                "change_folder": self.change_folder,
                "show_shortcuts": self.show_shortcuts,
            },
        )
        self.shortcut_buttons = {
            "r": self.view.start_button,
            "s": self.view.stop_button,
            "p": self.view.play_button,
            "o": self.view.open_folder_button,
            "F5": self.view.refresh_button,
        }
        # 한글 IME에서도 Ctrl 단축키가 동작하도록 Windows 가상 키를 사용한다.
        root.bind("<Control-KeyPress>", self.on_control_shortcut)
        for key in ("F5", "F1", "Escape"):
            root.bind(f"<{key}>", lambda event, action=key: self.run_shortcut(action))
        self.view.file_label.bind(
            "<Configure>",
            lambda event: self.view.file_label.configure(wraplength=max(200, event.width)),
        )
        self.refresh_devices()
        self.poll_id = root.after(50, self.poll)
        if warning:
            root.after(100, lambda: self.show_warning("설정 안내", warning))

    def on_control_shortcut(self, event):
        if event.state & 0x20008:  # AltGr 및 Ctrl+Alt 조합은 가로채지 않는다.
            return None
        key = {82: "r", 83: "s", 80: "p", 79: "o"}.get(event.keycode, event.keysym.lower())
        return self.run_shortcut(key)

    def run_shortcut(self, action):
        # 모달 창이 열린 동안에는 뒤쪽 녹음 버튼을 단축키로 실행하지 않는다.
        if self.root.grab_current() is not None:
            return None
        if action in self.shortcut_buttons:
            button = self.shortcut_buttons[action]
            if not button.instate(["disabled"]):
                button.invoke()
        elif action == "F1":
            self.show_shortcuts()
        elif action == "Escape":
            self.stop_playback()
        else:
            return None
        return "break"

    def show_shortcuts(self):
        from tkinter import messagebox

        messagebox.showinfo(
            "단축키 안내",
            "Ctrl+R  녹음 시작\n"
            "Ctrl+S  녹음 종료 및 저장\n"
            "Ctrl+P  최근 파일 재생\n"
            "Esc  재생 중지 (녹음은 계속)\n"
            "Ctrl+O  저장 폴더 열기\n"
            "F5  마이크 새로 고침\n"
            "F1  단축키 안내\n\n"
            "Tab / Shift+Tab  다음 / 이전 항목\n"
            "Space  선택한 버튼 실행\n\n"
            "앱 창이 활성화되어 있을 때 사용할 수 있습니다.\n"
            "사용할 수 없는 버튼의 단축키는 동작하지 않습니다.",
            parent=self.root,
        )

    def show_warning(self, title, message):
        from tkinter import messagebox

        messagebox.showwarning(title, message, parent=self.root)

    def refresh_devices(self):
        if self.state != "idle":
            return
        self.state = "loading"
        self.update_buttons()
        self.view.status.set("마이크 확인 중…")

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
        self.view.start_button.configure(state="normal" if idle and self.devices else "disabled")
        self.view.stop_button.configure(state="normal" if self.state == "recording" else "disabled")
        self.view.mic.configure(state="readonly" if idle else "disabled")
        self.view.refresh_button.configure(state="normal" if idle else "disabled")
        self.view.folder_button.configure(state="normal" if idle else "disabled")
        self.view.play_button.configure(state="normal" if idle and self.playable else "disabled")

    @staticmethod
    def stop_playback():
        stop_playback()

    def start(self):
        from tkinter import messagebox

        if self.state != "idle" or self.view.mic.current() < 0:
            return
        issue = microphone_access_issue()
        if issue:
            messagebox.showerror("Windows 마이크 접근 차단", issue, parent=self.root)
            return
        try:
            self.stop_playback()
            self.recorder.start(self.folder, self.devices[self.view.mic.current()][0])
        except Exception as exc:
            messagebox.showerror("녹음 시작 실패", str(exc), parent=self.root)
            return
        self.state = "starting"
        self.started = None
        self.view.timer.set("00:00")
        self.view.status.set("마이크 여는 중…")
        self.update_buttons()

    def stop(self):
        if self.state not in ("starting", "recording"):
            return
        self.recorder.stop()
        self.state = "saving"
        self.view.status.set("녹음 종료 및 저장 중…")
        self.view.rec_text.set("")
        self.update_buttons()

    def poll(self):
        from tkinter import messagebox

        try:
            devices, default, error = self.device_events.get_nowait()
            previous = self.view.mic.get()
            self.devices = devices
            self.view.mic["values"] = [name for _, name in devices]
            if devices:
                selected = next(
                    (i for i, (_, name) in enumerate(devices) if name == previous), None
                )
                if selected is None:
                    selected = next(
                        (i for i, (index, _) in enumerate(devices) if index == default), 0
                    )
                self.view.mic.current(selected)
                self.view.status.set("대기")
            else:
                self.view.mic.set("")
                self.view.status.set("마이크 없음")
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
                self.view.format_text.set(f"WAV · PCM 16-bit · Mono · {rate:,} Hz{suffix}")
                if self.state == "starting":
                    self.state = "recording"
                    self.view.status.set("녹음 중")
                    self.view.rec_text.set("● REC")
                    self.update_buttons()
            elif kind == "finished":
                # 완료 이벤트 뒤 작업 스레드가 반환할 때까지 Tk를 막지 않고 기다린다.
                self.root.after(10, lambda result=data: self.finish(result))
        if self.state == "recording" and self.started is not None:
            seconds = int(time.monotonic() - self.started)
            self.view.timer.set(f"{seconds // 60:02d}:{seconds % 60:02d}")
        self.poll_id = self.root.after(50, self.poll)

    def finish(self, result: RecordingResult):
        from tkinter import messagebox

        if self.recorder.thread.is_alive():
            self.root.after(10, lambda: self.finish(result))
            return
        self.state = "idle"
        self.view.rec_text.set("")
        seconds = result.frames // result.rate
        self.view.timer.set(f"{seconds // 60:02d}:{seconds % 60:02d}")
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
            self.view.file_text.set(f"최근 파일: {result.path.name}")
            self.view.path_text.set(str(result.path))
        self.view.status.set(
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
            open_folder(folder)
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
        self.view.file_text.set("최근 저장 파일 없음")
        self.view.path_text.set(f"저장 위치: {folder}")
        self.update_buttons()

    def play(self):
        from tkinter import messagebox

        if self.state != "idle" or self.last_file is None:
            return
        try:
            play_file(self.last_file)
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
            # 모달 창이 열린 동안에도 녹음 오류로 완료 이벤트가 도착할 수 있다.
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
