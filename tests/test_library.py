import os
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speaking_recorder.library import scan_recordings

class LibraryTests(unittest.TestCase):
    def test_nested_wav_metadata_and_invalid_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / '2026-11-16'
            nested.mkdir()
            path = nested / '연습.WAV'
            with wave.open(str(path), 'wb') as w:
                w.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                w.writeframes(b'\0\0' * 8000)
            (root / 'broken.wav').write_bytes(b'broken')
            records = scan_recordings(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].path, path)
            self.assertEqual(records[0].seconds, 1)
            self.assertEqual(records[0].size, path.stat().st_size)
            self.assertEqual(scan_recordings(root / 'missing'), [])

    def test_latest_first_uses_modification_time_not_filename(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, modified in [('z-old.wav', 1700000000), ('a-new.wav', 1700000020)]:
                with wave.open(str(root / name), 'wb') as audio:
                    audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(b'\0\0' * 80)
                os.utime(root / name, (modified, modified))
            self.assertEqual([r.path.name for r in scan_recordings(root)],
                             ['a-new.wav', 'z-old.wav'])
