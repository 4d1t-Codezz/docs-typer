"""Builds the real window with a fake backend and runs every animation. Sends no input anywhere."""

import os
import tkinter as tk
import traceback
import unittest

from docstyper import theme as T
from docstyper.readers import read_html

try:
    _root = tk.Tk()
    _root.update_idletasks()  # Tk 9 on macOS crashes the next Tk() if a root dies with idle work pending
    _root.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


class FakeWatcher:
    def __init__(self, cb):
        pass

    def start(self):
        return True

    def stop(self):
        pass


class FakeBackend:
    name = "test"
    mod_label = "Ctrl"
    accel = "Control"
    ui_font = "Helvetica"
    title_font = "Georgia"
    mono_font = "Courier"
    InputWatcher = FakeWatcher

    def setup_process(self):
        pass

    def scale(self, root):
        return 1.0

    def style_window(self, root, bg, fg):
        pass

    def set_icon(self, root, assets):
        pass

    def foreground(self):
        return 1

    def is_own(self, token, root):
        return True  # so a countdown never starts typing

    def permission_problem(self):
        return None

    def open_permission_settings(self, which=None):
        pass

    def clipboard_html(self):
        return None

    def type_char(self, ch):
        raise AssertionError("the smoke test must never type")

    press_enter = press_tab = shortcut = type_char


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SmokeTest(unittest.TestCase):
    def test_every_state_and_animation(self):
        os.environ.setdefault("APPDATA", os.path.join(os.path.dirname(__file__), ".tmp"))
        from docstyper import ui
        ui.save_settings = lambda data: None  # don't touch the real settings file
        T.configure_fonts(FakeBackend())
        errors = []
        root = tk.Tk()
        root.report_callback_exception = lambda *a: errors.append("".join(traceback.format_exception(*a)))
        app = ui.App(root, backend=FakeBackend(), intro=True)

        def steps():
            app.show_doc(read_html("<h1>Title</h1><p><b>Bold</b> and <i>it</i></p><ul><li>one</li></ul>"))
            app.start_button._set_hover(True)
            app.speed._set(hovering=True)
            app.speed._wheel(type("E", (), {"delta": 120})())
            app.swatches._click(type("E", (), {"x": app.swatches._cx(1)})())
            app.countdown_pick._click(type("E", (), {"x": 5})())
            app.mascot.poke()
            app.mascot.greet()
            app.title.do_wave()
            app.shake(app.box)
            app.begin_countdown()  # 3s countdown; fake backend says our own window is in front
            root.after(3600, visual_typing)

        def visual_typing():
            # Drive the typing visuals directly (no Typer thread, nothing is typed).
            app.state = "typing"
            app.map_text()
            app.keystrip.show(True)
            app.progress.set_shimmer(True)
            app.cursor_glow(True)
            app.mascot.set_mode("typing")
            for i in range(1, len(app.ops), 3):
                app.feed_keys(i)
                app.show_typed(i)
            root.after(600, finish)

        def finish():
            app.state = "idle"
            app.keystrip.show(False)
            app.progress.set_shimmer(False)
            app.cursor_glow(False)
            app.overlay.show("done", stats="10 characters · 2 sec · 60 wpm average")
            app.mascot.set_mode("done")
            app.refresh()
            root.after(3800, root.destroy)

        root.after(4200, steps)  # after the intro finishes
        root.after(20000, root.destroy)  # safety net
        root.mainloop()
        T.set_accent(T.ACCENTS[0][1], notify=False)
        self.assertEqual(errors, [], "\n".join(errors))
        self.assertEqual(app.countdown_secs, 3)


if __name__ == "__main__":
    unittest.main()
