"""Record microphone audio on one worker and report lifecycle events."""

from __future__ import annotations

import queue
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .wav import WaveSink, reserve_recording


@dataclass(frozen=True)
class RecordingResult:
    path: Path | None
    frames: int
    rate: int
    error: str
    playable: bool


class Recorder:
    """Own the audio stream and file on one worker; publish events to callers."""

    def __init__(self, audio):
        self.audio = audio
        self.events: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.stop_requested = threading.Event()

    def start(self, folder: Path, device: int) -> None:
        """Start asynchronously; report opened stream and completion via events."""
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("이미 녹음 또는 저장 중입니다.")
        self.stop_requested.clear()
        self.thread = threading.Thread(
            target=self._run, args=(folder, device), name="OPIc recording", daemon=False
        )
        self.thread.start()

    def stop(self) -> None:
        """Request stop; wait for the finished event before consuming the file."""
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
            # 콜백을 먼저 정지한 뒤 큐를 비워 종료 직전 음성까지 저장한다.
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
