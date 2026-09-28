"""Turning a document into a platform-neutral list of keystroke operations.

Ops are the same on Windows and macOS. Formatting is recorded as named Google Docs
actions ("bold", "heading2", "bullet", ...); each platform backend maps those
names to its own keyboard shortcuts.
"""

import collections
import random
import threading
import time

from .model import SOFT_BREAK

FMT_ACTIONS = {"b": "bold", "i": "italic", "u": "underline", "s": "strike", "sup": "superscript",
               "sub": "subscript"}
LIST_ACTIONS = {"bullet": "bullet", "numbered": "numbered"}
ALIGN_ACTIONS = {"left": "align_left", "center": "align_center", "right": "align_right",
                 "justify": "align_justify"}
ALL_ACTIONS = (set(FMT_ACTIONS.values()) | set(LIST_ACTIONS.values()) | set(ALIGN_ACTIONS.values())
               | {f"heading{n}" for n in range(7)} | {"outdent"})

TEXT_OPS = ("c", "enter", "soft", "tab")  # ops that correspond to a character of the text


def build_ops(paras, keep_formatting):
    """Ops: ('c', char) | ('enter',) | ('soft',) | ('tab',) | ('indent',) | ('k', action)."""
    ops = []

    def chars(text):
        for ch in text:
            if ch == SOFT_BREAK:
                ops.append(("soft",) if keep_formatting else ("enter",))
            elif ch == "\t":
                ops.append(("tab",))
            elif ch == "\n":
                ops.append(("enter",))
            else:
                ops.append(("c", ch))

    if not keep_formatting:
        for i, p in enumerate(paras):
            if i:
                ops.append(("enter",))
            chars(p.text)
        return ops

    fmt, heading, lst, level, align = set(), 0, None, 0, "left"

    def key(action):
        ops.append(("k", action))

    def set_fmt(target):
        nonlocal fmt
        for k in ("sup", "sub", "b", "i", "u", "s"):  # turn things off first
            if k in fmt and k not in target:
                key(FMT_ACTIONS[k])
        for k in ("b", "i", "u", "s", "sup", "sub"):
            if k in target and k not in fmt:
                key(FMT_ACTIONS[k])
        fmt = set(target)

    for i, p in enumerate(paras):
        if i:
            set_fmt(set())
            ops.append(("enter",))
            heading = 0  # Enter after a heading gives Normal text in Google Docs
        if p.heading != heading:
            key(f"heading{p.heading}")
            heading = p.heading
        if p.list != lst:
            key(LIST_ACTIONS[p.list or lst])  # toggles on, switches type, or toggles off
            lst, level = p.list, 0
        if lst:
            while level < p.level:
                ops.append(("indent",)); level += 1  # Tab at the start of a list item
            while level > p.level:
                key("outdent"); level -= 1
        if p.align != align:
            key(ALIGN_ACTIONS[p.align])
            align = p.align
        for text, f in p.runs:
            if text:
                set_fmt(f)
                chars(text)
    set_fmt(set())
    return ops


def is_glyph(op):
    return op[0] != "k"


def is_word_char(op):
    return op[0] == "c" and (op[1].isalnum() or op[1] in "'’-")


class Typer:
    """Plays ops into the front app on a background thread until done, stopped, or focus moves."""

    RETYPE_CHANCE = 0.04  # per word that can be retyped, so roughly one every 30 to 40 words

    def __init__(self, backend, ops, start, target, get_wpm, vary, retype=False):
        self.backend, self.ops, self.pos = backend, ops, start
        self.target, self.get_wpm, self.vary, self.retype = target, get_wpm, vary, retype
        self.cancel = threading.Event()
        self.stop_reason = None
        self.started = None
        self.typed = 0
        self.furthest = start  # pos only goes back while retyping a word; count those keys once
        self.retyped_at = None
        self.recent = collections.deque()  # timestamps of recent characters, for live speed
        self.thread = threading.Thread(target=self._run, daemon=True)

    def live_wpm(self):
        now = time.perf_counter()
        while self.recent and now - self.recent[0] > 6:
            self.recent.popleft()
        if len(self.recent) < 4:
            return None
        span = max(now - self.recent[0], 1.0)
        return len(self.recent) / 5 / span * 60

    def _base(self):
        return 60.0 / (max(self.get_wpm(), 1) * 5)  # 5 characters per word

    def _delay(self, op):
        base = self._base()
        if op[0] == "k":
            return 0.06
        if op[0] in ("enter", "soft"):
            base *= 3
        if not self.vary:
            return base
        d = base * random.lognormvariate(0, 0.3)
        ch = op[1] if op[0] == "c" else ""
        if ch in ".!?":
            d += base * random.uniform(2, 5)
        elif ch in ",;:":
            d += base * random.uniform(0.5, 2)
        elif ch == " " and random.random() < 0.02:
            d += random.uniform(0.3, 1.0)  # brief pause between words now and then
        return d

    def _sleep(self, seconds):
        """Sleeps in small slices so a stop takes effect right away. False if stopped."""
        end = time.perf_counter() + seconds
        while not self.cancel.is_set():
            left = end - time.perf_counter()
            if left <= 0:
                return True
            time.sleep(min(left, 0.05))
        return False

    def _can_go_on(self):
        if self.cancel.is_set():
            return False
        if self.backend.foreground() != self.target:
            self.stop_reason = "another app came to the front"
            return False
        return True

    def _word_to_retype(self):
        """Length of the word that ends at pos, if it's a good one to delete and type again."""
        if self.pos == self.retyped_at or (self.pos < len(self.ops) and is_word_char(self.ops[self.pos])):
            return 0
        start = self.pos
        while start > 0 and is_word_char(self.ops[start - 1]):
            start -= 1
        # Only right after a space with no formatting shortcut in between, so the word comes back in
        # the same formatting (Google Docs formats new text like the character before it).
        if self.pos - start < 3 or start == 0 or self.ops[start - 1] != ("c", " "):
            return 0
        return self.pos - start

    def _delete_word(self, n):
        """Backspaces over the last n characters, moving pos back so the main loop types them again."""
        self.retyped_at = self.pos
        if not self._sleep(random.uniform(0.25, 0.7)):  # a beat, as if noticing something
            return False
        for _ in range(n):
            if not self._can_go_on():
                return False
            self.backend.press_backspace()
            self.pos -= 1
            if not self._sleep(self._base() * random.uniform(0.4, 0.8)):
                return False
        return self._sleep(random.uniform(0.2, 0.5))

    def _run(self):
        b = self.backend
        self.started = time.perf_counter()
        while self.pos < len(self.ops):
            if not self._can_go_on():
                return
            op = self.ops[self.pos]
            kind = op[0]
            if kind == "c":
                b.type_char(op[1])
            elif kind == "enter":
                b.press_enter()
            elif kind == "soft":
                b.press_enter(shift=True)
            elif kind in ("tab", "indent"):
                b.press_tab()
            else:
                time.sleep(0.03)
                b.shortcut(op[1])
            if kind in TEXT_OPS:
                if self.pos >= self.furthest:
                    self.typed += 1
                self.recent.append(time.perf_counter())
            self.pos += 1
            self.furthest = max(self.furthest, self.pos)
            n = self._word_to_retype() if self.retype else 0
            if n and random.random() < self.RETYPE_CHANCE and not self._delete_word(n):
                return
            if not self._sleep(self._delay(op)):
                return
