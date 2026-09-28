"""Opening sequence: the mascot types the app's name, letters fly into place, then the curtain lifts.

Everything is built once and animated by moving and recoloring existing canvas items,
which keeps it smooth.
"""

import math
import random
import time
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T
from .mascot import PixelCritter
from .motion import clamp01, ease_back, ease_in_out, ease_out, mix, ticker

C = T.C

NAME = "Docs Typer"
TAGLINE = "Your document, typed out one key at a time."
T_FIRST = 0.55  # first keystroke
PER_CHAR = 0.12
FLIGHT = 0.38
T_TITLE_DONE = T_FIRST + PER_CHAR * (len(NAME) - 1) + FLIGHT
T_TAG = T_TITLE_DONE + 0.1
TAG_PER_CHAR = 0.016
T_LEAVE = T_TAG + TAG_PER_CHAR * len(TAGLINE) + 0.75
LEAVE_MS = 0.6


class Intro(tk.Canvas):
    def __init__(self, root, on_done, scale=1.0):
        super().__init__(root, highlightthickness=0, bd=0, bg=C["bg"], cursor="hand2")
        self.root, self.on_done, self.s = root, on_done, scale
        self.t0 = time.perf_counter()
        self.skip_at = None
        self.built = False
        self.title_font = tkfont.Font(family=T.TITLE_FONT, size=34)
        self.tag_font = tkfont.Font(family=T.FONT, size=11)
        self.small_font = tkfont.Font(family=T.FONT, size=8)
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Button-1>", self.skip)
        self._key_binding = root.bind("<Key>", self.skip, add="+")
        ticker(self).add("intro", self._frame)

    @property
    def leave_at(self):
        return self.skip_at if self.skip_at is not None else T_LEAVE

    def skip(self, _event=None):
        e = time.perf_counter() - self.t0
        if self.skip_at is None and e < self.leave_at:
            self.skip_at = e

    def _build(self, w, h):
        s = self.s
        self.w, self.h = w, h
        self.cx = w / 2
        self.title_y = h * 0.30
        # Soft glow behind the title.
        self.glow = []
        for i in range(10, 0, -1):
            r = i * 24 * s
            item = self.create_oval(self.cx - r * 1.5, self.title_y - r, self.cx + r * 1.5, self.title_y + r,
                                    outline="", fill=C["bg"])
            self.glow.append((item, i))
        # Drifting dust.
        rng = random.Random(7)
        self.dust = []
        for _ in range(46):
            x, y = rng.uniform(0, w), rng.uniform(0, h)
            size = rng.uniform(1.2, 2.8) * s
            speed = rng.uniform(6, 22) * s
            phase = rng.uniform(0, math.tau)
            item = self.create_oval(x, y, x + size, y + size, outline="", fill=C["bg"])
            self.dust.append([item, x, y, size, speed, phase])
        # Title letters, placed but hidden until they land.
        widths = [self.title_font.measure(ch) for ch in NAME]
        x = self.cx - sum(widths) / 2
        self.slots = []
        for ch, cw in zip(NAME, widths):
            item = self.create_text(x, self.title_y, text=ch, font=self.title_font, fill=C["bg"], anchor="w")
            self.slots.append((item, x + cw / 2, cw))
            x += cw
        self.title_end = x
        lh = self.title_font.metrics("linespace")
        self.caret = self.create_line(0, self.title_y - lh * 0.36, 0, self.title_y + lh * 0.34,
                                      width=max(2, int(3 * s)), fill=C["bg"])
        self.tag = self.create_text(self.cx, self.title_y + 50 * s, text="", font=self.tag_font, fill=C["muted"])
        self.hint = self.create_text(self.cx, h - 22 * s, text="click to skip", font=self.small_font, fill=C["bg"])
        # The mascot at its keyboard.
        cell = max(5, round(9 * s))
        self.critter = PixelCritter(self, cell, self.cx - 6 * cell, h * 0.56, "introcritter")
        self.critter.pose.update(eyes="focus", paws="up", keyboard=True)
        self.critter.render()
        # Letters in flight.
        self.flyers = {}
        self.flip = False
        self.built = True

    def _frame(self, now):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or h < 50:
            return
        if not self.built:
            self._build(w, h)
        s = self.s
        e = now - self.t0
        skipping = self.skip_at is not None
        out = clamp01((e - self.leave_at) / LEAVE_MS)
        if out >= 1:
            self._finish()
            return
        if out > 0:
            self.place_configure(y=-h * ease_in_out(out))

        fade_in = clamp01(e / 0.4)
        # Glow breathes gently.
        breathe = 0.75 + 0.25 * math.sin(e * 2.2)
        lit = clamp01((e - T_FIRST) / 1.0) if not skipping else 1
        for item, i in self.glow:
            self.itemconfigure(item, fill=mix(C["bg"], C["accent"], 0.022 * (11 - i) * breathe * lit * fade_in))
        # Dust drifts up and twinkles.
        for d in self.dust:
            item, x, y, size, speed, phase = d
            yy = (y - e * speed) % (h + 10) - 5
            xx = x + math.sin(e * 0.8 + phase) * 8 * s
            self.coords(item, xx, yy, xx + size, yy + size)
            tw = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(e * 2.4 + phase * 3))
            self.itemconfigure(item, fill=mix(C["bg"], C["muted"], 0.5 * tw * fade_in))

        # Keystrokes: each letter launches from the keyboard and arcs up into its slot.
        kx, ky = self.critter.keyboard_top()
        landed = 0
        for i, (item, sx, cw) in enumerate(self.slots):
            t_key = T_FIRST + i * PER_CHAR
            if skipping and e >= self.skip_at:
                t_key = min(t_key, self.skip_at - FLIGHT)
            if e < t_key:
                continue
            if i not in self.flyers:
                self.flyers[i] = self.create_text(kx, ky, text=NAME[i], font=self.title_font, fill=C["accent"])
                self.flip = not self.flip
                if NAME[i] != " ":
                    self.critter.set(paws="left" if self.flip else "right", flash=random.randrange(11))
            f = clamp01((e - t_key) / FLIGHT)
            fl = self.flyers[i]
            if f < 1:
                p = ease_out(f)
                x = kx + (sx - kx) * p
                y = ky + (self.title_y - ky) * p - math.sin(f * math.pi) * 60 * s
                self.coords(fl, x, y)
                self.itemconfigure(fl, fill=mix(C["accent"], C["text"], p))
            else:
                if fl is not None:
                    self.delete(fl)
                    self.flyers[i] = None
                pop = clamp01((e - t_key - FLIGHT) / 0.3)
                self.itemconfigure(item, fill=mix(C["accent"], C["text"], ease_out(pop)))
                landed = i + 1
        # Caret sits after the last landed letter and blinks once the name is done.
        caret_x = self.slots[landed - 1][1] + self.slots[landed - 1][2] / 2 + 5 * s if landed else \
            self.slots[0][1] - self.slots[0][2] / 2 - 4 * s
        lh = self.title_font.metrics("linespace")
        self.coords(self.caret, caret_x, self.title_y - lh * 0.36, caret_x, self.title_y + lh * 0.34)
        blink = 1.0 if e < T_TITLE_DONE else (math.cos((e - T_TITLE_DONE) * 7) + 1) / 2
        self.itemconfigure(self.caret, fill=mix(C["bg"], C["accent"], blink * fade_in))

        # Mascot: taps between letters, cheers when done, bobs throughout.
        cr = self.critter
        if e > T_TITLE_DONE:
            if cr.pose["eyes"] != "happy":
                cr.set(eyes="happy", mouth="grin", paws="cheer", flash=None)
            hop = (e - T_TITLE_DONE) / 0.45
            dy = -math.sin((hop % 1) * math.pi) * 18 * s if hop < 2 else 0
        else:
            if cr.pose["flash"] is not None and (e - T_FIRST) % PER_CHAR > 0.07:
                cr.set(flash=None, paws="up")
            dy = math.sin(e * 9) * 1.2 * s
        cr.move_to(0, dy)

        # Tagline types itself.
        n = int(clamp01((e - T_TAG) / (TAG_PER_CHAR * len(TAGLINE))) * len(TAGLINE))
        if skipping:
            n = len(TAGLINE)
        self.itemconfigure(self.tag, text=TAGLINE[:n])
        self.itemconfigure(self.hint, fill=mix(C["bg"], C["faint"], 0.8 * fade_in * (1 - out)))

    def _finish(self):
        ticker(self).remove("intro")
        try:
            self.root.unbind("<Key>", self._key_binding)
        except tk.TclError:
            pass
        self.destroy()
        self.on_done()
