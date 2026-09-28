"""The Docs Typer window. Shared by Windows and macOS; only the backend differs."""

import datetime
import json
import math
import os
import queue
import random
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

from . import theme as T
from .intro import Intro
from .keystrokes import TEXT_OPS, Typer, build_ops, is_glyph
from .mascot import Mascot
from .model import SOFT_BREAK, Unreadable, doc_from_plain
from .motion import (ColorState, Tweens, Value, clamp01, ease_back, ease_out, linear, mix, partial_path,
                     ticker)
from .platforms import get_backend
from .readers import load_file, read_html
from .widgets import Button, Check, KeyStrip, Progress, Pulse, Segmented, Slider, Swatches, Title, Tooltip

C = T.C
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

SUBTITLE = "Paste text or open a file, press Start, then click into your Google Doc."
PLACEHOLDER = "Paste your text here, or open a .docx, .rtf, .odt or .html file."
HANDS_OFF = "Once typing starts, hands off — any key, click or mouse movement stops it."
COUNTDOWNS = ["3s", "5s", "10s"]


def fmt_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sec"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    return f"{seconds // 3600} h {round(seconds % 3600 / 60)} min"


def fmt_clock(seconds_from_now):
    t = datetime.datetime.now() + datetime.timedelta(seconds=seconds_from_now)
    return t.strftime("%I:%M %p").lstrip("0")


def settings_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/Library/Application Support")
    return os.path.join(base, "DocsTyper", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


class BoxOverlay(tk.Canvas):
    """Covers the text box for the countdown and the finish celebration."""

    def __init__(self, parent, scale=1.0):
        super().__init__(parent, highlightthickness=0, bd=0, bg=C["field"])
        self.s, self.mode, self.t0, self.fade = scale, None, 0.0, 0.0
        self.particles, self.seconds, self.stats = [], 5, ""
        self.num_fonts = {}
        self.f_label = tkfont.Font(family=T.FONT, size=11)
        self.f_small = tkfont.Font(family=T.FONT, size=9)
        self.f_done = tkfont.Font(family=T.TITLE_FONT, size=16)

    def _num_font(self, size):
        f = self.num_fonts.get(size)
        if f is None:
            f = self.num_fonts[size] = tkfont.Font(family=T.TITLE_FONT, size=size)
        return f

    def show(self, mode, seconds=5, stats=""):
        self.mode, self.t0, self.seconds, self.stats = mode, time.perf_counter(), seconds, stats
        self.fade = 1.0
        if mode == "done":
            self.particles = [(random.uniform(0, 2 * math.pi), random.uniform(0.55, 1.3),
                               random.choice(T.CONFETTI), random.uniform(2.2, 4.4), random.uniform(-1, 1))
                              for _ in range(60)]
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.tk.call("raise", self._w)  # Canvas.lift() raises canvas items, not the widget
        ticker(self).add(f"overlay{id(self)}", self._frame)

    def hide(self, ms=260):
        if self.mode is None:
            return
        start = time.perf_counter()

        def fading(now):
            self.fade = 1 - clamp01((now - start) * 1000 / ms)
            self._draw(now)
            if self.fade <= 0:
                ticker(self).remove(f"overlay{id(self)}")
                self.place_forget()
                self.mode = None

        ticker(self).add(f"overlay{id(self)}", fading)

    def _frame(self, now):
        self._draw(now)
        if self.mode == "done" and now - self.t0 > 3.0:
            self.hide(450)

    def c(self, color, t=1.0):
        return mix(C["field"], color, t * self.fade)

    def _draw(self, now):
        self.delete("all")
        s = self.s
        w, h = self.winfo_width(), self.winfo_height()
        cx, cy = w / 2, h / 2 - 16 * s
        e = now - self.t0
        R = 48 * s
        if self.mode == "countdown":
            total = self.seconds
            left = max(total - e, 0)
            num = max(1, math.ceil(left))
            within = 1 - (left - math.floor(left)) if left > 0 else 1
            rad = R + ease_out(within) * 40 * s
            self.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, width=max(1, int(2 * s)),
                             outline=self.c(C["accent"], 0.55 * (1 - within)))
            self.create_oval(cx - R, cy - R, cx + R, cy + R, width=int(5 * s), outline=self.c(C["track"]))
            extent = 360 * left / total
            if extent > 0.5:
                self.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=extent, style="arc",
                                width=int(5 * s), outline=self.c(C["accent"]))
                ang = math.radians(90 + extent)
                dx, dy = cx + math.cos(ang) * R, cy - math.sin(ang) * R
                d = 4.5 * s
                self.create_oval(dx - d, dy - d, dx + d, dy + d, outline="", fill=self.c(C["accent_hover"]))
            pop = ease_back(clamp01(within * 3.2))
            size = int(34 + (1 - pop) * 16)
            self.create_text(cx, cy, text=str(num), font=self._num_font(size),
                             fill=self.c(C["text"], clamp01(within * 5)))
            self.create_text(cx, cy + R + 30 * s, text="Click into your Google Doc", font=self.f_label,
                             fill=self.c(C["text"]))
            self.create_text(cx, cy + R + 52 * s, text="then keep your hands off the keyboard and mouse",
                             font=self.f_small, fill=self.c(C["muted"]))
        elif self.mode == "done":
            circle = ease_out(clamp01(e / 0.5))
            self.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=-359.9 * circle, style="arc",
                            width=int(5 * s), outline=self.c(C["ok"]))
            if e > 0.3:
                pts = [(cx - R * 0.38, cy + R * 0.02), (cx - R * 0.08, cy + R * 0.32), (cx + R * 0.42, cy - R * 0.28)]
                self.create_line(*partial_path(pts, ease_out(clamp01((e - 0.3) / 0.35))), width=int(5 * s),
                                 fill=self.c(C["ok"]), capstyle="round", joinstyle="round")
            burst = clamp01((e - 0.35) / 1.8)
            if 0 < burst < 1:
                for ang, speed, color, size, spin in self.particles:
                    d = (R + 10 * s) + ease_out(burst) * 140 * s * speed
                    px = cx + math.cos(ang) * d
                    py = cy + math.sin(ang) * d + burst ** 2 * 80 * s
                    r = size * s * (1 - burst * 0.6)
                    tilt = spin * math.sin(burst * 12) * r
                    self.create_polygon(px - r, py - r * 0.5 + tilt, px + r, py - r * 0.5 - tilt,
                                        px + r, py + r * 0.5 - tilt, px - r, py + r * 0.5 + tilt,
                                        fill=self.c(color, 1 - burst ** 3), outline="")
            label = clamp01((e - 0.5) / 0.4)
            self.create_text(cx, cy + R + 30 * s + (1 - ease_out(label)) * 8 * s, text="All typed!",
                             font=self.f_done, fill=self.c(C["text"], label))
            if self.stats:
                st = clamp01((e - 0.8) / 0.4)
                self.create_text(cx, cy + R + 56 * s, text=self.stats, font=self.f_small,
                                 fill=self.c(C["muted"], st))


class App:
    def __init__(self, root, backend=None, intro=True):
        self.root = root
        self.backend = backend or get_backend()
        self.prefs = load_settings()
        self.doc = None  # rich document loaded from a file or rich paste
        self.doc_text = None  # the text shown in the box for self.doc
        self.ops, self.pos, self.total = [], 0, 0
        self.stray = 0  # wrong characters a stopped mistake left in the document
        self.text_before = []  # for each op index, how many text characters come before it
        self.char_offsets = []  # text box offset of each typeable character
        self.state = "idle"  # idle | countdown | typing
        self.typer = None
        self.last_seen = 0
        self.run_started, self.run_typed = None, 0
        self.stop_reason = None
        self.events = queue.Queue()
        self.watcher = self.backend.InputWatcher(lambda reason: self.events.put(("input", reason)))
        self.wpm = int(self.prefs.get("wpm", 60))
        self.countdown_secs = int(self.prefs.get("countdown", 5))
        self.status_key = None
        self.tweens = Tweens(root)
        accent = self.prefs.get("accent")
        if accent in [c for _, c in T.ACCENTS]:
            T.set_accent(accent, notify=False)

        s = self.s = self.backend.scale(root)

        def px(n):
            return int(n * s)

        root.title("Docs Typer")
        root.configure(bg=C["bg"])
        sh = root.winfo_screenheight()
        height = min(px(840), sh - px(90))
        root.geometry(f"{px(620)}x{height}")
        root.minsize(px(540), min(px(700), sh - px(110)))
        self.fonts = {}

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Dark.Vertical.TScrollbar", gripcount=0, background=C["raised_hover"],
                        troughcolor=C["field"], bordercolor=C["field"], lightcolor=C["raised_hover"],
                        darkcolor=C["raised_hover"], arrowcolor=C["muted"], arrowsize=px(11), relief="flat")
        style.map("Dark.Vertical.TScrollbar", background=[("active", C["border_hover"])])

        outer = tk.Frame(root, bg=C["bg"], padx=px(18), pady=px(14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        self.inset = inset = px(8)  # matches the halo room inside buttons and checkboxes

        # Header: title + subtitle on the left, the mascot on the right.
        header = tk.Frame(outer, bg=C["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=inset)
        header.columnconfigure(0, weight=1)
        self.title = Title(header, "Docs Typer", scale=s)
        self.title.grid(row=0, column=0, sticky="sw")
        subtitle = tk.Label(header, text=SUBTITLE, bg=C["bg"], fg=C["muted"], font=(T.FONT, 10),
                            justify="left", anchor="w")
        subtitle.grid(row=1, column=0, sticky="ew", pady=(0, px(2)))
        header.bind("<Configure>", lambda e: subtitle.configure(wraplength=max(e.width - px(260), px(180))))
        self.mascot = Mascot(header, scale=s)
        self.mascot.grid(row=0, column=1, rowspan=2, sticky="se")

        # Text box
        self.box = tk.Frame(outer, bg=C["field"], highlightthickness=1,
                            highlightbackground=C["border"], highlightcolor=C["border"])
        self.box.grid(row=1, column=0, sticky="nsew", padx=inset, pady=(px(10), px(6)))
        self.box_colors = ColorState(self.tweens, "focus", self._paint_box, border=C["border"])
        self.text = tk.Text(self.box, wrap="word", undo=True, font=(T.FONT, 10), bg=C["field"],
                            fg=C["text"], insertbackground=C["accent"], insertwidth=px(2),
                            selectbackground=C["select"], selectforeground=C["text"],
                            inactiveselectbackground=C["select"], relief="flat", borderwidth=0,
                            highlightthickness=0, padx=px(16), pady=px(14), spacing1=px(2), spacing3=px(2))
        self.scrollbar = ttk.Scrollbar(self.box, style="Dark.Vertical.TScrollbar", command=self.text.yview)
        self.text.configure(yscrollcommand=self.autohide_scroll)
        self.text.pack(side="left", fill="both", expand=True)
        self.placeholder = tk.Label(self.box, text=PLACEHOLDER, bg=C["field"], fg=C["faint"],
                                    font=(T.FONT, 10), cursor="xterm", justify="left", anchor="nw")
        self.placeholder.bind("<Button-1>", lambda e: self.text.focus_set())
        self.box.bind("<Configure>", lambda e: self.placeholder.configure(wraplength=e.width - px(44)))
        self.overlay = BoxOverlay(self.box, scale=s)
        self.text.bind("<FocusIn>", lambda e: self.box_colors.fade(ms=200, border=C["accent"]))
        self.text.bind("<FocusOut>", lambda e: self.box_colors.fade(ms=200, border=C["border"]))
        for w in (self.text, self.placeholder):
            w.bind("<Enter>", lambda e: self.root.focus_get() is not self.text
                   and self.box_colors.fade(border=C["border_hover"]))
            w.bind("<Leave>", lambda e: self.root.focus_get() is not self.text
                   and self.box_colors.fade(border=C["border"]))
        self.text.bind("<<Paste>>", self.on_paste)
        self.text.bind(f"<{self.backend.accel}-Shift-V>", self.paste_plain)
        self.text.bind(f"<{self.backend.accel}-Shift-v>", self.paste_plain)
        self.text.bind("<<Modified>>", self.on_modified)
        self._style_tags()

        # Keyboard that slides open while typing.
        self.keystrip = KeyStrip(outer, scale=s)
        self.keystrip.grid(row=2, column=0, sticky="ew", padx=inset)

        # Speed
        speed = tk.Frame(outer, bg=C["bg"])
        speed.grid(row=3, column=0, sticky="ew", padx=inset)
        speed.columnconfigure(1, weight=1)
        tk.Label(speed, text="Speed", bg=C["bg"], fg=C["text"], font=(T.FONT, 10), width=9, anchor="w").grid(
            row=0, column=0, sticky="sw", pady=(0, px(9)))
        self.speed = Slider(speed, 10, 200, self.wpm, self.on_speed, fmt=lambda v: f"{v} wpm", scale=s)
        self.speed.grid(row=0, column=1, sticky="ew")
        self.speed_label = tk.Label(speed, text="", bg=C["bg"], fg=C["muted"], font=(T.FONT, 10),
                                    width=8, anchor="e")
        self.speed_label.grid(row=0, column=2, sticky="se", pady=(0, px(9)))
        self.speed_shown = Value(self.tweens, "speed", self._paint_speed, self.wpm)

        # Countdown length and accent color
        row = tk.Frame(outer, bg=C["bg"])
        row.grid(row=4, column=0, sticky="ew", padx=inset, pady=(px(2), px(4)))
        tk.Label(row, text="Countdown", bg=C["bg"], fg=C["text"], font=(T.FONT, 10), width=9, anchor="w").pack(side="left")
        cd = f"{self.countdown_secs}s" if f"{self.countdown_secs}s" in COUNTDOWNS else "5s"
        self.countdown_pick = Segmented(row, COUNTDOWNS, cd, self.on_countdown, scale=s)
        self.countdown_pick.pack(side="left", padx=(px(6), 0))
        self.swatches = Swatches(row, T.ACCENTS, C["accent"], self.on_accent, scale=s)
        self.swatches.pack(side="right")
        tk.Label(row, text="Accent", bg=C["bg"], fg=C["muted"], font=(T.FONT, 10)).pack(side="right", padx=(0, px(4)))

        # Options
        opts = tk.Frame(outer, bg=C["bg"])
        opts.grid(row=5, column=0, sticky="w")
        self.keep_formatting = tk.BooleanVar(value=self.prefs.get("keep_formatting", True))
        self.vary_pace = tk.BooleanVar(value=self.prefs.get("vary_pace", True))
        self.retype_words = tk.BooleanVar(value=self.prefs.get("retype_words", False))
        self.make_mistakes = tk.BooleanVar(value=self.prefs.get("make_mistakes", False))
        keep = Check(opts, "Keep formatting", self.keep_formatting, self.options_changed, scale=s)
        keep.pack(side="left")
        vary = Check(opts, "Vary pace", self.vary_pace, self.options_changed, scale=s)
        vary.pack(side="left", padx=(px(12), 0))
        retype = Check(opts, "Retype words", self.retype_words, self.options_changed, scale=s)
        retype.pack(side="left", padx=(px(12), 0))
        mistakes = Check(opts, "Make mistakes", self.make_mistakes, self.options_changed, scale=s)
        mistakes.pack(side="left", padx=(px(12), 0))
        Tooltip([keep, keep.box, keep.label], "Recreates bold, italics, underline, headings, lists and "
                "alignment using Google Docs keyboard shortcuts.", scale=s)
        Tooltip([vary, vary.box, vary.label], "Adds small, natural pauses: a beat after sentences and "
                "now and then between words.", scale=s)
        Tooltip([retype, retype.box, retype.label], "Every so often, deletes the word it just typed "
                "and types it again, like a second thought.", scale=s)
        Tooltip([mistakes, mistakes.box, mistakes.label], "Now and then makes a typo (a wrong, doubled, "
                "swapped or missed letter) or mixes up words like their/there, then notices and fixes "
                "it.", scale=s)

        self.progress = Progress(outer, scale=s)
        self.progress.grid(row=6, column=0, sticky="ew", padx=inset, pady=(px(8), px(8)))

        # Status and buttons
        status_row = tk.Frame(outer, bg=C["bg"])
        status_row.grid(row=7, column=0, sticky="ew", padx=inset)
        status_row.columnconfigure(1, weight=1)
        self.pulse = Pulse(status_row, scale=s)
        self.status = tk.Label(status_row, text="", bg=C["bg"], fg=C["muted"], font=(T.FONT, 9),
                               justify="left", anchor="w")
        self.status.grid(row=0, column=1, sticky="ew")
        status_row.bind("<Configure>", lambda e: self.status.configure(wraplength=e.width - px(24)))

        buttons = tk.Frame(outer, bg=C["bg"])
        buttons.grid(row=8, column=0, sticky="ew", pady=(px(2), 0))
        self.open_button = Button(buttons, "Open file…", self.open_file, scale=s)
        self.open_button.pack(side="left")
        self.start_button = Button(buttons, "Start", self.toggle, kind="primary", scale=s, min_text="Resume")
        self.start_button.pack(side="right")
        self.reset_button = Button(buttons, "Start over", self.start_over, scale=s)
        self.reset_button.pack(side="right")

        acc = self.backend.accel
        root.bind(f"<{acc}-o>", lambda e: self.state == "idle" and self.open_file())
        root.bind(f"<{acc}-O>", lambda e: self.state == "idle" and self.open_file())
        root.bind(f"<{acc}-Return>", lambda e: (self.state == "idle" and self.begin_countdown(), "break")[1])
        T.on_accent(self._style_tags)

        self.on_speed(self.wpm, save=False)
        self.update_placeholder()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.refresh()
        self.poll()
        if intro:
            Intro(root, on_done=self.after_intro, scale=s)
        else:
            self.after_intro()

    def shortcut_hint(self):
        if self.backend.name == "macos":
            return "⌘O to open a file · ⌘↩ to start"
        return "Ctrl+O to open a file · Ctrl+Enter to start"

    def after_intro(self):
        self.title.do_wave()
        self.mascot.hop()
        self.mascot.say("hi! I'll do the typing", 2.8)
        if not self.text.get("1.0", "end-1c"):
            self.text.focus_set()

    def save_prefs(self):
        save_settings({"wpm": self.wpm, "countdown": self.countdown_secs, "accent": C["accent"],
                       "keep_formatting": self.keep_formatting.get(), "vary_pace": self.vary_pace.get(),
                       "retype_words": self.retype_words.get(), "make_mistakes": self.make_mistakes.get()})

    # -- text box
    def _style_tags(self):
        self.text.tag_configure("typed", foreground=C["text"])
        self.text.tag_configure("cursor", background=C["accent"], foreground=C["field"])
        self.text.tag_configure("marker", foreground=C["accent"])
        self.text.configure(insertbackground=C["accent"], selectbackground=C["select"],
                            inactiveselectbackground=C["select"])
        if self.root.focus_get() is self.text:
            self.box_colors.colors["border"] = C["accent"]
            self._paint_box()

    def _paint_box(self):
        self.box.configure(highlightbackground=self.box_colors["border"],
                           highlightcolor=self.box_colors["border"])

    def autohide_scroll(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y", before=self.text)
        self.scrollbar.set(first, last)

    def update_placeholder(self):
        key = "placeholder"
        if self.text.get("1.0", "end-1c"):
            self.placeholder.place_forget()
            ticker(self.root).remove(key)
        else:
            self.placeholder.place(x=int(17 * self.s), y=int(14 * self.s))
            t0 = time.perf_counter()
            ticker(self.root).add(key, lambda now: self.placeholder.configure(
                fg=mix(C["faint"], C["muted"], (1 - math.cos((now - t0) * 1.6)) / 2 * 0.7)))

    def font_for(self, fmt, heading):
        key = (fmt, heading)
        if key not in self.fonts:
            size = {0: 10, 1: 18, 2: 15, 3: 13, 4: 12, 5: 11, 6: 10}[heading]
            if "sup" in fmt or "sub" in fmt:
                size = max(size - 3, 7)
            self.fonts[key] = tkfont.Font(family=T.TITLE_FONT if heading else T.FONT, size=size,
                                          weight="bold" if "b" in fmt else "normal",
                                          slant="italic" if "i" in fmt else "roman",
                                          underline="u" in fmt, overstrike="s" in fmt)
        return self.fonts[key]

    def show_doc(self, paras):
        self.text.delete("1.0", "end")
        counters = {}
        for n, p in enumerate(paras):
            if n:
                self.text.insert("end", "\n")
            start = self.text.index("end-1c")
            prefix = ""
            if p.list:
                counters = {k: v for k, v in counters.items() if k <= p.level}
                counters[p.level] = counters.get(p.level, 0) + 1
                prefix = "•  " if p.list == "bullet" else f"{counters[p.level]}.  "
            else:
                counters = {}
            self.text.insert("end", prefix, "marker")
            for text, fmt in p.runs:
                tag = f"f{hash((fmt, p.heading))}"
                self.text.tag_configure(tag, font=self.font_for(fmt, p.heading),
                                        offset=4 if "sup" in fmt else -2 if "sub" in fmt else 0)
                self.text.insert("end", text.replace(SOFT_BREAK, "\n"), tag)
            ptag = f"p{p.align}{p.level if p.list else -1}{p.heading}"
            indent = int((p.level + 1) * 18 * self.s) if p.list else 0
            self.text.tag_configure(ptag, justify={"justify": "left"}.get(p.align, p.align),
                                    lmargin1=indent, lmargin2=indent + (int(16 * self.s) if p.list else 0),
                                    spacing1=int(10 * self.s) if p.heading else int(2 * self.s))
            self.text.tag_add(ptag, start, "end-1c")
        self.doc = paras
        self.doc_text = self.text.get("1.0", "end-1c")
        self.text.edit_reset()
        self.text.edit_modified(False)  # loading isn't an edit; keep any saved place
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self.update_placeholder()
        self.reveal_text()
        self.mascot.say(random.choice(["ooh, nice doc", "got it!", "looks good", "ready to type"]), 2.2)

    def reveal_text(self):
        """Fade freshly loaded text in, line by line from the top."""
        lines = min(int(self.text.index("end-1c").split(".")[0]), 60)
        for i in range(1, lines + 1):
            tag = f"reveal{i}"
            self.text.tag_configure(tag, foreground=C["field"])
            self.text.tag_add(tag, f"{i}.0", f"{i}.end")
            self.text.tag_raise(tag)

        def step(t):
            for i in range(1, lines + 1):
                local = clamp01(t * (1 + lines * 0.12) - (i - 1) * 0.12)
                self.text.tag_configure(f"reveal{i}", foreground=mix(C["field"], C["text"], ease_out(local)))

        def done():
            for i in range(1, lines + 1):
                self.text.tag_delete(f"reveal{i}")

        self.tweens.run("reveal", 360 + min(lines, 20) * 40, step, ease=linear, done=done)

    def current_doc(self):
        text = self.text.get("1.0", "end-1c")
        if self.doc is not None and text == self.doc_text:
            return self.doc
        return doc_from_plain(text)

    def on_modified(self, _event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if self.state == "idle" and self.pos:
                # Text changed while stopped; the old place no longer lines up.
                self.pos, self.ops = 0, []
                self.stop_reason = None
                self.progress.to(0)
                self.clear_typed()
            self.update_placeholder()
            self.refresh()

    def on_paste(self, _event=None):
        text_now = self.text.get("1.0", "end-1c")
        replacing_all = not text_now.strip() or (
            self.text.tag_ranges("sel") and self.text.get("sel.first", "sel.last") == text_now)
        if replacing_all:
            html = self.backend.clipboard_html()
            if html:
                paras = read_html(html)
                if paras:
                    self.show_doc(paras)
                    self.refresh()
                    return "break"
        return None  # default plain paste

    def paste_plain(self, _event=None):
        try:
            s = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
        self.text.insert("insert", s)
        return "break"

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open a document",
            filetypes=[("Documents", "*.docx *.rtf *.odt *.html *.htm *.txt *.md"), ("All files", "*.*")])
        if not path:
            return
        try:
            paras = load_file(path)
        except Unreadable as e:
            self.set_status(str(e), "warn")
            self.shake(self.box)
            self.mascot.say("I can't read that one", 2.5)
            return
        self.start_over()
        self.show_doc(paras)
        self.refresh()

    # -- live view of what's been typed
    def map_text(self):
        """Line up each typeable op with its character in the box (list markers are display only)."""
        text = self.text.get("1.0", "end-1c")
        skip = [False] * len(text)
        ranges = self.text.tag_ranges("marker")
        for a, b in zip(ranges[0::2], ranges[1::2]):
            i = len(self.text.get("1.0", a))
            j = len(self.text.get("1.0", b))
            for k in range(i, min(j, len(skip))):
                skip[k] = True
        self.char_offsets = [k for k in range(len(text)) if not skip[k]]
        count, self.text_before = 0, []
        for op in self.ops:
            self.text_before.append(count)
            if op[0] in TEXT_OPS:
                count += 1
        self.text_before.append(count)

    def show_typed(self, pos):
        if not self.char_offsets or pos >= len(self.text_before):
            return
        n = self.text_before[pos]
        self.text.tag_remove("typed", "1.0", "end")
        self.text.tag_remove("cursor", "1.0", "end")
        if n:
            end = self.char_offsets[min(n, len(self.char_offsets)) - 1] + 1
            self.text.tag_add("typed", "1.0", f"1.0 + {end} chars")
        if n < len(self.char_offsets) and self.state == "typing":
            at = f"1.0 + {self.char_offsets[n]} chars"
            self.text.tag_add("cursor", at, f"{at} + 1 chars")
            self.text.see(at)
        self.text.tag_raise("typed")
        self.text.tag_raise("marker")
        self.text.tag_raise("cursor")

    def clear_typed(self):
        self.text.tag_remove("typed", "1.0", "end")
        self.text.tag_remove("cursor", "1.0", "end")

    def cursor_glow(self, on):
        key = "cursorglow"
        if on:
            t0 = time.perf_counter()
            ticker(self.root).add(key, lambda now: self.text.tag_configure(
                "cursor", background=mix(C["select"], C["accent"], 0.45 + 0.55 * (math.sin((now - t0) * 7) + 1) / 2)))
        else:
            ticker(self.root).remove(key)

    def feed_keys(self, upto):
        """Show newly typed characters on the key strip and the mascot's keyboard."""
        chars = []
        for op in self.ops[self.last_seen:upto]:
            if op[0] == "c":
                chars.append(op[1])
            elif op[0] in ("enter", "soft", "tab"):
                chars.append("\n")
        self.last_seen = upto
        for ch in chars[-4:]:
            self.keystrip.press(ch)
        if chars:
            self.mascot.keystroke(chars[-1])

    # -- controls
    def on_speed(self, value, save=True):
        self.wpm = int(float(value))
        self.speed_shown.to(self.wpm, ms=240)
        if save:
            self.save_prefs()
        self.refresh()

    def _paint_speed(self):
        self.speed_label.configure(text=f"{round(self.speed_shown.v)} wpm")

    def on_countdown(self, label):
        self.countdown_secs = int(label.rstrip("s"))
        self.save_prefs()

    def on_accent(self, color):
        start = C["accent"]
        self.tweens.run("accent", 420, lambda t: T.set_accent(mix(start, color, t)), done=self.save_prefs)
        self.mascot.hop()
        self.mascot.say(random.choice(["new look!", "ooh, fancy", "love it"]), 1.6)

    def options_changed(self):
        self.save_prefs()
        if self.state == "idle" and self.pos:
            self.set_status("The formatting change applies after Start over.", "warn")
        else:
            self.refresh()

    def set_status(self, text, tone="muted", key=None):
        """Show a status line. A new key (or tone) fades the line in; the same key just updates it."""
        key = key or (tone, text)
        target = C[tone]
        if key == self.status_key:
            self.status.configure(text=text)
            return
        self.status_key = key
        self.status.configure(text=text)
        self.tweens.run("status", 300, lambda t: self.status.configure(fg=mix(C["bg"], target, t)))

    def toggle(self):
        if self.state == "idle":
            self.begin_countdown()
        else:
            self.stop("you pressed Stop")

    def start_over(self):
        if self.state != "idle":
            self.stop(None)
        self.ops, self.pos, self.stop_reason = [], 0, None
        self.stray = 0
        self.progress.to(0, ms=400)
        self.clear_typed()
        self.mascot.set_mode("idle")
        self.refresh()

    def begin_countdown(self):
        problem = self.backend.permission_problem()
        if problem:
            message, which = problem
            self.set_status(message, "warn")
            self.backend.open_permission_settings(which)
            self.mascot.say("I need permission first", 3)
            self.shake(self.box)
            return
        if not self.ops:
            paras = self.current_doc()
            if not any(p.text.strip() for p in paras):
                self.set_status("Paste some text or open a file first.", "warn")
                self.shake(self.box)
                self.mascot.say("nothing to type yet!", 2.2)
                return
            self.ops = build_ops(paras, self.keep_formatting.get())
            self.total = sum(1 for op in self.ops if is_glyph(op))
            self.pos, self.stray = 0, 0
            self.run_started, self.run_typed = None, 0
        self.map_text()
        self.stop_reason = None
        self.state = "countdown"
        self.countdown_left = self.countdown_secs
        self.root.attributes("-topmost", True)
        self.progress.value.v = 1.0
        self.progress.to(0.0, ms=self.countdown_secs * 1000, ease=linear, color="accent")
        self.overlay.show("countdown", seconds=self.countdown_secs)
        self.mascot.set_mode("countdown")
        self.tick()

    def shake(self, widget):
        """A quick sideways nudge to say 'not yet'."""
        def step(t):
            offset = int(math.sin(t * math.pi * 6) * (1 - t) * 6 * self.s)
            widget.grid_configure(padx=(self.inset + offset, self.inset - offset))

        self.tweens.run("shake", 450, step, ease=linear, done=lambda: widget.grid_configure(padx=self.inset))

    def tick(self):
        if self.state != "countdown":
            return
        if self.countdown_left > 0:
            self.set_status(f"Click into your Google Doc now — starting in {self.countdown_left}…",
                            "accent", key="countdown")
            self.countdown_left -= 1
            self.after_id = self.root.after(1000, self.tick)
            self.refresh_buttons()
            return
        target = self.backend.foreground()
        if self.backend.is_own(target, self.root):
            self.state = "idle"
            self.root.attributes("-topmost", False)
            self.overlay.hide()
            self.set_status("Didn't start: click into your Google Doc during the countdown.", "warn")
            self.progress.to(self.done_fraction(), color="warn")
            self.shake(self.box)
            self.mascot.set_mode("idle")
            self.mascot.say("you didn't click your doc!", 3)
            self.refresh_buttons()
            self.pulse_update()
            return
        if self.watcher.start() is False:
            self.state = "idle"
            self.root.attributes("-topmost", False)
            self.overlay.hide()
            self.set_status("Docs Typer needs Input Monitoring access so it can stop when you touch "
                            "anything. Allow it in System Settings, then quit and reopen Docs Typer.", "warn")
            self.backend.open_permission_settings("input")
            self.refresh()
            return
        self.state = "typing"
        self.overlay.hide(350)
        self.typer = Typer(self.backend, self.ops, self.pos, target, lambda: self.wpm, self.vary_pace.get(),
                           self.retype_words.get(), self.make_mistakes.get(), cleanup=self.stray)
        self.last_seen = self.pos
        if self.run_started is None:
            self.run_started = time.perf_counter()
        self.typer.thread.start()
        self.progress.to(self.done_fraction(), color="accent")
        self.progress.set_shimmer(True)
        self.keystrip.show(True)
        self.cursor_glow(True)
        self.mascot.set_mode("typing")
        self.refresh()

    def _end_typing(self):
        if self.typer:
            self.run_typed += self.typer.typed
            self.pos, self.stray = self.typer.pos, self.typer.stray
            self.typer = None
        self.watcher.stop()
        self.state = "idle"
        self.root.attributes("-topmost", False)
        self.progress.set_shimmer(False)
        self.keystrip.show(False)
        self.cursor_glow(False)

    def stop(self, reason):
        if self.state == "countdown":
            self.root.after_cancel(self.after_id)
        if self.typer:
            self.typer.cancel.set()
            self.typer.thread.join(1)
        was = self.state
        self._end_typing()
        self.stop_reason = reason
        self.overlay.hide()
        self.show_typed(self.pos)
        self.progress.to(self.done_fraction(), color="warn" if self.pos else "accent")
        if reason and was == "typing":
            self.mascot.set_mode("stopped")
        else:
            self.mascot.set_mode("idle")
        self.refresh()

    def poll(self):
        try:
            while True:
                kind, reason = self.events.get_nowait()
                if kind == "input" and self.state == "typing":
                    self.stop(reason)
        except queue.Empty:
            pass
        if self.state == "typing" and self.typer and not self.typer.thread.is_alive():
            reason = self.typer.stop_reason
            self.feed_keys(self.typer.pos)
            self._end_typing()
            if self.pos >= len(self.ops):
                self.show_typed(self.pos)
                elapsed = time.perf_counter() - (self.run_started or time.perf_counter())
                chars = self.run_typed
                speed = chars / 5 / max(elapsed, 1) * 60
                stats = f"{chars:,} characters · {fmt_duration(elapsed)} · {speed:.0f} wpm average"
                self.ops, self.pos, self.stray = [], 0, 0
                self.stop_reason = "done"
                self.progress.to(1.0, color="ok")
                self.overlay.show("done", stats=stats)
                self.mascot.set_mode("done")
                self.root.after(3400, self._after_done)
            else:
                self.stop_reason = reason
                self.show_typed(self.pos)
                self.progress.to(self.done_fraction(), color="warn")
                self.mascot.set_mode("stopped")
            self.refresh()
        elif self.state == "typing" and self.typer:
            pos = self.typer.pos
            self.progress.to(self.done_fraction(), ms=250)
            self.show_typed(pos)
            self.feed_keys(pos)
            self.refresh()
        self.root.after(80, self.poll)

    def _after_done(self):
        if self.state == "idle" and not self.pos:
            self.progress.to(0, ms=700)
            self.clear_typed()
            self.mascot.set_mode("idle")

    # -- display
    def remaining(self):
        pos = self.typer.pos if self.typer else self.pos
        return sum(1 for op in self.ops[pos:] if is_glyph(op))

    def done_fraction(self):
        if not self.ops or not self.total:
            return 0.0
        return 1 - self.remaining() / self.total

    def eta_seconds(self, glyphs):
        return glyphs * 60.0 / (self.wpm * 5) * (1.35 if self.vary_pace.get() else 1.0)

    def pulse_update(self):
        if self.state in ("typing", "countdown"):
            self.pulse.start("accent")
            self.pulse.grid(row=0, column=0, padx=(0, int(8 * self.s)))
        else:
            self.pulse.stop()
            self.pulse.grid_remove()

    def refresh_buttons(self):
        if not hasattr(self, "start_button"):
            return
        idle = self.state == "idle"
        has_text = bool(self.text.get("1.0", "end-1c").strip())
        if idle:
            self.start_button.set(text="Resume" if self.pos else "Start", kind="primary",
                                  breathing=has_text or bool(self.pos))
        else:
            self.start_button.set(text="Stop", kind="danger", breathing=True)
        self.open_button.set(enabled=idle)
        self.reset_button.set(enabled=not idle or bool(self.pos))
        self.text.configure(state="normal" if idle else "disabled",
                            fg=C["text"] if idle and not self.pos else C["faint"])

    def refresh(self):
        if not hasattr(self, "status"):
            return
        self.refresh_buttons()
        self.pulse_update()
        if self.state == "countdown":
            return
        if self.state == "typing":
            left = self.remaining()
            live = self.typer.live_wpm() if self.typer else None
            speed = f" · {live:.0f} wpm live" if live else ""
            self.set_status(f"Typing — {left:,} characters left{speed} · done around "
                            f"{fmt_clock(self.eta_seconds(left))}\nTouch anything to stop.", "text", key="typing")
            return
        if self.stop_reason == "done":
            self.set_status("Done — everything's typed.", "ok")
        elif self.pos and self.stop_reason:
            left = self.remaining()
            self.set_status(f"Stopped because {self.stop_reason}. {left:,} characters left — "
                            "put your cursor back where it left off, then Resume.", "warn")
        elif self.pos:
            self.set_status(f"{self.remaining():,} characters left. Put your cursor back where it "
                            "left off, then Resume.", "warn")
        else:
            paras = self.current_doc()
            glyphs = sum(len(p.text) for p in paras) + max(len(paras) - 1, 0)
            if not any(p.text.strip() for p in paras):
                self.set_status(f"{HANDS_OFF}\n{self.shortcut_hint()}", key="empty")
                if self.mascot.mode == "ready":
                    self.mascot.set_mode("idle")
            else:
                secs = self.eta_seconds(glyphs)
                self.set_status(f"{glyphs:,} characters · about {fmt_duration(secs)}\n{HANDS_OFF}", key="ready")
                if self.mascot.mode == "idle":
                    self.mascot.set_mode("ready")

    def quit(self):
        if self.state != "idle":
            self.stop(None)
        self.save_prefs()
        self.root.destroy()


def main():
    backend = get_backend()
    backend.setup_process()
    T.configure_fonts(backend)
    root = tk.Tk()
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    backend.set_icon(root, ASSETS)
    app = App(root, backend=backend)
    backend.style_window(root, C["bg"], C["text"])

    def fade(t):
        try:
            root.attributes("-alpha", t)
        except tk.TclError:
            pass

    app.tweens.run("window", 260, fade)
    root.mainloop()


if __name__ == "__main__":
    main()
