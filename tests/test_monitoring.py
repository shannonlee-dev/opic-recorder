"""Live monitoring routing and mixing with a simulated PortAudio."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from speaking_recorder.monitoring import Monitor, mix, monitor_input, output_choices


def device(name, host, inputs=0, outputs=0, rate=44100):
    return {"name": name, "hostapi": host, "max_input_channels": inputs,
            "max_output_channels": outputs, "default_samplerate": rate}


class DuplexAudio:
    """MME + WASAPI layout as seen on a PC with a USB headset."""

    def __init__(self, fail_rates=()):
        self.fail_rates = set(fail_rates)
        self.opened = []
        self.devices = [
            device("마이크(USB Advanced Audio Device", 0, inputs=2),          # 0 MME, truncated
            device("스피커(USB Advanced Audio Device", 0, outputs=2),        # 1
            device("Realtek Digital Output(Realtek(R) Audio)", 1, outputs=2, rate=48000),  # 2
            device("스피커(USB Advanced Audio Device)", 1, outputs=2, rate=48000),       # 3
            device("마이크(USB Advanced Audio Device)", 1, inputs=2, rate=48000),        # 4
        ]

    def query_devices(self, index=None, kind=None):
        return self.devices if index is None else self.devices[index]

    def query_hostapis(self):
        return [{"name": "MME", "default_output_device": 1},
                {"name": "Windows WASAPI", "default_output_device": 2}]

    def WasapiSettings(self, auto_convert=False):
        return ("wasapi", auto_convert)

    def RawStream(self, **kwargs):
        if kwargs["samplerate"] in self.fail_rates:
            raise OSError("Invalid sample rate")
        owner = self

        class Stream:
            active = False

            def start(self):
                self.active = True

            def stop(self):
                self.active = False

            def close(self):
                owner.closed = True

            def feed(self, pcm):
                out = bytearray(len(pcm) * kwargs["channels"][1])
                kwargs["callback"](pcm, out, len(pcm) // 2, None, None)
                return bytes(out)

        stream = Stream()
        self.opened.append((kwargs, stream))
        return stream


class MonitoringTests(unittest.TestCase):
    def test_mme_microphone_is_monitored_through_its_wasapi_twin(self):
        audio = DuplexAudio()
        self.assertEqual(monitor_input(audio, 0), 4)
        outputs, preferred = output_choices(audio, 0)
        self.assertEqual([i for i, _ in outputs], [2, 3])
        self.assertEqual(preferred, 3, "headset output should win over the default speaker")
        self.assertIn("마이크와 같은 장치", dict(outputs)[3])

    def test_mix_applies_gain_clips_and_duplicates_to_stereo(self):
        pcm = struct.pack("<hhh", 1000, -20000, 30000)
        data, peak = mix(pcm, 1.5, 2)
        self.assertEqual(peak, 30000)
        self.assertEqual(struct.unpack("<6h", data), (1500, 1500, -30000, -30000, 32767, 32767))
        mono, _ = mix(pcm, 0.0, 1)
        self.assertEqual(mono, bytes(6))

    def test_start_uses_low_latency_duplex_and_falls_back_on_rate(self):
        audio = DuplexAudio(fail_rates={48000})
        monitor = Monitor(audio)
        monitor.start(0, 3)
        kwargs, stream = audio.opened[-1]
        self.assertEqual(kwargs["device"], (4, 3))
        self.assertEqual(kwargs["latency"], "low")
        self.assertEqual(kwargs["channels"], (1, 2))
        self.assertEqual(kwargs["extra_settings"][0], ("wasapi", True))
        self.assertEqual(monitor.rate, 44100)
        self.assertTrue(monitor.active)
        monitor.gain = 0.5
        out = stream.feed(struct.pack("<h", 16384))
        self.assertEqual(struct.unpack("<2h", out), (8192, 8192))
        self.assertAlmostEqual(monitor.take_peak(), 0.5)
        self.assertEqual(monitor.take_peak(), 0.0)
        monitor.stop()
        self.assertFalse(monitor.active)

    def test_start_reports_every_failed_rate(self):
        monitor = Monitor(DuplexAudio(fail_rates={48000, 44100}))
        with self.assertRaises(RuntimeError) as caught:
            monitor.start(0, 3)
        self.assertIn("48000Hz", str(caught.exception))
        self.assertFalse(monitor.active)


    @unittest.skipUnless(sys.platform == "win32", "native Windows DLL")
    def test_live_autotune_runs_inside_the_monitor_callback(self):
        audio = DuplexAudio()
        monitor = Monitor(audio)
        monitor.start(0, 3)
        _, stream = audio.opened[-1]
        monitor.set_autotune(2)
        self.assertIsNotNone(monitor.tuner)
        impulse = struct.pack("<h", 20000) + bytes(2 * 2047)
        out = stream.feed(impulse)  # stereo, so 4 bytes per frame
        left = struct.unpack(f"<{len(out) // 2}h", out)[0::2]
        self.assertEqual(left[0], 0, "tuned path is delayed by the tuner latency")
        monitor.set_autotune(0)
        out = stream.feed(impulse)
        self.assertEqual(struct.unpack("<h", out[:2])[0], 20000)
        monitor.stop()
        self.assertIsNone(monitor.tuner)


class FakeNative:
    """Stands in for autotune.NativeMonitor (the C++ WASAPI engine)."""

    def __init__(self, fail=False, exclusive=True):
        self.fail, self.exclusive_input = fail, exclusive
        self.running = False
        self.calls = []
        self.captured = [struct.pack("<3h", 1, 2, 3), struct.pack("<2h", 4, 5)]
        self.timeouts = 0

    def start(self, input_name, output_name):
        self.calls.append(("start", input_name, output_name))
        if self.fail:
            raise OSError("no exclusive")
        self.running = True

    def stop(self):
        self.running = False

    def set_gain(self, gain):
        self.calls.append(("gain", gain))

    def set_tune(self, level, key):
        self.calls.append(("tune", level, key))

    def key(self):
        return 0

    def peak(self):
        return 0.5

    def pitch(self):
        return (196.0, 196.0, 0.95)

    def info(self):
        return type("Info", (), dict(wait_timeouts=self.timeouts, sample_rate=48000, estimate_ms=16.0,
                                     tuner_latency_frames=144))()

    def alive(self):
        return self.running

    def tap(self, on):
        self.calls.append(("tap", on))

    def read(self, max_frames=4096):
        return self.captured.pop(0) if self.captured else b""


class NativeMonitorPathTests(unittest.TestCase):
    def test_native_engine_is_preferred_and_controlled(self):
        native = FakeNative()
        monitor = Monitor(DuplexAudio(), native)
        monitor.start(0, 3)
        self.assertTrue(monitor.using_native)
        self.assertEqual(native.calls[0], ("start", "마이크(USB Advanced Audio Device)",
                                           "스피커(USB Advanced Audio Device)"))
        self.assertEqual(DuplexAudio().opened, [])
        monitor.gain = 0.3
        monitor.set_autotune(2, (9, True))
        self.assertIn(("gain", 0.3), native.calls)
        self.assertIn(("tune", 2, (9, True)), native.calls)
        self.assertEqual(monitor.latency_ms, 19)  # 16 ms buffers + 3.0 ms tuner
        self.assertEqual(monitor.notes_in_use(), 0)
        self.assertEqual(monitor.pitch(), (196.0, 196.0, 0.95))
        self.assertTrue(monitor.active)
        native.timeouts = 1  # the engine stalled (device unplugged)
        self.assertFalse(monitor.active)
        monitor.stop()
        self.assertFalse(native.running)

    def test_falls_back_to_portaudio_when_native_fails(self):
        audio = DuplexAudio()
        monitor = Monitor(audio, FakeNative(fail=True))
        monitor.start(0, 3)
        self.assertFalse(monitor.using_native)
        self.assertTrue(monitor.active)
        self.assertEqual(len(audio.opened), 1)
        self.assertIsNone(monitor.capture_audio(audio))

    def test_recorder_reads_every_captured_sample_through_the_tap(self):
        native = FakeNative()
        monitor = Monitor(DuplexAudio(), native)
        monitor.start(0, 3)
        tap_audio = monitor.capture_audio(DuplexAudio())
        self.assertEqual(tap_audio.query_devices(0, "input")["default_samplerate"], 48000)
        with self.assertRaises(ValueError):
            tap_audio.check_input_settings(device=0, channels=1, dtype="int16", samplerate=44100)
        received = []
        stream = tap_audio.RawInputStream(callback=lambda data, frames, t, status: received.append(data))
        stream.start()
        stream.stop()  # stop drains whatever is left
        self.assertEqual(b"".join(received), struct.pack("<5h", 1, 2, 3, 4, 5))
        self.assertEqual([c for c in native.calls if c[0] == "tap"], [("tap", True), ("tap", False)])

if __name__ == "__main__":
    unittest.main()
