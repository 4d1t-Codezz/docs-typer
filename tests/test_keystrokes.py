import sys
import threading
import unittest

from docstyper.keystrokes import ALL_ACTIONS, Typer, build_ops
from docstyper.model import NOFMT, SOFT_BREAK, Paragraph, doc_from_plain


def doc():
    return [
        Paragraph(runs=[("Head", NOFMT)], heading=2),
        Paragraph(runs=[("Bold ", frozenset("b")), ("plain" + SOFT_BREAK + "x", NOFMT)], align="justify"),
        Paragraph(runs=[("item", NOFMT)], list="bullet", level=1),
        Paragraph(runs=[("next", NOFMT)]),
    ]


class BuildOpsTests(unittest.TestCase):
    def test_formatted_plan(self):
        ops = build_ops(doc(), True)
        self.assertEqual(ops[:6], [("k", "heading2"), ("c", "H"), ("c", "e"), ("c", "a"), ("c", "d"), ("enter",)])
        self.assertIn(("k", "align_justify"), ops)
        self.assertIn(("soft",), ops)
        i = ops.index(("k", "bullet"))
        self.assertEqual(ops[i + 1], ("indent",))
        # Bold is toggled on and back off, list toggled off for the last paragraph.
        self.assertEqual(ops.count(("k", "bold")), 2)
        self.assertEqual(ops.count(("k", "bullet")), 2)

    def test_plain_plan(self):
        ops = build_ops(doc(), False)
        self.assertTrue(all(op[0] in ("c", "enter") for op in ops))
        text = "".join(op[1] if op[0] == "c" else "\n" for op in ops)
        self.assertEqual(text, "Head\nBold plain\nx\nitem\nnext")

    def test_every_action_is_known(self):
        for op in build_ops(doc(), True):
            if op[0] == "k":
                self.assertIn(op[1], ALL_ACTIONS)


class FakeBackend:
    def __init__(self):
        self.log = []

    def foreground(self):
        return 42

    def type_char(self, ch):
        self.log.append(ch)

    def press_enter(self, shift=False):
        self.log.append("<S-Enter>" if shift else "<Enter>")

    def press_tab(self):
        self.log.append("<Tab>")

    def shortcut(self, action):
        self.log.append(f"<{action}>")


class TyperTests(unittest.TestCase):
    def test_plays_everything_in_order(self):
        b = FakeBackend()
        ops = build_ops(doc_from_plain("hi\nyo"), False)
        t = Typer(b, ops, 0, 42, lambda: 100000, False)
        t._run()
        self.assertEqual(b.log, ["h", "i", "<Enter>", "y", "o"])
        self.assertEqual(t.typed, 5)

    def test_stops_when_focus_moves(self):
        b = FakeBackend()
        t = Typer(b, build_ops(doc_from_plain("abc"), False), 0, 7, lambda: 100000, False)
        t._run()
        self.assertEqual(b.log, [])
        self.assertEqual(t.stop_reason, "another app came to the front")


@unittest.skipUnless(sys.platform == "win32", "Windows backend")
class WindowsBackendTests(unittest.TestCase):
    def test_shortcuts_cover_all_actions(self):
        from docstyper.platforms import windows
        self.assertEqual(ALL_ACTIONS - set(windows.SHORTCUTS), set())
        self.assertEqual(windows.SHORTCUTS["bold"], (("ctrl",), 0x42))
        self.assertEqual(windows.SHORTCUTS["heading3"], (("ctrl", "alt"), 0x33))


@unittest.skipUnless(sys.platform == "darwin", "macOS backend")
class MacBackendTests(unittest.TestCase):
    def test_shortcuts_cover_all_actions(self):
        from docstyper.platforms import macos
        self.assertEqual(ALL_ACTIONS - set(macos.SHORTCUTS), set())
        self.assertEqual(macos.SHORTCUTS["bold"], (("cmd",), 11))
        self.assertEqual(macos.SHORTCUTS["heading3"], (("cmd", "option"), 20))
        self.assertEqual(macos.SHORTCUTS["strike"], (("cmd", "shift"), 7))

    def test_system_calls_resolve(self):
        # Loading the module binds every Quartz/CoreFoundation/objc function it uses.
        from docstyper.platforms import macos
        self.assertIsInstance(macos.frontmost_pid(), int)
        b = macos.Backend()
        html = b.clipboard_html()
        self.assertTrue(html is None or isinstance(html, str))


if __name__ == "__main__":
    unittest.main()
