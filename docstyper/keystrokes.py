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

# For "make mistakes": keys next to each other, and words people often mix up.
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
NEIGHBORS = {}
for _r, _row in enumerate(_ROWS):
    for _c, _ch in enumerate(_row):
        near = [_row[_c + d] for d in (-1, 1) if 0 <= _c + d < len(_row)]
        near += [_ROWS[_r + d][_c] for d in (-1, 1) if 0 <= _r + d < len(_ROWS) and _c < len(_ROWS[_r + d])]
        NEIGHBORS[_ch] = near
CONFUSED = {
    "their": ("there", "they're"), "there": ("their",), "they're": ("their", "there"),
    "your": ("you're",), "you're": ("your",), "its": ("it's",), "it's": ("its",),
    "then": ("than",), "than": ("then",), "affect": ("effect",), "effect": ("affect",),
    "to": ("too",), "too": ("to",), "were": ("where",), "where": ("were",), "lose": ("loose",),
    "loose": ("lose",), "accept": ("except",), "except": ("accept",), "whose": ("who's",),
    "who's": ("whose",),
}


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


def misspell(rest):
    """A slip at the start of rest (the rest of a word, 2+ letters) plus a few right letters after it,
    as typed before noticing. None if the letter isn't one to slip on."""
    first = rest[0]
    if not first.isalpha() or not rest[1].isalpha():
        return None
    kinds = ["near", "double", "skip"] + (["swap"] if rest[1] != first else [])
    kind = random.choice(kinds)
    near = NEIGHBORS.get(first.lower())
    if kind == "near" and near:
        slip = random.choice(near)
        wrong, used = (slip.upper() if first.isupper() else slip), 1
    elif kind == "swap":
        wrong, used = rest[1] + first, 2
    elif kind == "skip":
        return rest[1:2 + random.randint(0, 2)]  # the next letters, without this one
    else:
        wrong, used = first * 2, 1
    return wrong + rest[used:used + random.randint(0, 3)]


def confused_with(word):
    """A word often typed by mistake for this one (their/there, its/it's, ...), or None."""
    alts = CONFUSED.get(word.lower().replace("’", "'"))
    if not alts:
        return None
    alt = random.choice(alts)
    if "’" in word or ("'" not in word and "’" in alt):
        alt = alt.replace("'", "’")
    return alt[0].upper() + alt[1:] if word[0].isupper() else alt


class Typer:
    """Plays ops into the front app on a background thread until done, stopped, or focus moves."""

    RETYPE_CHANCE = 0.04  # per word that can be retyped, so roughly one every 30 to 40 words
    TYPO_CHANCE = 0.05  # per word of 3+ letters: a spelling slip that gets noticed and fixed
    GRAMMAR_CHANCE = 0.3  # per often-confused word (their, your, its, ...): the wrong one, then fixed

    def __init__(self, backend, ops, start, target, get_wpm, vary, retype=False, mistakes=False,
                 cleanup=0):
        self.backend, self.ops, self.pos = backend, ops, start
        self.target, self.get_wpm, self.vary, self.retype = target, get_wpm, vary, retype
        self.mistakes = mistakes
        self.stray = cleanup  # wrong characters in the document that still need deleting
        self.typo_at = None  # where the next spelling slip goes, planned at the start of a word
        self.checked_at = None
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

    def _word_from(self, i):
        j = i
        while j < len(self.ops) and is_word_char(self.ops[j]):
            j += 1
        return "".join(op[1] for op in self.ops[i:j])

    def _mistake(self):
        """Wrong text to type at pos before the right text, or None. Mistakes stay inside a word, or
        replace a whole word that follows a plain space, so fixing them never changes formatting."""
        pos, ops = self.pos, self.ops
        if pos == self.checked_at or not is_word_char(ops[pos]):
            return None
        self.checked_at = pos
        if pos == 0 or not is_word_char(ops[pos - 1]):  # start of a word: plan what happens in it
            self.typo_at = None
            word = self._word_from(pos)
            alt = confused_with(word) if pos and ops[pos - 1] == ("c", " ") else None
            if alt and random.random() < self.GRAMMAR_CHANCE:
                return alt
            if len(word) >= 3 and random.random() < self.TYPO_CHANCE:
                self.typo_at = pos + random.randint(1, len(word) - 2)
            return None
        if pos == self.typo_at:
            self.typo_at = None
            return misspell(self._word_from(pos))
        return None

    def _erase_stray(self):
        while self.stray:
            if not self._can_go_on():
                return False
            self.backend.press_backspace()
            self.stray -= 1
            if not self._sleep(self._base() * random.uniform(0.4, 0.8)):
                return False
        return self._sleep(random.uniform(0.15, 0.4))

    def _detour(self, wrong):
        """Types a mistake, pauses as if noticing it, then backspaces it away. pos doesn't move."""
        for ch in wrong:
            if not self._can_go_on():
                return False
            self.backend.type_char(ch)
            self.stray += 1
            self.recent.append(time.perf_counter())
            if not self._sleep(self._delay(("c", ch))):
                return False
        if not self._sleep(random.uniform(0.3, 0.9)):
            return False
        return self._erase_stray()

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
        if self.stray and not self._erase_stray():  # left over from a mistake when it was stopped
            return
        while self.pos < len(self.ops):
            if not self._can_go_on():
                return
            wrong = self._mistake() if self.mistakes else None
            if wrong and not self._detour(wrong):
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
