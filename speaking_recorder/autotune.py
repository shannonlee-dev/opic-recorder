"""Hard-tune pitch correction through the native trap-autotune DLL (C ABI).

The same DSP runs live (monitoring) and offline (saved takes), so a take sounds
exactly like what the singer heard. Saving never risks the original: the raw
recording is kept in a hidden ``.raw`` folder next to the tuned take.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import time
import wave
from pathlib import Path

RAW_FOLDER = ".raw"
# Levels shown in the app. MAX snaps to the key detected from the singing, so the
# voice jumps in bigger, more mechanical steps (the hard trap-vocal sound).
OFF, ON, MAX = 0, 1, 2
LABELS = {OFF: "OFF", ON: "ON", MAX: "MAX"}
NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


SOLFEGE = ["도", "도#", "레", "레#", "미", "파", "파#", "솔", "솔#", "라", "라#", "시"]
LETTERS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_label(midi: int) -> str:
    """Korean vocal convention: middle C (C4) = 2옥타브 도, G3 = 1옥타브 솔, A4 = 2옥타브 라."""
    return f"{midi // 12 - 3}옥타브 {SOLFEGE[midi % 12]}"


def letter_name(midi: int) -> str:
    return f"{LETTERS[midi % 12]}{midi // 12 - 1}"


def describe_pitch(hz: float):
    """Nearest note of a frequency: midi, Korean label, letter name, cents off, advice."""
    if not hz or hz <= 0:
        return None
    exact = 69 + 12 * math.log2(hz / 440.0)
    midi = round(exact)
    cents = round((exact - midi) * 100)
    if abs(cents) <= 10:
        advice = "정확해요"
    elif cents > 0:
        advice = "조금 높아요" if cents <= 25 else "높아요"
    else:
        advice = "조금 낮아요" if cents >= -25 else "낮아요"
    return {"midi": midi, "exact": exact, "label": note_label(midi), "letter": letter_name(midi),
            "hz": hz, "cents": cents, "advice": advice}


def key_name(key) -> str:
    """(tonic, minor) -> 'A Minor'; None -> '자동'."""
    if key is None:
        return "자동"
    tonic, minor = key
    return f"{NOTE_NAMES[tonic]} {'Minor' if minor else 'Major'}"


def scale_notes(key) -> str:
    """Notes a beat key snaps to, plus the key that uses exactly the same notes.

    Natural minor and its relative major share all 7 notes, so they tune identically.
    """
    tonic, minor = key
    major = (tonic + 3) % 12 if minor else tonic
    steps = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    # Proper spelling: each degree gets its own letter (A major -> G#, not Ab).
    letters, naturals = "CDEFGAB", [0, 2, 4, 5, 7, 9, 11]
    first = letters.index(NOTE_NAMES[tonic][0])
    spelled = []
    for degree, step in enumerate(steps):
        letter = (first + degree) % 7
        shift = ((tonic + step) - naturals[letter]) % 12
        spelled.append(letters[letter] + {0: "", 1: "#", 2: "##", 11: "b", 10: "bb"}[shift])
    notes = " ".join(spelled)
    twin = f"{NOTE_NAMES[major]} Major" if minor else f"{NOTE_NAMES[(major + 9) % 12]} Minor"
    return f"{notes}  ·  {twin}와 같은 음"


def notes_name(major_tonic: int) -> str:
    """Notes in use (major-scale tonic) as both names: 'C Major / A Minor'."""
    if major_tonic < 0:
        return ""
    return f"{NOTE_NAMES[major_tonic]} Major / {NOTE_NAMES[(major_tonic + 9) % 12]} Minor"
_lib = None


def _dll_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "native" / "ta_autotune.dll"
    return Path(__file__).resolve().parent / "native" / "ta_autotune.dll"


def _load():
    global _lib
    if _lib is None:
        if sys.platform != "win32":
            raise OSError("하드튠은 Windows에서만 사용할 수 있습니다.")
        lib = ctypes.CDLL(str(_dll_path()))
        lib.ta_version.restype = ctypes.c_int
        lib.ta_create.argtypes = [ctypes.c_double]
        lib.ta_create.restype = ctypes.c_void_p
        lib.ta_destroy.argtypes = [ctypes.c_void_p]
        lib.ta_latency.argtypes = [ctypes.c_void_p]
        lib.ta_latency.restype = ctypes.c_int64
        lib.ta_process_i16.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]
        lib.ta_set_strength.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.ta_set_key.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]
        lib.ta_key.argtypes = [ctypes.c_void_p]
        lib.ta_key.restype = ctypes.c_int32
        lib.ta_create_ex.argtypes = [ctypes.c_double, ctypes.c_int32]
        lib.ta_create_ex.restype = ctypes.c_void_p
        lib.ta_monitor_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int32,
                                         ctypes.c_char_p, ctypes.c_int32]
        lib.ta_monitor_set_gain.argtypes = [ctypes.c_float]
        lib.ta_monitor_set_tune.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
        lib.ta_monitor_peak.restype = ctypes.c_float
        lib.ta_monitor_get_info.argtypes = [ctypes.c_void_p]
        lib.ta_monitor_read.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        lib.ta_monitor_pitch.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
        lib.ta_state.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_float)] * 3
        if lib.ta_version() != 5:
            raise OSError("하드튠 엔진 버전이 맞지 않습니다.")
        _lib = lib
    return _lib


def available() -> bool:
    try:
        _load()
        return True
    except OSError:
        return False


class AutoTune:
    """One stream's pitch-correction state. Not thread-safe; one caller at a time."""

    def __init__(self, rate: int, level: int = ON, key=None, live: bool = True):
        self._lib = _load()
        # Live: ~11 ms look-ahead. Files: ~21 ms, slightly cleaner (delay is irrelevant).
        self._handle = self._lib.ta_create_ex(float(rate), 1 if live else 0)
        if not self._handle:
            raise OSError(f"하드튠을 {rate} Hz로 시작할 수 없습니다.")
        self._lib.ta_set_strength(self._handle, 1.0 if level == MAX else 0.0)
        if key is not None:
            self._lib.ta_set_key(self._handle, key[0], int(key[1]))
        self.rate = rate
        self.latency = int(self._lib.ta_latency(self._handle))

    def state(self):
        """(detected Hz, target Hz, confidence) of the latest analysis; 0 Hz = unvoiced."""
        values = [ctypes.c_float() for _ in range(3)]
        if self._handle:
            self._lib.ta_state(self._handle, *(ctypes.byref(v) for v in values))
        return tuple(v.value for v in values)

    def notes_in_use(self) -> int:
        """Major-scale tonic of the notes being snapped to; -1 = chromatic / no key yet."""
        return int(self._lib.ta_key(self._handle)) if self._handle else -1

    def process(self, pcm: bytes) -> bytes:
        """Mono int16 PCM in, same length out (delayed by ``latency`` frames)."""
        frames = len(pcm) // 2
        if not frames:
            return b""
        buffer = (ctypes.c_int16 * frames).from_buffer_copy(pcm[: frames * 2])
        self._lib.ta_process_i16(self._handle, buffer, buffer, frames)
        return bytes(buffer)

    def close(self) -> None:
        if self._handle:
            self._lib.ta_destroy(self._handle)
            self._handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def tune_file(source: Path, destination: Path, level: int = ON, key=None,
              chunk: int = 1 << 16) -> None:
    """Tune a mono 16-bit WAV; output is time-aligned with the input (latency removed)."""
    with wave.open(str(source), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ValueError("모노 16-bit WAV만 하드튠할 수 있습니다.")
        rate = reader.getframerate()
        total = reader.getnframes()
        tuner = AutoTune(rate, level, key, live=False)
        try:
            with wave.open(str(destination), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(rate)
                skip = tuner.latency * 2
                while True:
                    data = reader.readframes(chunk)
                    if not data:
                        break
                    out = tuner.process(data)
                    if skip:
                        cut = min(skip, len(out))
                        out, skip = out[cut:], skip - cut
                    writer.writeframes(out)
                # Flush the delay line so the last note is not cut off.
                tail = tuner.process(bytes(tuner.latency * 2))
                writer.writeframes(tail[skip:])
        finally:
            tuner.close()
    with wave.open(str(destination), "rb") as check:
        if check.getnframes() != total:
            raise OSError("하드튠 결과 길이가 원본과 다릅니다.")


def apply_to_take(path: Path, level: int = ON, key=None) -> Path:
    """Replace a take with its tuned version; return where the raw original was kept."""
    temp = path.with_name(path.name + ".tuning")
    raw_dir = path.parent / RAW_FOLDER
    raw = raw_dir / path.name
    try:
        tune_file(path, temp, level, key)
        raw_dir.mkdir(exist_ok=True)
        os.replace(path, raw)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    try:
        os.replace(temp, path)
    except OSError:
        os.replace(raw, path)  # put the original back rather than lose the take
        temp.unlink(missing_ok=True)
        raise
    return raw


def is_tuned(path: Path) -> bool:
    return (path.parent / RAW_FOLDER / path.name).exists()


class _Info(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in (
        "input_exclusive", "output_exclusive", "input_period_frames", "output_period_frames",
        "fifo_frames", "tuner_latency_frames", "sample_rate")] + [("estimate_ms", ctypes.c_double)] + [
        (name, ctypes.c_uint64) for name in (
            "underruns", "input_glitches", "fifo_starved", "wait_timeouts", "tap_dropped")]


class NativeMonitor:
    """Low-latency WASAPI monitor in the DLL (exclusive mic, shared headphones).

    The tuner runs inside the C++ audio thread. Devices are matched by the endpoint
    name Windows shows, which is what PortAudio's WASAPI host reports too.
    """

    def __init__(self):
        self._lib = _load()
        self.running = False
        self.exclusive_input = False

    def start(self, input_name: str, output_name: str) -> None:
        self.stop()
        error = ctypes.create_string_buffer(1024)
        failures = []
        # Exclusive input gives 3 ms buffers; it fails if another app holds the mic.
        for exclusive in (1, 0):
            if self._lib.ta_monitor_start(input_name.encode(), output_name.encode(), exclusive, error, 1024):
                self.running = True
                self.exclusive_input = bool(self.info().input_exclusive)
                return
            failures.append(error.value.decode(errors="replace"))
        raise OSError("저지연 모니터를 시작할 수 없습니다.\n" + "\n".join(failures))

    def stop(self) -> None:
        if self.running:
            self._lib.ta_monitor_stop()
        self.running = False

    def set_gain(self, gain: float) -> None:
        self._lib.ta_monitor_set_gain(gain)

    def set_tune(self, level: int, key) -> None:
        tonic, minor = key if key is not None else (-1, False)
        self._lib.ta_monitor_set_tune(level, tonic, int(minor))

    def key(self) -> int:
        return int(self._lib.ta_monitor_key())

    def peak(self) -> float:
        return float(self._lib.ta_monitor_peak())

    def pitch(self):
        values = [ctypes.c_float() for _ in range(3)]
        self._lib.ta_monitor_pitch(*(ctypes.byref(v) for v in values))
        return tuple(v.value for v in values)

    def info(self) -> _Info:
        info = _Info()
        self._lib.ta_monitor_get_info(ctypes.byref(info))
        return info

    def alive(self) -> bool:
        return self.running and bool(self._lib.ta_monitor_running())

    def tap(self, on: bool) -> None:
        self._lib.ta_monitor_tap(1 if on else 0)

    def read(self, max_frames: int = 4096) -> bytes:
        buffer = (ctypes.c_int16 * max_frames)()
        frames = self._lib.ta_monitor_read(buffer, max_frames)
        return bytes(buffer)[: frames * 2]


class NativeCaptureAudio:
    """sounddevice-shaped input for Recorder that reads the monitor's microphone.

    With exclusive capture nothing else can open the mic, so the recording takes the
    exact samples the monitor captured (48 kHz mono int16).
    """

    RATE = 48000

    def __init__(self, base, monitor: NativeMonitor):
        self.base = base
        self.monitor = monitor

    def query_devices(self, device=None, kind=None):
        info = self.base.query_devices(device, kind)
        return dict(info, default_samplerate=self.RATE) if device is not None else info

    def check_input_settings(self, **kwargs):
        if kwargs.get("samplerate") != self.RATE or kwargs.get("channels") != 1 or kwargs.get("dtype") != "int16":
            raise ValueError("모니터 입력은 48 kHz 모노 16-bit만 제공합니다.")

    def RawInputStream(self, callback=None, **kwargs):
        return _TapStream(self.monitor, callback)


class _TapStream:
    def __init__(self, monitor: NativeMonitor, callback):
        self.monitor = monitor
        self.callback = callback
        self.active = False
        self._stop = threading.Event()
        self._thread = None

    def _deliver(self) -> int:
        data = self.monitor.read()
        if data:
            self.callback(data, len(data) // 2, None, False)
        return len(data)

    def _pump(self):
        while not self._stop.is_set():
            if not self.monitor.alive():
                self.active = False  # the recorder reports the interruption
                return
            if not self._deliver():
                time.sleep(0.004)

    def start(self):
        self.monitor.tap(True)
        self.active = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="Monitor tap", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        while self._deliver():  # the last samples before stop still belong to the take
            pass
        self.monitor.tap(False)
        self.active = False

    def close(self):
        pass

