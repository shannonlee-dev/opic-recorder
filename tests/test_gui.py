"""Windows-only Tk lifecycle tests. Microphone input is simulated."""

import gc
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_recorder import FakeAudio

import main


@unittest.skipUnless(sys.platform == "win32", "Windows Tk / winsound required")
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy)
        self.errors = []
        self.patches = [
            patch.object(main, "microphone_access_issue", return_value=None, create=True),
            patch.object(main, "settings_file", return_value=folder / "settings.json"),
            patch.object(main, "desktop_folder", return_value=folder),
            patch(
                "tkinter.messagebox.showerror", side_effect=lambda *a, **k: self.errors.append(a)
            ),
            patch("tkinter.messagebox.showwarning"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = main.RecorderApp(self.root, FakeAudio())
        self.wait_for(lambda: self.app.state == "idle")

    def destroy(self):
        if hasattr(self, "app"):
            self.app.recorder.stop()
            if self.app.recorder.thread:
                self.app.recorder.thread.join(4)
        try:
            self.app.shutdown()
        except Exception:
            pass
        # Collect Tk cycles on the owning thread before another worker starts.
        del self.app
        del self.root
        gc.collect()

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail("GUI did not reach expected state")

    def test_blocked_desktop_permission_prevents_recording_and_explains_setting(self):
        with patch.object(
            main, "microphone_access_issue", return_value="데스크톱 앱 마이크 접근 차단"
        ):
            self.app.start()
        self.assertEqual(self.app.state, "idle")
        self.assertIsNone(self.app.recorder.thread)
        self.assertTrue(self.errors)
        self.assertIn("데스크톱", self.errors[0][1])

    def test_resizing_window_expands_controls_in_both_directions(self):
        self.root.deiconify()
        self.root.update()
        before = (self.app.start_button.winfo_width(), self.app.start_button.winfo_height())
        self.root.geometry(f"{self.root.winfo_width() + 240}x{self.root.winfo_height() + 180}")
        self.root.update()
        self.assertGreater(self.app.start_button.winfo_width(), before[0])
        self.assertGreater(self.app.start_button.winfo_height(), before[1])
        self.assertTrue(all(self.root.resizable()))

    def test_start_stop_buttons_and_playback_enable_after_save(self):
        self.assertTrue(self.app.stop_button.instate(["disabled"]))
        self.app.start_button.invoke()
        self.assertTrue(self.app.start_button.instate(["disabled"]))
        self.wait_for(lambda: self.app.state == "recording")
        self.assertEqual(self.app.rec_text.get(), "● REC")
        self.app.stop_button.invoke()
        self.wait_for(lambda: self.app.state == "idle")
        self.assertEqual(self.app.status.get(), "저장 완료")
        self.assertTrue(self.app.last_file.exists())
        self.assertTrue(self.app.play_button.instate(["!disabled"]))
        self.assertFalse(self.errors)

    def test_cancel_close_keeps_recording_and_save_close_preserves_file(self):
        self.app.start()
        self.wait_for(lambda: self.app.state == "recording")
        with patch("tkinter.messagebox.askyesnocancel", return_value=None):
            self.app.on_close()
        self.assertEqual(self.app.state, "recording")
        with patch("tkinter.messagebox.askyesnocancel", return_value=True):
            self.app.on_close()
        self.wait_for(lambda: self.app.state == "idle")
        self.assertTrue(self.app.last_file.exists())

    def test_discard_close_removes_only_current_recording(self):
        self.app.start()
        self.wait_for(lambda: self.app.state == "recording")
        self.app.stop()
        self.wait_for(lambda: self.app.state == "idle")
        previous = self.app.last_file
        self.app.start()
        self.wait_for(lambda: self.app.state == "recording")
        with patch("tkinter.messagebox.askyesnocancel", return_value=False):
            self.app.on_close()
        self.wait_for(lambda: self.app.state == "idle")
        self.assertEqual(list(Path(self.temp.name).rglob("*.wav")), [previous])


if __name__ == "__main__":
    unittest.main()
