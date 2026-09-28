"""Tappy: a chunky pixel critter who does the typing for you.

The body is a 12×9 grid of square "pixels" with two ear nubs, sitting behind a
tiny keyboard. Poses (eyes, mouth, paws) are redrawn only when they change;
bobbing and eye tracking just move existing canvas items, so it stays smooth.
"""

import math
import random
import time
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T
from .motion import Tweens, clamp01, ease_back, ease_out, mix, rounded_rect, ticker

C = T.C

BODY = [(x, y) for y in range(9) for x in range(12) if (x, y) not in {(0, 0), (11, 0), (0, 8), (11, 8)}]
EARS = [(1, -1), (2, -1), (9, -1), (10, -1)]  # small two-pixel nubs
EYES = {
    "normal": [(3, 3), (3, 4), (8, 3), (8, 4)],
    "blink": [(3, 4), (8, 4)],
    "wide": [(3, 3), (4, 3), (3, 4), (4, 4), (7, 3), (8, 3), (7, 4), (8, 4)],
    "happy": [(2, 4), (3, 3), (4, 4), (7, 4), (8, 3), (9, 4)],
    "focus": [(3, 4), (4, 4), (7, 4), (8, 4)],
}
MOUTHS = {None: [], "smile": [(5, 6), (6, 6)], "o": [(5, 6), (6, 6), (5, 7), (6, 7)], "grin": [(4, 6), (5, 7), (6, 7), (7, 6)]}
KEYBOARD = [(x, y) for y in (9, 10) for x in range(-1, 13)]
KEYCAPS = [(x, 9) for x in range(0, 12, 2)] + [(x, 10) for x in range(1, 11, 2)]
def _hand(x, y):
    """A short, chunky 2×2 hand."""
    return [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]


PAWS = {  # hands only: no long arms
    "rest": _hand(-2, 5) + _hand(12, 5),
    "up": [(2, 8), (3, 8), (8, 8), (9, 8)],
    "left": [(2, 9), (3, 9), (8, 8), (9, 8)],
    "right": [(2, 8), (3, 8), (8, 9), (9, 9)],
    "wave": [(2, 8), (3, 8)] + _hand(12, 1),
    "cheer": _hand(-2, -1) + _hand(12, -1),
}
MARK = [(13, -5), (13, -4), (13, -3), (13, -1)]  # "!"


class PixelCritter:
    """Draws the critter onto any canvas at a given cell size."""

    def __init__(self, canvas, cell, ox, oy, tag):
        self.c, self.p, self.ox, self.oy, self.tag = canvas, cell, ox, oy, tag
        self.dx = self.dy = 0.0
        self.look = (0.0, 0.0)
        self.pose = {"eyes": "normal", "mouth": None, "paws": "up", "keyboard": True, "flash": None,
                     "mark": False, "blush": True}

    def set(self, **pose):
        changed = any(self.pose.get(k) != v for k, v in pose.items())
        self.pose.update(pose)
        if changed:
            self.render()

    def _cell(self, x, y, color, tag):
        p = self.p
        x0 = self.ox + self.dx + x * p
        y0 = self.oy + self.dy + y * p
        self.c.create_rectangle(x0, y0, x0 + p, y0 + p, fill=color, outline="", tags=(self.tag, tag))

    def render(self):
        c, pose = self.c, self.pose
        c.delete(self.tag)
        body = C["accent"]
        light = mix(body, "#FFFFFF", 0.18)
        shade = mix(body, "#000000", 0.22)
        for x, y in EARS:
            self._cell(x, y, light, "body")
        for x, y in BODY:
            col = light if y == 0 else shade if y == 8 else body
            self._cell(x, y, col, "body")
        if pose["blush"] and pose["eyes"] != "wide":
            for x in (2, 9):
                self._cell(x, 5, mix(body, "#F4A6A0", 0.55), "body")
        for x, y in EYES[pose["eyes"]]:
            self._cell(x, y, C["ink"], "eyes")
        for x, y in MOUTHS[pose["mouth"]]:
            self._cell(x, y, C["ink"], "body")
        if pose["keyboard"]:
            for x, y in KEYBOARD:
                self._cell(x, y, "#3A3936", "kb")
            for i, (x, y) in enumerate(KEYCAPS):
                self._cell(x, y, C["accent"] if pose["flash"] == i else "#5A5852", "kb")
        paw = mix(body, "#FFFFFF", 0.08)
        for x, y in PAWS[pose["paws"]]:
            self._cell(x, y, paw, "paws")
        if pose["mark"]:
            for x, y in MARK:
                self._cell(x, y, C["warn"], "mark")
        lx, ly = self.look
        if pose["eyes"] in ("normal", "wide"):
            c.move(f"{self.tag}&&eyes", lx, ly)

    def move_to(self, dx, dy):
        c = self.c
        c.move(self.tag, dx - self.dx, dy - self.dy)
        self.dx, self.dy = dx, dy

    def look_at(self, lx, ly):
        """Shift pupils by up to a fraction of a cell toward a point."""
        if self.pose["eyes"] not in ("normal", "wide"):
            self.look = (lx, ly)
            return
        ox, oy = self.look
        if abs(lx - ox) > 0.2 or abs(ly - oy) > 0.2:
            self.c.move(f"{self.tag}&&eyes", lx - ox, ly - oy)
            self.look = (lx, ly)

    def center(self):
        return self.ox + self.dx + 6 * self.p, self.oy + self.dy + 4 * self.p

    def keyboard_top(self):
        return self.ox + self.dx + 6 * self.p, self.oy + self.dy + 9 * self.p


LINES = {
    "idle": ["paste something in!", "ready when you are", "I type fast, promise", "open a doc for me?",
             "hi there!", "boop"],
    "ready": ["press Start!", "looks good to me", "let's type this"],
    "countdown": ["click your doc!", "into the doc!", "get ready…"],
    "typing": ["on it…", "tap tap tap", "typing away", "don't touch!"],
    "stopped": ["whoa, paused!", "hey!", "I stopped!"],
    "done": ["all done!", "nailed it!", "ta-da!"],
    "poke": ["hehe", "that tickles", "boing!", "hi!", ":)"],
}


class Mascot(tk.Canvas):
    """The header mascot: idles, follows your mouse, types along, celebrates, talks."""

    def __init__(self, parent, scale=1.0):
        self.s = scale
        self.cell = max(3, round(5 * scale))
        w, h = int(260 * scale), int(100 * scale)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.w, self.h = w, h
        ox = w - 16 * self.cell
        oy = h - 11 * self.cell - 4 * scale
        self.critter = PixelCritter(self, self.cell, ox, oy, "critter")
        self.tweens = Tweens(self)
        self.mode = "idle"
        self.t0 = time.perf_counter()
        self.next_blink = self.t0 + 2
        self.blink_until = 0
        self.hop_start = None
        self.hops = 0
        self.paw_flip = False
        self.particles = []  # [item, x, y, born, drift]
        self.bubble_text, self.bubble_born, self.bubble_until = None, 0, 0
        self.flash_until = 0
        self.mono = tkfont.Font(family=T.MONO_FONT, size=9, weight="bold")
        self.bubble_font = tkfont.Font(family=T.FONT, size=9)
        self.critter.render()
        self.bind("<Button-1>", lambda e: self.poke())
        self.bind("<Enter>", lambda e: self.greet())
        T.on_accent(self.critter.render)
        ticker(self).add(f"mascot{id(self)}", self._frame)

    # -- reactions
    def say(self, text, secs=2.6):
        self.bubble_text, self.bubble_born, self.bubble_until = text, time.perf_counter(), time.perf_counter() + secs
        self.delete("bubble")

    def say_mood(self, mood, secs=2.6):
        self.say(random.choice(LINES[mood]), secs)

    def hop(self, times=1):
        self.hop_start, self.hops = time.perf_counter(), times

    def poke(self):
        self.hop()
        self.say_mood("poke", 1.6)

    def greet(self):
        if self.mode in ("idle", "ready") and not self.hop_start:
            self.critter.set(paws="wave", eyes="happy", mouth="smile")
            self.wave_until = time.perf_counter() + 1.1

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        if mode == "countdown":
            self.critter.set(eyes="wide", mouth=None, paws="up", mark=False)
            self.say_mood("countdown", 5)
        elif mode == "typing":
            self.critter.set(eyes="focus", mouth=None, paws="up", mark=False)
            self.say_mood("typing", 2)
        elif mode == "stopped":
            self.critter.set(eyes="wide", mouth="o", paws="rest", mark=True)
            self.say_mood("stopped", 3)
            self.hop()
        elif mode == "done":
            self.critter.set(eyes="happy", mouth="grin", paws="cheer", mark=False)
            self.say_mood("done", 3.5)
            self.hop(3)
        else:
            self.critter.set(eyes="normal", mouth=None, paws="up", mark=False)
            if mode == "ready":
                self.say_mood("ready", 2.2)

    def keystroke(self, ch):
        """Tap a key and send a little letter floating up."""
        self.paw_flip = not self.paw_flip
        self.critter.set(paws="left" if self.paw_flip else "right", flash=random.randrange(len(KEYCAPS)))
        self.flash_until = time.perf_counter() + 0.09
        if ch and ch.strip() and len(self.particles) < 14:
            x, y = self.critter.keyboard_top()
            x += random.uniform(-4, 4) * self.cell
            item = self.create_text(x, y, text=ch, font=self.mono, fill=C["accent"])
            self.particles.append([item, x, y, time.perf_counter(), random.uniform(-0.8, 0.8)])

    # -- per-frame
    def _frame(self, now):
        e = now - self.t0
        cr = self.critter
        # Bob, faster when excited.
        speed = {"countdown": 7, "typing": 9, "done": 5}.get(self.mode, 2.2)
        amp = {"typing": 0.6, "countdown": 1.5}.get(self.mode, 1.4) * self.s
        dy = math.sin(e * speed) * amp
        dx = 0.0
        if self.hop_start is not None:
            ht = (now - self.hop_start) / 0.42
            if ht >= self.hops:
                self.hop_start = None
            else:
                frac = ht % 1
                dy -= math.sin(frac * math.pi) * 12 * self.s
        if self.mode == "stopped" and cr.pose["mark"]:
            dx = math.sin(e * 40) * 1.2 * self.s * max(0, 1 - (now - self.bubble_born))
        cr.move_to(dx, dy)

        # Wave ends, blinks, keyboard flash.
        if getattr(self, "wave_until", 0) and now > self.wave_until:
            self.wave_until = 0
            if self.mode in ("idle", "ready"):
                cr.set(paws="up", eyes="normal", mouth=None)
        if self.mode in ("idle", "ready") and cr.pose["eyes"] in ("normal", "blink"):
            if now > self.next_blink:
                cr.set(eyes="blink")
                self.blink_until = now + 0.12
                self.next_blink = now + random.uniform(2.2, 5.0)
            elif cr.pose["eyes"] == "blink" and now > self.blink_until:
                cr.set(eyes="normal")
        if cr.pose["flash"] is not None and now > self.flash_until:
            cr.set(flash=None)
        if self.mode == "typing" and cr.pose["paws"] != "up" and now > self.flash_until + 0.12:
            cr.set(paws="up")

        # Eyes follow the mouse.
        try:
            px, py = self.winfo_pointerxy()
            cx, cy = cr.center()
            vx, vy = px - (self.winfo_rootx() + cx), py - (self.winfo_rooty() + cy)
            dist = math.hypot(vx, vy) or 1
            reach = min(dist / 120, 1) * self.cell * 0.5
            cr.look_at(vx / dist * reach, vy / dist * reach)
        except tk.TclError:
            pass

        # Floating letters.
        alive = []
        for item, x, y, born, drift in self.particles:
            t = (now - born) / 0.9
            if t >= 1:
                self.delete(item)
                continue
            self.coords(item, x + drift * 12 * self.s * t, y - ease_out(t) * 34 * self.s)
            self.itemconfigure(item, fill=mix(C["accent"], C["bg"], t ** 2))
            alive.append([item, x, y, born, drift])
        self.particles = alive

        self._draw_bubble(now)

    def _draw_bubble(self, now):
        self.delete("bubble")
        if not self.bubble_text or now > self.bubble_until + 0.25:
            return
        s = self.s
        pop = ease_back(clamp01((now - self.bubble_born) / 0.28))
        fade = 1 - clamp01((now - self.bubble_until) / 0.25)
        vis = min(clamp01((now - self.bubble_born) / 0.15), fade)
        tw = self.bubble_font.measure(self.bubble_text)
        bw, bh = tw + 20 * s, 24 * s
        cx, _ = self.critter.center()
        right = self.critter.ox - 6 * s
        x0 = right - bw
        y0 = 8 * s + (1 - pop) * 6 * s
        fill = mix(C["bg"], C["raised"], vis)
        edge = mix(C["bg"], C["border_hover"], vis)
        rounded_rect(self, x0, y0, right, y0 + bh, 9 * s, fill=fill, outline=edge, tags="bubble")
        ty = y0 + bh * 0.62
        self.create_polygon(right - 1, ty - 5 * s, right + 7 * s, ty + 2 * s, right - 1, ty + 3 * s,
                            fill=fill, outline=edge, tags="bubble")
        self.create_line(right - 1, ty - 4 * s, right - 1, ty + 2 * s, fill=fill, tags="bubble")
        self.create_text(x0 + bw / 2, y0 + bh / 2, text=self.bubble_text, font=self.bubble_font,
                         fill=mix(C["bg"], C["text"], vis), tags="bubble")
