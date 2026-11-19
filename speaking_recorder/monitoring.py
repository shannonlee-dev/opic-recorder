"""Live microphone monitoring on its own duplex stream, independent of recording.

Monitoring never touches the recorder: if it glitches or fails, the recording
stream and WAV file are unaffected. It prefers WASAPI (low latency) even when the
recorder uses MME, by finding the same microphone under the WASAPI host.
"""

from __future__ import annotations

import threading
from array import array

LOW_LATENCY_HOST = "Windows WASAPI"


def _hardware(name: str) -> str:
    """'스피커(USB Audio Device)' -> 'USB Audio Device' (the physical device part)."""
    name = name.strip()
    if "(" not in name:
        return name
    return name[name.index("(") + 1 :].rstrip(")").strip()


def monitor_input(audio, device: int) -> int:
    """The same microphone under the low-latency host when available."""
    devices = audio.query_devices()
    hosts = audio.query_hostapis()
    name = devices[device]["name"].strip()
    fast = next((i for i, h in enumerate(hosts) if h["name"] == LOW_LATENCY_HOST), None)
    if fast is None or devices[device]["hostapi"] == fast:
        return device
    # MME truncates names to 31 characters, so compare by prefix.
    twin = next(
        (
            i
            for i, item in enumerate(devices)
            if item["hostapi"] == fast
            and item["max_input_channels"] > 0
            and item["name"].strip().startswith(name)
        ),
        None,
    )
    return device if twin is None else twin


def output_choices(audio, device: int) -> tuple[list[tuple[int, str]], int]:
    """Outputs usable with the monitor input; prefer the mic's own hardware (headset)."""
    devices = audio.query_devices()
    hosts = audio.query_hostapis()
    source = monitor_input(audio, device)
    host = devices[source]["hostapi"]
    outputs = [
        (i, item["name"].strip())
        for i, item in enumerate(devices)
        if item["hostapi"] == host and item["max_output_channels"] > 0
    ]
    if not outputs:
        return [], -1
    hardware = _hardware(devices[source]["name"])
    same = next((i for i, name in outputs if _hardware(name) == hardware), None)
    default = hosts[host].get("default_output_device", -1)
    indices = [i for i, _ in outputs]
    preferred = same if same is not None else (default if default in indices else indices[0])
    labels = [
        (i, name + (" (마이크와 같은 장치)" if i == same else " (기본)" if i == default else ""))
        for i, name in outputs
    ]
    return labels, preferred


def mix(data: bytes, gain: float, channels: int) -> tuple[bytes, int]:
    """Apply gain with clipping, copy mono to every output channel; return input peak."""
    samples = array("h")
    samples.frombytes(data)
    peak = max(map(abs, samples), default=0)
    scaled = array(
        "h", (max(-32768, min(32767, int(sample * gain))) for sample in samples)
    )
    if channels == 1:
        return scaled.tobytes(), peak
    out = array("h", bytes(len(scaled) * 2 * channels))
    for channel in range(channels):
        out[channel::channels] = scaled
    return out.tobytes(), peak


class Monitor:
    """Route the microphone to an output with low latency; safe to toggle any time."""

    def __init__(self, audio, native=None):
        self.audio = audio
        # Optional autotune.NativeMonitor: C++ WASAPI path (~27 ms instead of ~75 ms).
        # PortAudio below stays as the fallback when it cannot start.
        self.native = native
        self.using_native = False
        self._timeouts = 0
        self.stream = None
        self._gain = 1.0
        self.rate = 0
        self.route = None
        self.autotune = 0  # 0 off, 1 on, 2 max (see autotune.py)
        self.key = None    # (tonic, minor) from the beat, or None = automatic
        self.tuner = None  # replaced atomically; the callback reads it once per block
        self._peak = 0
        self._lock = threading.Lock()

    @property
    def gain(self) -> float:
        return self._gain

    @gain.setter
    def gain(self, value: float) -> None:
        self._gain = value
        if self.using_native:
            self.native.set_gain(value)

    @property
    def active(self) -> bool:
        if self.using_native:
            return self.native.alive() and self.native.info().wait_timeouts == self._timeouts
        return self.stream is not None and bool(self.stream.active)

    @property
    def latency_ms(self) -> int:
        """Estimated software latency (excludes USB/ADC/DAC hardware), incl. the tuner."""
        if self.using_native:
            info = self.native.info()
            tuner = 1000 * info.tuner_latency_frames / info.sample_rate if self.autotune else 0
            return round(info.estimate_ms + tuner)
        try:
            return round(sum(self.stream.latency) * 1000)
        except Exception:
            return 0

    def notes_in_use(self):
        """Key the tuner snaps to (major tonic), -1 = chromatic, None = tuner off."""
        if not self.autotune:
            return None
        if self.using_native:
            return self.native.key()
        tuner = self.tuner
        return tuner.notes_in_use() if tuner is not None else None

    def pitch(self):
        """(detected Hz, target Hz, confidence) of the live voice, or None if not analysed."""
        if self.using_native:
            return self.native.pitch()
        tuner = self.tuner  # the PortAudio fallback only analyses while tuning
        return tuner.state() if tuner is not None else None

    def capture_audio(self, base):
        """Recorder input while the native monitor owns the mic, else None."""
        if self.using_native and self.native.exclusive_input:
            from .autotune import NativeCaptureAudio

            return NativeCaptureAudio(base, self.native)
        return None

    def take_peak(self) -> float:
        """Highest input level (0.0–1.0) since the last call."""
        if self.using_native:
            return self.native.peak()
        with self._lock:
            peak, self._peak = self._peak, 0
        return peak / 32768

    def start(self, device: int, output: int) -> None:
        self.stop()
        source = monitor_input(self.audio, device)
        devices = self.audio.query_devices()
        if self.native is not None:
            try:
                self.native.start(devices[source]["name"].strip(), devices[output]["name"].strip())
            except OSError:
                pass  # fall back to PortAudio below
            else:
                self.using_native = True
                self._timeouts = self.native.info().wait_timeouts
                self.rate, self.route = self.native.info().sample_rate, (source, output)
                self.native.set_gain(self._gain)
                self.set_autotune(self.autotune, self.key)
                return
        hosts = self.audio.query_hostapis()
        out_info = devices[output]
        channels = max(1, min(2, out_info["max_output_channels"]))
        extra = None
        if hosts[out_info["hostapi"]]["name"] == LOW_LATENCY_HOST and hasattr(
            self.audio, "WasapiSettings"
        ):
            # Shared-mode WASAPI only accepts the mixer rate unless converting.
            settings = self.audio.WasapiSettings(auto_convert=True)
            extra = (settings, settings)
        rates = [
            int(round(out_info["default_samplerate"])),
            int(round(devices[source]["default_samplerate"])),
            48000,
            44100,
        ]

        def callback(indata, outdata, frames, timing, status):
            try:
                data = bytes(indata)
                tuner = self.tuner
                if tuner is not None:
                    data = tuner.process(data)
                data, peak = mix(data, self._gain, channels)
                outdata[:] = data
                with self._lock:
                    self._peak = max(self._peak, peak)
            except Exception:
                outdata[:] = bytes(len(outdata))

        failures = []
        for rate in dict.fromkeys(r for r in rates if r > 0):
            try:
                stream = self.audio.RawStream(
                    device=(source, output),
                    samplerate=rate,
                    channels=(1, channels),
                    dtype="int16",
                    latency="low",
                    callback=callback,
                    extra_settings=extra,
                )
                stream.start()
            except Exception as exc:
                failures.append(f"{rate}Hz: {exc}")
                continue
            self.stream, self.rate, self.route = stream, rate, (source, output)
            self.set_autotune(self.autotune, self.key)
            return
        raise RuntimeError(
            "모니터링을 시작할 수 없습니다. 출력 장치를 바꾸거나 다른 앱의 사용 여부를 "
            "확인하세요.\n" + "\n".join(failures)
        )

    def set_autotune(self, level: int, key=None) -> None:
        """Set live pitch correction level and key; adds the tuner's fixed delay while on."""
        self.autotune, self.key = level, key
        if self.using_native:
            self.native.set_tune(level, key)
        elif level and self.stream is not None:
            from .autotune import AutoTune

            self.tuner = AutoTune(self.rate, level, key)
        else:
            self.tuner = None

    def stop(self) -> None:
        if self.using_native:
            self.native.stop()
            self.using_native = False
        stream, self.stream = self.stream, None
        self.tuner = None
        if stream is None:
            return
        for action in (stream.stop, stream.close):
            try:
                action()
            except Exception:
                pass
