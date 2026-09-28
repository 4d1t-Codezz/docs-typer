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


class Typer:
    """Plays ops into the front app on a background thread until done, stopped, or focus moves."""

    def __init__(self, backend, ops, start, target, get_wpm, vary):
        self.backend, self.ops, self.pos = backend, ops, start
        self.target, self.get_wpm, self.vary = target, get_wpm, vary
        self.cancel = threading.Event()
        self.stop_reason = None
        self.started = None
        self.typed = 0
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

    def _delay(self, op):
        base = 60.0 / (max(self.get_wpm(), 1) * 5)  # 5 characters per word
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

    def _run(self):
        b = self.backend
        self.started = time.perf_counter()
        while self.pos < len(self.ops):
            if self.cancel.is_set():
                return
            if b.foreground() != self.target:
                self.stop_reason = "another app came to the front"
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
                self.typed += 1
                self.recent.append(time.perf_counter())
            self.pos += 1
            # Sleep in small slices so a stop takes effect right away.
            end = time.perf_counter() + self._delay(op)
            while not self.cancel.is_set():
                left = end - time.perf_counter()
                if left <= 0:
                    break
                time.sleep(min(left, 0.05))
