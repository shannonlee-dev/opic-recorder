"""Reserve unique recordings and preserve complete PCM blocks on disk."""

from __future__ import annotations

import os
import struct
import wave
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

MAX_PCM_BYTES = 0xFFFFFFFF - 36 - 1  # RIFF/WAV 크기 제한에 맞춘 짝수 바이트 수.


def reserve_recording(folder: Path, started_at: datetime) -> tuple[Path, BinaryIO]:
    day = folder / started_at.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    stem = started_at.strftime("%Hh%Mm_OPIc_%Y%m%d_%H%M%S")
    index = 0
    while True:
        suffix = f"_{index:04d}" if index else ""
        path = day / f"{stem}{suffix}.wav"
        try:
            return path, path.open("x+b")  # 여러 앱 인스턴스에서도 기존 파일을 덮어쓰지 않는다.
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
        self.wav.writeframes(b"")  # 강제 종료 시 복구 가능한 길이를 헤더에 반영한다.
        self.file.flush()

    def close(self) -> None:
        try:
            try:
                self.wav.close()
            finally:
                if self.failed:
                    # 부분 기록된 블록은 제외하고 성공한 블록까지만 헤더와 크기를 복원한다.
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
