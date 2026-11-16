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

from speaking_recorder.ui import app as ui_app


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
            patch.object(ui_app, "microphone_access_issue", return_value=None, create=True),
            patch.object(ui_app, "settings_file", return_value=folder / "settings.json"),
            patch.object(ui_app, "desktop_folder", return_value=folder),
            patch(
                "tkinter.messagebox.showerror", side_effect=lambda *a, **k: self.errors.append(a)
            ),
            patch("tkinter.messagebox.showwarning"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = ui_app.RecorderApp(self.root, FakeAudio())
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

    def test_library_refresh_search_select_and_recording_guard(self):
        self.app.start()
        self.wait_for(lambda: self.app.state == "recording")
        self.app.stop()
        self.wait_for(lambda: self.app.state == "idle")
        library = self.app.view.library
        self.wait_for(lambda: len(library.records) == 1)
        path = library.records[0].path
        library.select(path)
        with patch("speaking_recorder.ui.library.play_file") as play:
            library.play()
            play.assert_called_once_with(path)
            play.reset_mock()
            self.app.start()
            library.play()
            play.assert_not_called()
        self.app.stop()
        self.wait_for(lambda: self.app.state == "idle")
        library.query.set("no matching recording")
        self.assertEqual(library.filtered(), [])
        library.query.set("")
        self.assertTrue(library.filtered())

    def test_library_cards_leave_player_visible_and_filter_by_date(self):
        from speaking_recorder.library import Recording

        library = self.app.view.library
        library.records = [Recording(Path(f'track-{i}.wav'), f'2026-11-{16-i:02}', 60, 1024)
                           for i in range(7)]
        library.render()
        self.root.deiconify()
        self.root.update()
        button_bottom = library.play_button.winfo_rooty() + library.play_button.winfo_height()
        self.assertLessEqual(button_bottom, self.root.winfo_rooty() + self.root.winfo_height())
        library.turn(1)
        self.assertEqual(library.page, 1)
        library.date.set('2026-11-16')
        self.assertEqual(len(library.filtered()), 1)
        self.assertEqual(library.page, 0)
        self.root.update()
        card = library.cards.winfo_children()[0]
        with patch('speaking_recorder.ui.library.play_file') as play:
            with patch.object(Path, 'is_file', return_value=True):
                card.event_generate('<Button-1>')
                card.event_generate('<ButtonRelease-1>')
                card.event_generate('<Button-1>')
                self.root.update()
            play.assert_called_once_with(Path('track-0.wav'))

    def test_delete_confirmation_cancel_success_and_failure(self):
        self.app.start()
        self.wait_for(lambda: self.app.state == 'recording')
        self.app.stop()
        self.wait_for(lambda: self.app.state == 'idle')
        library = self.app.view.library
        self.wait_for(lambda: len(library.records) == 1)
        path = library.records[0].path
        library.select(path)
        with patch('tkinter.messagebox.askyesno', return_value=False) as confirm:
            with patch('speaking_recorder.ui.library.recycle_file') as recycle:
                library.delete_buttons[0].invoke()
                confirm.assert_called_once()
                recycle.assert_not_called()
                self.assertTrue(path.exists())
        with patch('tkinter.messagebox.askyesno', return_value=True):
            with patch('speaking_recorder.ui.library.recycle_file', side_effect=OSError('locked')):
                library.delete(path)
                self.assertEqual(library.selected, path)
                self.assertTrue(path.exists())
                self.assertTrue(self.errors)
            with patch('speaking_recorder.ui.library.recycle_file', side_effect=lambda p: p.unlink()):
                library.delete(path)
        self.assertIsNone(library.selected)
        self.assertIsNone(self.app.last_file)
        self.assertFalse(library.records)
        self.assertTrue(self.app.view.play_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno') as confirm:
            library.set_idle(False)
            library.delete(path)
            confirm.assert_not_called()

    def test_blocked_desktop_permission_prevents_recording_and_explains_setting(self):
        with patch.object(
            ui_app, "microphone_access_issue", return_value="데스크톱 앱 마이크 접근 차단"
        ):
            self.app.start()
        self.assertEqual(self.app.state, "idle")
        self.assertIsNone(self.app.recorder.thread)
        self.assertTrue(self.errors)
        self.assertIn("데스크톱", self.errors[0][1])

    def test_resizing_window_expands_controls_in_both_directions(self):
        self.root.deiconify()
        self.root.update()
        before = (
            self.app.view.start_button.winfo_width(),
            self.app.view.start_button.winfo_height(),
        )
        self.root.geometry(f"{self.root.winfo_width() + 240}x{self.root.winfo_height() + 180}")
        self.root.update()
        self.assertGreater(self.app.view.start_button.winfo_width(), before[0])
        self.assertEqual(self.app.view.start_button.winfo_height(), before[1])
        self.assertTrue(all(self.root.resizable()))

    def test_start_stop_buttons_and_playback_enable_after_save(self):
        self.assertTrue(self.app.view.stop_button.instate(["disabled"]))
        self.app.view.start_button.invoke()
        self.assertTrue(self.app.view.start_button.instate(["disabled"]))
        self.wait_for(lambda: self.app.state == "recording")
        self.assertEqual(self.app.view.rec_text.get(), "● REC")
        self.app.view.stop_button.invoke()
        self.wait_for(lambda: self.app.state == "idle")
        self.assertEqual(self.app.view.status.get(), "저장 완료")
        self.assertTrue(self.app.last_file.exists())
        self.assertTrue(self.app.view.play_button.instate(["!disabled"]))
        self.assertFalse(self.errors)

    def test_keyboard_record_save_and_repeated_start(self):
        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        self.root.event_generate("<Control-KeyPress-r>")
        self.wait_for(lambda: self.app.state == "recording")
        worker = self.app.recorder.thread
        self.root.event_generate("<Control-KeyPress-r>")
        self.root.update()
        self.assertIs(self.app.recorder.thread, worker)
        self.root.event_generate("<Control-KeyPress-s>")
        self.wait_for(lambda: self.app.state == "idle")
        self.assertTrue(self.app.last_file.exists())
        self.assertFalse(self.errors)

    def test_shortcuts_respect_disabled_controls_and_modal_dialogs(self):
        import tkinter as tk

        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        with patch("winsound.PlaySound") as playback:
            self.root.event_generate("<Control-KeyPress-p>")
            self.root.update()
            playback.assert_not_called()
        self.app.start()
        self.wait_for(lambda: self.app.state == "recording")
        with patch.object(self.app, "refresh_devices") as refresh:
            self.app.view.refresh_button.configure(command=refresh)
            self.root.event_generate("<F5>")
            self.root.update()
            refresh.assert_not_called()
        dialog = tk.Toplevel(self.root)
        dialog.grab_set()
        try:
            self.root.event_generate("<Control-KeyPress-s>")
            self.root.update()
            self.assertEqual(self.app.state, "recording")
        finally:
            dialog.grab_release()
            dialog.destroy()
        self.app.stop()
        self.wait_for(lambda: self.app.state == "idle")

    def test_keyboard_help_and_playback_stop(self):
        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        with patch("tkinter.messagebox.showinfo") as help_dialog:
            self.root.event_generate("<F1>")
            self.root.update()
            help_dialog.assert_called_once()
            self.assertIn("Ctrl+R", help_dialog.call_args.args[1])
        with patch("winsound.PlaySound") as playback:
            self.root.event_generate("<Escape>")
            self.root.update()
            playback.assert_called_once_with(None, 0)

    def test_folder_refresh_playback_and_text_entry_keys(self):
        import tkinter as tk

        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        for key, button in (
            ("<Control-KeyPress-o>", self.app.view.open_folder_button),
            ("<F5>", self.app.view.refresh_button),
            ("<Control-KeyPress-p>", self.app.view.play_button),
        ):
            with patch.object(self.app, "open_folder") as action:
                button.configure(command=action, state="normal")
                self.root.event_generate(key)
                self.root.update()
                action.assert_called_once_with()
        entry = tk.Entry(self.root)
        entry.pack()
        # The app fixes its initial geometry; make room for this extra test input.
        self.root.geometry(
            f"{self.root.winfo_width()}x{self.root.winfo_height() + entry.winfo_reqheight()}"
        )
        self.root.update()
        entry.focus_force()
        self.root.update()
        self.assertTrue(entry.winfo_ismapped())
        self.assertIs(self.root.focus_get(), entry)
        for key in ("r", "space", "s"):
            entry.event_generate(f"<KeyPress-{key}>", state=0)
        self.root.update()
        self.assertEqual(entry.get(), "r s")
        self.assertEqual(self.app.state, "idle")
        self.assertIsNone(self.app.recorder.thread)

    def test_korean_ime_virtual_key_and_altgr_guard(self):
        from types import SimpleNamespace

        with patch.object(self.app, "start") as start:
            self.app.view.start_button.configure(command=start)
            self.app.on_control_shortcut(SimpleNamespace(keycode=82, keysym="Hangul", state=4))
            start.assert_called_once_with()
            self.app.on_control_shortcut(SimpleNamespace(keycode=82, keysym="r", state=0x20004))
            start.assert_called_once_with()

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
