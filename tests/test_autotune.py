"""Hard Tune bridge: native DLL loads, files are tuned in place, originals are kept."""

import math
import struct
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from speaking_recorder import autotune
from speaking_recorder.library import scan_recordings

RATE = 48000


def write_tone(path, hz, seconds=1.5, amplitude=6000):
    frames = int(RATE * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(
            struct.pack("<h", int(amplitude * math.sin(2 * math.pi * hz * i / RATE)))
            for i in range(frames)
        ))
    return frames


def measure_hz(path, start=0.6, seconds=0.6):
    """Zero-crossing frequency of a pure tone (linear-interpolated crossings)."""
    with wave.open(str(path), "rb") as r:
        r.setpos(int(start * RATE))
        data = r.readframes(int(seconds * RATE))
    x = struct.unpack(f"<{len(data) // 2}h", data)
    crossings = [i + x[i] / (x[i] - x[i + 1]) for i in range(len(x) - 1) if x[i] <= 0 < x[i + 1]]
    return RATE * (len(crossings) - 1) / (crossings[-1] - crossings[0])


class NoteNameTests(unittest.TestCase):
    def test_korean_octave_names_and_tuning_advice(self):
        def hz(midi, cents=0):
            return 440 * 2 ** ((midi - 69 + cents / 100) / 12)

        g3 = autotune.describe_pitch(hz(55))
        self.assertEqual((g3["label"], g3["letter"], g3["advice"]), ("1옥타브 솔", "G3", "정확해요"))
        self.assertEqual(autotune.describe_pitch(hz(60))["label"], "2옥타브 도")   # middle C
        self.assertEqual(autotune.describe_pitch(hz(69))["label"], "2옥타브 라")   # A4
        self.assertEqual(autotune.describe_pitch(hz(72))["label"], "3옥타브 도")   # C5
        self.assertEqual(autotune.describe_pitch(hz(58))["label"], "1옥타브 라#")
        sharp = autotune.describe_pitch(hz(55, 18))
        self.assertEqual((sharp["cents"], sharp["advice"]), (18, "조금 높아요"))
        self.assertEqual(autotune.describe_pitch(hz(55, -40))["advice"], "낮아요")
        self.assertIsNone(autotune.describe_pitch(0))


@unittest.skipUnless(sys.platform == "win32", "native Windows DLL")
class AutoTuneTests(unittest.TestCase):
    def test_dll_loads_with_fixed_latency(self):
        self.assertTrue(autotune.available())
        tuner = autotune.AutoTune(RATE)
        self.assertEqual(tuner.latency, 144)  # live: 3.0 ms on attacks and consonants
        self.assertEqual(autotune.AutoTune(RATE, live=False).latency, 1024)  # files: cleaner
        self.assertEqual(len(tuner.process(bytes(960))), 960)
        tuner.close()

    def test_take_is_tuned_aligned_and_original_kept(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            take = folder / "2026-11-19" / "take.wav"
            take.parent.mkdir()
            frames = write_tone(take, 226.0)  # +46 cents above A3
            self.assertAlmostEqual(measure_hz(take), 226.0, delta=0.5)
            raw = autotune.apply_to_take(take)
            self.assertEqual(raw, take.parent / ".raw" / "take.wav")
            self.assertAlmostEqual(measure_hz(raw), 226.0, delta=0.5)  # original untouched
            tuned = measure_hz(take)
            self.assertLess(abs(1200 * math.log2(tuned / 220.0)), 10, tuned)
            with wave.open(str(take), "rb") as r:
                self.assertEqual(r.getnframes(), frames)  # same length: latency removed
            self.assertTrue(autotune.is_tuned(take))
            # MAX on a separate copy also lands exactly on a note.
            maxed = take.parent / "max.wav"
            write_tone(maxed, 226.0)
            autotune.apply_to_take(maxed, autotune.MAX)
            self.assertLess(abs(1200 * math.log2(measure_hz(maxed) / 220.0)), 10)
            # Beat key A major: C sung 20 cents sharp goes to C# (A minor would keep C).
            keyed = take.parent / "keyed.wav"
            write_tone(keyed, 440 * 2 ** ((60.2 - 69) / 12))
            autotune.apply_to_take(keyed, autotune.ON, (9, False))
            self.assertLess(abs(1200 * math.log2(measure_hz(keyed) / (440 * 2 ** ((61 - 69) / 12)))), 10)
            self.assertEqual(autotune.key_name((9, True)), "A Minor")
            self.assertEqual(autotune.notes_name(0), "C Major / A Minor")
            self.assertEqual(autotune.scale_notes((9, True)), "A B C D E F G  ·  C Major와 같은 음")
            self.assertEqual(autotune.scale_notes((7, False)), "G A B C D E F#  ·  E Minor와 같은 음")
            self.assertEqual(autotune.scale_notes((3, False)).split("  ")[0], "Eb F G Ab Bb C D")
            self.assertEqual(autotune.scale_notes((4, True)).split("  ")[0], "E F# G A B C D")
            self.assertEqual(sorted(r.path.name for r in scan_recordings(folder)),
                             ["keyed.wav", "max.wav", "take.wav"])  # .raw originals hidden

    def test_failed_tuning_leaves_the_take_untouched(self):
        with TemporaryDirectory() as temp:
            take = Path(temp) / "stereo.wav"
            with wave.open(str(take), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(bytes(400))
            before = take.read_bytes()
            with self.assertRaises(ValueError):
                autotune.apply_to_take(take)
            self.assertEqual(take.read_bytes(), before)
            self.assertFalse((Path(temp) / ".raw").exists())
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["stereo.wav"])


if __name__ == "__main__":
    unittest.main()
