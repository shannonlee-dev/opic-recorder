"""Windows-only Tk lifecycle tests. Microphone input is simulated."""

import gc
import struct
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

    def test_volume_slider_sets_live_playback_volume(self):
        from speaking_recorder.windows import set_playback_volume

        library = self.app.view.library
        self.root.deiconify()
        self.root.update()
        with patch("speaking_recorder.ui.library.set_playback_volume") as volume:
            library.volume_scale.set(35)
            self.root.update()
            volume.assert_called_with(0.35)
        self.assertEqual(library.volume_text.cget("text"), "35%")
        set_playback_volume(0.35)  # The real Windows call must succeed.
        set_playback_volume(1.0)

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

    def test_keyboard_record_save_with_numlock(self):
        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        # Windows Tk reports NumLock as Mod1 (0x8), not Alt.
        self.root.event_generate("<Control-KeyPress-r>", state=0xC)
        self.wait_for(lambda: self.app.state == "recording")
        self.root.event_generate("<Control-KeyPress-s>", state=0xC)
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



@unittest.skipUnless(sys.platform == "win32", "Windows Tk required")
class ModeTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close, self.root)
        for item in (
            patch.object(ui_app, "microphone_access_issue", return_value=None, create=True),
            patch.object(ui_app, "settings_file", side_effect=lambda name: self.folder / name),
            patch.object(ui_app, "desktop_folder", return_value=self.folder),
            patch("tkinter.messagebox.showerror"),
            patch("tkinter.messagebox.showwarning"),
        ):
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def close(root):
        try:
            root.destroy()
        except Exception:
            pass

    def test_launcher_click_hands_over_chosen_mode_and_cleans_up(self):
        from speaking_recorder.modes import ENGLISH, SONG
        from speaking_recorder.ui.launcher import ModeLauncher

        chosen = []
        launcher = ModeLauncher(self.root, chosen.append)
        self.root.deiconify()
        for _ in range(5):
            self.root.update()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        middle_x = x + self.root.winfo_width() / 2
        middle_y = y + self.root.winfo_height() / 2
        self.assertLess(abs(middle_x - self.root.winfo_screenwidth() / 2), 80)
        self.assertLess(abs(middle_y - self.root.winfo_screenheight() / 2), 120)
        width = launcher.canvas.winfo_width()
        launcher.canvas.event_generate("<Motion>", x=width - 10, y=50)
        self.assertIs(launcher.hover, SONG)
        launcher.canvas.event_generate("<ButtonRelease-1>", x=width - 10, y=50)
        self.assertEqual(chosen, [SONG])
        self.assertIsNone(launcher.canvas)
        self.assertEqual(self.root.winfo_children(), [])
        launcher = ModeLauncher(self.root, chosen.append)
        self.root.update()
        self.root.focus_force()
        self.root.update()
        self.root.event_generate("<Key-1>")
        self.root.update()
        self.assertEqual(chosen, [SONG, ENGLISH])

    def test_song_mode_records_into_its_own_folder(self):
        from speaking_recorder.modes import ENGLISH, SONG

        english = ui_app.RecorderApp(self.root, FakeAudio(), ENGLISH)
        self.assertEqual(english.folder, self.folder / "Speaking_Recordings")
        self.assertEqual(english.config, self.folder / "settings.json")
        english.shutdown()
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close, self.root)
        song = ui_app.RecorderApp(self.root, FakeAudio(), SONG)
        self.assertEqual(song.folder, self.folder / "Song_Recordings")
        self.assertEqual(song.config, self.folder / "song-settings.json")
        self.assertIn("Song", self.root.title())
        deadline = time.monotonic() + 5
        while song.state != "idle" and time.monotonic() < deadline:
            self.root.update()
        song.start()
        while song.state != "recording" and time.monotonic() < deadline + 5:
            self.root.update()
        song.stop()
        while song.state != "idle" and time.monotonic() < deadline + 10:
            self.root.update()
        self.assertEqual(song.last_file.parents[1], self.folder / "Song_Recordings")
        song.shutdown()

    def test_song_mode_monitoring_toggles_alongside_recording(self):
        from speaking_recorder.modes import ENGLISH, SONG

        class MonitorAudio(FakeAudio):
            def query_devices(self, device=None, kind=None):
                info = dict(super().query_devices(0), max_output_channels=2)
                return [info] if device is None else info

            def RawStream(self, **kwargs):
                class Stream:
                    active = False

                    def start(self):
                        self.active = True

                    def stop(self):
                        self.active = False

                    def close(self):
                        pass

                self.duplex = Stream()
                return self.duplex

        english = ui_app.RecorderApp(self.root, MonitorAudio(), ENGLISH)
        self.assertFalse(hasattr(english.view, "monitor_button"))
        english.shutdown()
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close, self.root)
        audio = MonitorAudio()
        with patch.object(ui_app, "output_choices", return_value=([(0, "Headphones")], 0)):
            song = ui_app.RecorderApp(self.root, audio, SONG)
            deadline = time.monotonic() + 5
            while song.state != "idle" and time.monotonic() < deadline:
                self.root.update()
        self.assertEqual(song.view.monitor_output.get(), "Headphones")
        song.toggle_monitor()
        self.assertTrue(song.monitor_on and audio.duplex.active)
        self.assertIn("ON", song.view.monitor_button.cget("text"))
        song.start()
        while song.state != "recording" and time.monotonic() < deadline + 5:
            self.root.update()
        song.stop()
        while song.state != "idle" and time.monotonic() < deadline + 10:
            self.root.update()
        self.assertTrue(song.last_file.exists())
        self.assertTrue(song.monitor_on, "recording must not stop monitoring")
        song.set_monitor_volume("40")
        self.assertEqual(song.monitor.gain, 0.4)
        audio.duplex.active = False  # device unplugged
        self.root.update()
        time.sleep(0.1)
        self.root.update()
        self.assertFalse(song.monitor_on)
        self.assertIn("중단", song.view.monitor_status.get())
        song.shutdown()

    def test_song_stage_disc_records_and_takes_play_on_tap(self):
        from speaking_recorder.modes import SONG

        song = ui_app.RecorderApp(self.root, FakeAudio(), SONG)
        self.root.deiconify()
        deadline = time.monotonic() + 5
        while song.state != "idle" and time.monotonic() < deadline:
            self.root.update()
        view = song.view
        self.assertIsNone(view.play_button)
        self.assertIsNone(view.folder_button)
        cx, cy, _ = view._geometry()
        view.canvas.event_generate("<ButtonRelease-1>", x=int(cx), y=int(cy))
        while song.state != "recording" and time.monotonic() < deadline + 5:
            self.root.update()
        self.assertEqual(song.state, "recording")
        self.root.focus_force()
        self.root.update()
        self.root.event_generate("<Control-KeyPress-s>")  # shortcut reaches the disc's stop
        while song.state != "idle" and time.monotonic() < deadline + 10:
            self.root.update()
        takes = view.library
        while not takes.records and time.monotonic() < deadline + 15:
            self.root.update()
        self.assertEqual(takes.records[0].path, song.last_file)
        self.assertEqual(takes.records[0].path.parents[1], self.folder / "Song_Recordings")
        row = takes.rows.winfo_children()[0]
        with patch("speaking_recorder.ui.song_view.play_file") as play:
            row.event_generate("<ButtonRelease-1>")
            self.root.update()
            play.assert_called_once_with(song.last_file)
        self.assertEqual(takes.playing, song.last_file)
        with patch("speaking_recorder.ui.song_view.stop_playback") as stop:
            takes.rows.winfo_children()[0].event_generate("<ButtonRelease-1>")
            self.root.update()
            stop.assert_called_once()
        self.assertIsNone(takes.playing)
        song.shutdown()

    def test_song_autotune_toggle_tunes_the_saved_take(self):
        from speaking_recorder.modes import SONG

        song = ui_app.RecorderApp(self.root, FakeAudio(), SONG)
        deadline = time.monotonic() + 5
        while song.state != "idle" and time.monotonic() < deadline:
            self.root.update()
        self.assertTrue(song.autotune_ready)
        self.assertIn("OFF", song.view.autotune_button.cget("text"))
        self.root.deiconify()
        self.root.focus_force()
        self.root.update()
        self.root.event_generate("<Control-KeyPress-t>")
        self.root.update()
        self.assertEqual(song.autotune_level, 1)
        self.assertEqual(song.view.autotune_button.cget("text"), "ON")
        self.root.event_generate("<Control-KeyPress-t>")
        self.root.update()
        self.assertEqual(song.autotune_level, 2)
        self.assertEqual(song.view.autotune_button.cget("text"), "MAX")
        self.assertEqual(song.monitor.autotune, 2)
        view = song.view
        self.assertEqual(view.key_box.get(), "자동")
        self.assertEqual(str(view.scale_box.cget("state")), "disabled")
        view.key_box.current(10)          # A
        view.key_box.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(song.autotune_key, (9, True))  # A Minor (scale defaults to Minor)
        view.scale_box.current(1)
        view.scale_box.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(song.autotune_key, (9, False))  # A Major
        self.assertEqual(song.monitor.key, (9, False))
        self.root.update()
        time.sleep(0.1)
        self.root.update()
        self.assertTrue(view.key_hint.get().startswith("A B C# D E F# G#"), repr(view.key_hint.get()))
        song.start()
        while song.state != "recording" and time.monotonic() < deadline + 5:
            self.root.update()
        song.stop()
        while song.state != "idle" and time.monotonic() < deadline + 15:
            self.root.update()
        take = song.last_file
        self.assertTrue((take.parent / ".raw" / take.name).exists(), "raw original kept")
        self.assertEqual(song.take_key, (9, False))
        self.assertTrue(take.exists())
        self.assertEqual(song.view.status.get(), "하드튠 적용 완료")
        song.toggle_autotune()
        self.assertEqual(song.autotune_level, 0)
        self.assertEqual(song.view.autotune_button.cget("text"), "OFF")
        song.shutdown()

    def test_muting_the_monitor_mid_take_keeps_the_native_capture_alive(self):
        from test_monitoring import FakeNative

        from speaking_recorder.modes import SONG

        song = ui_app.RecorderApp(self.root, FakeAudio(), SONG)
        deadline = time.monotonic() + 5
        while song.state != "idle" and time.monotonic() < deadline:
            self.root.update()
        native = FakeNative()
        native.captured = [struct.pack("<480h", *([1000, -1000] * 240))] * 40
        song.monitor.native = native
        song.outputs = [(0, "Headphones")]
        song.view.monitor_output["values"] = ["Headphones"]
        song.view.monitor_output.current(0)
        song.toggle_monitor()
        self.assertTrue(song.monitor.using_native)
        song.start()
        self.assertTrue(song.recording_via_monitor)
        while song.state != "recording" and time.monotonic() < deadline + 5:
            self.root.update()
        song.toggle_monitor()  # off during the take: mute only
        self.assertFalse(song.monitor_on)
        self.assertTrue(native.running)
        self.assertEqual(native.calls[-1], ("gain", 0.0))
        song.stop()
        while song.state != "idle" and time.monotonic() < deadline + 10:
            self.root.update()
        self.assertFalse(native.running)  # released after the take
        self.assertIs(song.recorder.audio, song.audio)
        self.assertTrue(song.last_file.exists())
        song.shutdown()

    def test_song_pitch_panel_names_the_sung_note(self):
        from test_monitoring import FakeNative

        from speaking_recorder.modes import SONG

        song = ui_app.RecorderApp(self.root, FakeAudio(), SONG)
        deadline = time.monotonic() + 5
        while song.state != "idle" and time.monotonic() < deadline:
            self.root.update()
        self.root.deiconify()
        view = song.view
        self.root.update()
        self.assertFalse(view.pitch_live)
        native = FakeNative()
        native.pitch = lambda: (198.0, 196.0, 0.95)  # G3, 18 cents sharp
        song.monitor.native = native
        song.outputs = [(0, "Headphones")]
        song.view.monitor_output["values"] = ["Headphones"]
        song.view.monitor_output.current(0)
        song.toggle_monitor()
        song.toggle_autotune()
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            self.root.update()
        self.assertTrue(view.pitch_live)
        self.assertEqual(view.pitch_now["label"], "1옥타브 솔")
        self.assertEqual(view.pitch_target["label"], "1옥타브 솔")
        texts = [view.pitch_canvas.itemcget(i, "text") for i in view.pitch_canvas.find_all()
                 if view.pitch_canvas.type(i) == "text"]
        self.assertIn("1옥타브 솔", texts)
        self.assertIn("+18센트  ·  조금 높아요", texts)
        self.assertIn("→ 하드튠: 1옥타브 솔", texts)
        self.assertIn("1옥타브 솔#", texts)  # black-key semitones are labelled too
        self.assertIn("1옥타브 라", texts)
        # The graph is its own column between the stage and the takes.
        self.assertLess(view.canvas.winfo_rootx(), view.pitch_canvas.winfo_rootx())
        self.assertLess(view.pitch_canvas.winfo_rootx(), view.library.frame.winfo_rootx())
        self.assertGreater(len(view.pitch_history), 3)
        song.toggle_monitor()
        self.root.update()
        time.sleep(0.1)
        self.root.update()
        self.assertFalse(view.pitch_live)
        song.shutdown()

if __name__ == "__main__":
    unittest.main()
