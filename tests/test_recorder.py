"""Real WAV/filesystem tests; only the microphone hardware is simulated."""

import importlib.util
import math
import struct
import sys
import time
import unittest
import wave
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImplementationExists(unittest.TestCase):
    def test_executable_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("main"), "main.py is missing")


if importlib.util.find_spec("main"):
    import main
else:
    main = None


class FakeAudio:
    """PortAudio boundary: hardware unavailable in headless unit tests."""

    def __init__(
        self,
        rate=48000,
        disconnect=False,
        start_error=False,
        chunks=None,
        status=False,
        tail=b"\xde\x00",
    ):
        self.rate = rate
        self.disconnect = disconnect
        self.start_error = start_error
        self.chunks = chunks if chunks is not None else [struct.pack("<hhh", 1000, -1000, 0)]
        self.status = status
        self.tail = tail
        self.stream = None
        self.default = type("Default", (), {"device": (0, 1)})()

    def query_devices(self, device=None, kind=None):
        info = {
            "name": "Test microphone",
            "hostapi": 0,
            "max_input_channels": 1,
            "default_samplerate": self.rate,
        }
        return [info] if device is None else info

    def query_hostapis(self):
        return [{"name": "Test API"}]

    def check_input_settings(self, **kwargs):
        if kwargs["samplerate"] != self.rate:
            raise ValueError("Unsupported rate")

    def RawInputStream(self, **kwargs):
        if kwargs["dtype"] != "int16" or kwargs["channels"] != 1:
            raise AssertionError("PCM16 mono required")
        owner = self

        class Stream:
            active = False

            def start(self):
                if owner.start_error:
                    raise OSError("Microphone access denied")
                self.active = True
                for chunk in owner.chunks:
                    kwargs["callback"](chunk, len(chunk) // 2, None, owner.status)
                if owner.disconnect:
                    self.active = False

            def stop(self):
                if self.active:
                    # A callback can finish while stop waits for the stream.
                    kwargs["callback"](owner.tail, len(owner.tail) // 2, None, False)
                self.active = False

            def close(self):
                self.active = False

        self.stream = Stream()
        return self.stream


@unittest.skipIf(main is None, "Implementation not yet written")
class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def wait_event(self, recorder, kind):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            event = recorder.events.get(timeout=4)
            if event[0] == kind:
                return event[1]
        self.fail(f"Missing {kind} event")

    def finish(self, recorder):
        recorder.stop()
        result = self.wait_event(recorder, "finished")
        recorder.thread.join(3)
        self.assertFalse(recorder.thread.is_alive())
        return result

    def test_unique_names_never_overwrite_and_use_start_date(self):
        stamp = datetime(2026, 11, 15, 23, 59, 59)
        paths = []
        for _ in range(3):
            path, file = main.reserve_recording(self.root, stamp)
            file.write(b"keep")
            file.close()
            paths.append(path)
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(paths[0].name, "23h59m_OPIc_20261115_235959.wav")
        self.assertEqual(paths[0].parent.name, "2026-11-15")
        self.assertTrue(all(p.read_bytes() == b"keep" for p in paths))

    def test_microphone_choices_hide_duplicate_drivers_and_mark_default(self):
        class DeviceList:
            default = type("Default", (), {"device": (0, 1)})()

            def query_hostapis(self):
                return [
                    {"name": "MME", "default_input_device": 0},
                    {"name": "Windows WASAPI", "default_input_device": 3},
                    {"name": "Windows WDM-KS", "default_input_device": 4},
                ]

            def query_devices(self):
                return [
                    {
                        "name": "마이크(USB Advanced Audio Device)",
                        "hostapi": 0,
                        "max_input_channels": 2,
                    },
                    {
                        "name": "머리에 거는 수화기(JBL Tour Pro 3)",
                        "hostapi": 0,
                        "max_input_channels": 1,
                    },
                    {
                        "name": "머리에 거는 수화기(JBL Tour Pro 3)",
                        "hostapi": 1,
                        "max_input_channels": 1,
                    },
                    {
                        "name": "마이크(USB Advanced Audio Device)",
                        "hostapi": 1,
                        "max_input_channels": 2,
                    },
                    {"name": "연결 안 된 마이크", "hostapi": 2, "max_input_channels": 2},
                ]

        choices, default = main.microphone_choices(DeviceList())
        self.assertEqual(default, 0)
        self.assertEqual(choices, [(0, "USB 마이크 (기본)"), (1, "JBL Tour Pro 3 마이크")])

    def test_settings_persist_and_corruption_is_reported(self):
        config = self.root / "settings.json"
        folder = self.root / "한글 녹음 폴더"
        main.save_settings(config, folder)
        self.assertEqual(main.load_settings(config), (folder, None))
        config.write_text("{broken", encoding="utf-8")
        path, warning = main.load_settings(config)
        self.assertIsNone(path)
        self.assertTrue(warning)

    def test_recording_drains_final_callback_and_repeated_runs(self):
        rec = main.Recorder(FakeAudio())
        paths = []
        for _ in range(3):
            rec.start(self.root, 0)
            self.wait_event(rec, "started")
            with self.assertRaises(RuntimeError):
                rec.start(self.root, 0)
            result = self.finish(rec)
            self.assertFalse(result.error)
            paths.append(result.path)
            with wave.open(str(result.path), "rb") as audio:
                self.assertEqual(
                    (
                        audio.getnchannels(),
                        audio.getsampwidth(),
                        audio.getframerate(),
                        audio.getnframes(),
                    ),
                    (1, 2, 48000, 4),
                )
                self.assertEqual(audio.getcomptype(), "NONE")
                self.assertEqual(audio.readframes(4), struct.pack("<hhhh", 1000, -1000, 0, 222))
        self.assertEqual(len(set(paths)), 3)

    def test_unsupported_48khz_uses_native_rate(self):
        rec = main.Recorder(FakeAudio(rate=44100))
        rec.start(self.root, 0)
        info = self.wait_event(rec, "started")
        self.assertEqual(info["rate"], 44100)
        result = self.finish(rec)
        with wave.open(str(result.path), "rb") as audio:
            self.assertEqual(audio.getframerate(), 44100)

    def test_disconnect_preserves_already_received_pcm(self):
        rec = main.Recorder(FakeAudio(disconnect=True))
        rec.start(self.root, 0)
        result = self.wait_event(rec, "finished")
        rec.thread.join(3)
        self.assertTrue(result.error)
        with wave.open(str(result.path), "rb") as audio:
            self.assertEqual(audio.readframes(3), struct.pack("<hhh", 1000, -1000, 0))

    def test_permission_error_leaves_no_empty_recording(self):
        rec = main.Recorder(FakeAudio(start_error=True))
        rec.start(self.root, 0)
        result = self.wait_event(rec, "finished")
        rec.thread.join(3)
        self.assertTrue(result.error)
        self.assertIsNone(result.path)
        self.assertEqual(list(self.root.rglob("*.wav")), [])

    def test_disk_write_failure_preserves_complete_previous_frames(self):
        path, file = main.reserve_recording(self.root, datetime.now())
        sink = main.WaveSink(file, 48000)
        sink.write(struct.pack("<hh", 10, 20))
        original = sink.wav.writeframesraw

        def failed_write(data):
            original(data[:2])
            raise OSError("Disk full")

        sink.wav.writeframesraw = failed_write
        with self.assertRaises(OSError):
            sink.write(struct.pack("<hh", 30, 40))
        sink.close()
        with wave.open(str(path), "rb") as audio:
            self.assertEqual(audio.getnframes(), 2)
            self.assertEqual(audio.readframes(100), struct.pack("<hh", 10, 20))

    def test_30_seconds_pcm_roundtrip_has_no_missing_or_changed_samples(self):
        cycle = struct.pack(
            "<480h", *(int(16000 * math.sin(2 * math.pi * i / 480)) for i in range(480))
        )
        chunk = cycle * 30
        rec = main.Recorder(FakeAudio(chunks=[chunk] * 100, tail=b""))
        rec.start(self.root, 0)
        self.wait_event(rec, "started")
        result = self.finish(rec)
        self.assertFalse(result.error)
        with wave.open(str(result.path), "rb") as audio:
            self.assertEqual(audio.getnframes(), 1440000)
            self.assertEqual(audio.readframes(1440000), cycle * 3000)

    def test_buffer_overflow_stops_and_keeps_queued_audio(self):
        rec = main.Recorder(FakeAudio(chunks=[b"\x01\x00"] * 300, tail=b""))
        rec.start(self.root, 0)
        result = self.wait_event(rec, "finished")
        rec.thread.join(3)
        self.assertTrue(result.error)
        self.assertTrue(result.playable)
        with wave.open(str(result.path), "rb") as audio:
            self.assertEqual(audio.getnframes(), 256)

    def test_input_overflow_is_reported_and_received_audio_kept(self):
        rec = main.Recorder(FakeAudio(status="input overflow", tail=b""))
        rec.start(self.root, 0)
        result = self.wait_event(rec, "finished")
        rec.thread.join(3)
        self.assertIn("input overflow", result.error)
        self.assertTrue(result.playable)
        self.assertEqual(result.frames, 3)

    def test_unwritable_destination_reports_error_and_stops_worker(self):
        blocked = self.root / "not-a-directory"
        blocked.write_bytes(b"do not overwrite")
        rec = main.Recorder(FakeAudio())
        rec.start(blocked, 0)
        result = self.wait_event(rec, "finished")
        rec.thread.join(3)
        self.assertTrue(result.error)
        self.assertIsNone(result.path)
        self.assertFalse(rec.thread.is_alive())
        self.assertEqual(blocked.read_bytes(), b"do not overwrite")


if __name__ == "__main__":
    unittest.main()
