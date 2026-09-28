import random
import sys
import threading
import unittest

from docstyper.keystrokes import ALL_ACTIONS, Typer, build_ops, confused_with, misspell
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

    def press_backspace(self):
        self.log.append("<BS>")

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

    def retyping_typer(self, b, ops):
        t = Typer(b, ops, 0, 42, lambda: 100000, False, retype=True)
        t.RETYPE_CHANCE = 1.0  # retype every word that qualifies
        t._sleep = lambda seconds: True
        return t

    def test_retypes_words(self):
        b = FakeBackend()
        t = self.retyping_typer(b, build_ops(doc_from_plain("hi there, world"), False))
        t._run()
        # "hi" is too short and starts the text; the others are deleted and typed again once each.
        self.assertEqual("".join(b.log), "hi there<BS><BS><BS><BS><BS>there, world"
                                         "<BS><BS><BS><BS><BS>world")
        self.assertEqual(t.typed, len("hi there, world"))
        self.assertEqual(t.pos, len(t.ops))

    def test_never_retypes_across_formatting(self):
        b = FakeBackend()
        paras = [Paragraph(runs=[("plain ", NOFMT), ("bold", frozenset("b"))]),
                 Paragraph(runs=[("next", NOFMT)])]
        t = self.retyping_typer(b, build_ops(paras, True))
        t._run()
        # "bold" follows a bold toggle and "next" follows Enter, so neither is safe to retype.
        self.assertNotIn("<BS>", b.log)

    def test_stop_while_deleting_leaves_pos_on_the_text(self):
        b = FakeBackend()
        t = self.retyping_typer(b, build_ops(doc_from_plain("a word"), False))
        real = b.press_backspace

        def press_then_stop():
            real()
            if b.log.count("<BS>") == 2:
                t.cancel.set()

        b.press_backspace = press_then_stop
        t._run()
        # "a word" minus two deleted letters is "a wo": Resume must continue from there.
        self.assertEqual(t.pos, len("a wo"))

    def test_stops_when_focus_moves(self):
        b = FakeBackend()
        t = Typer(b, build_ops(doc_from_plain("abc"), False), 0, 7, lambda: 100000, False)
        t._run()
        self.assertEqual(b.log, [])
        self.assertEqual(t.stop_reason, "another app came to the front")


class FakeDoc(FakeBackend):
    """Keeps the text a document would end up with, so every mistake must be fully fixed."""

    def __init__(self):
        super().__init__()
        self.text = ""

    def type_char(self, ch):
        super().type_char(ch)
        self.text += ch

    def press_enter(self, shift=False):
        super().press_enter(shift)
        self.text += "\n"

    def press_backspace(self):
        super().press_backspace()
        self.text = self.text[:-1]


TEXT = "Their dog ran to the park, and its owner was happier than ever.\nYour turn to write something longer."


class MistakeTests(unittest.TestCase):
    def typer(self, b, ops, start=0, cleanup=0):
        t = Typer(b, ops, start, 42, lambda: 100000, False, mistakes=True, cleanup=cleanup)
        t.TYPO_CHANCE = t.GRAMMAR_CHANCE = 1.0
        t._sleep = lambda seconds: True
        return t

    def test_mistakes_get_fixed(self):
        for seed in range(40):
            random.seed(seed)
            b = FakeDoc()
            t = self.typer(b, build_ops(doc_from_plain(TEXT), False))
            t._run()
            self.assertEqual(b.text, TEXT, f"seed {seed}")
            self.assertIn("<BS>", b.log)
            self.assertEqual(t.typed, len(TEXT))

    def test_grammar_mistake(self):
        random.seed(0)
        b = FakeDoc()
        t = self.typer(b, build_ops(doc_from_plain("I like their car"), False))
        t.TYPO_CHANCE = 0.0
        t._run()
        self.assertTrue("".join(b.log).startswith("I like there<BS>") or
                        "".join(b.log).startswith("I like they're<BS>"), b.log)
        self.assertEqual(b.text, "I like their car")

    def test_formatted_word_is_never_deleted_whole(self):
        # "their" is bold right after a plain space, so swapping the whole word would lose the bold.
        paras = [Paragraph(runs=[("see ", NOFMT), ("their", frozenset("b"))])]
        for seed in range(20):
            random.seed(seed)
            b = FakeDoc()
            t = self.typer(b, build_ops(paras, True))
            t._run()
            self.assertNotIn("there", b.text)
            log = "".join(b.log)
            self.assertNotIn("<bold>there", log)
            self.assertNotIn("<bold>they're", log)
            self.assertEqual(b.text, "see their")

    def test_resume_cleans_up_a_stopped_mistake(self):
        random.seed(3)
        ops = build_ops(doc_from_plain("Your answer was better than mine"), False)
        b = FakeDoc()
        t = self.typer(b, ops)
        real = b.type_char

        def type_then_stop(ch):
            real(ch)
            if t.stray:  # stop in the middle of a mistake
                t.cancel.set()

        b.type_char = type_then_stop
        t._run()
        self.assertGreater(t.stray, 0)
        b.type_char = real
        t2 = self.typer(b, ops, start=t.pos, cleanup=t.stray)
        t2._run()
        self.assertEqual(b.text, "Your answer was better than mine")

    def test_helpers(self):
        random.seed(0)
        for _ in range(50):
            wrong = misspell("there")
            self.assertTrue(wrong and wrong != "there"[:len(wrong)])
        self.assertIsNone(misspell("9am"))
        self.assertEqual(confused_with("Its")[0], "I")
        self.assertIn(confused_with("it’s"), ("its",))
        self.assertIsNone(confused_with("dog"))


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
