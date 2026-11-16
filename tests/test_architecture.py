"""Protect the headless recording boundary and legacy entry point imports."""

import subprocess
import sys
import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_core_imports_without_gui_windows_or_audio_driver(self):
        code = """
import importlib.abc
import sys

class BlockDesktopImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'tkinter', 'winsound', 'winreg', 'sounddevice'}:
            raise AssertionError('Core imported desktop dependency: ' + fullname)
        if fullname in {'opic_recorder.windows', 'opic_recorder.ui', 'opic_recorder.app'}:
            raise AssertionError('Core imported application layer: ' + fullname)

sys.meta_path.insert(0, BlockDesktopImports())
from opic_recorder import Recorder, RecordingResult
from opic_recorder import devices, settings, wav
assert Recorder.__module__ == 'opic_recorder.recording'
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_recorder_import_is_same_public_class(self):
        import main
        from opic_recorder import Recorder, RecordingResult

        self.assertIs(main.Recorder, Recorder)
        self.assertIs(main.RecordingResult, RecordingResult)


if __name__ == "__main__":
    unittest.main()
