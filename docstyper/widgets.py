"""Canvas-drawn controls with hover, press and state animations.

Every widget leaves margin inside its canvas for halos and overshoot, so nothing
gets clipped at the edges.
"""

import math
import time
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T
from .motion import (ColorState, Tweens, Value, clamp01, ease_back, ease_in_out, ease_out, linear, mix,
                     partial_path, rounded_rect, ticker)

C = T.C


class Tooltip:
    """A small hint that fades in after hovering for a moment."""

    def __init__(self, widgets, text, scale=1.0):
        self.text, self.s, self.win, self.job, self.anchor = text, scale, None, None, widgets[0]
        for w in widgets:
            w.bind("<Enter>", self._schedule, add="+")
            w.bind("<Leave>", self._hide, add="+")
            w.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event=None):
        if self.job is None and self.win is None:
            self.job = self.anchor.after(500, self._show)

    def _show(self):
        self.job = None
        a, s = self.anchor, self.s
        win = self.win = tk.Toplevel(a)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        win.configure(bg=C["border_hover"])
        tk.Label(win, text=self.text, bg=C["raised"], fg=C["text"], font=(T.FONT, 9), justify="left",
                 wraplength=int(260 * s), padx=int(10 * s), pady=int(7 * s)).pack(padx=1, pady=1)
        x, y = a.winfo_rootx(), a.winfo_rooty() + a.winfo_height() + int(4 * s)
        tweens = Tweens(win)

        def step(t):
            if self.win is win:
                try:
                    win.attributes("-alpha", 0.97 * t)
                except tk.TclError:
                    pass
                win.geometry(f"+{x}+{int(y + (1 - t) * 6 * s)}")

        tweens.run("in", 180, step)

    def _hide(self, _event=None):
        if self.job:
            self.anchor.after_cancel(self.job)
            self.job = None
        if self.win is not None:
            self.win.destroy()
            self.win = None


class Button(tk.Canvas):
    """Rounded button: glowing halo and lifted label on hover, press dip, click flash, breathing."""

    KINDS = {  # fill, hover fill, text, border
        "primary": ("accent", "accent_hover", "ink", "accent"),
        "danger": ("danger", "danger_hover", "#FFFFFF", "danger"),
        "secondary": ("raised", "raised_hover", "text", "border"),
    }

    def __init__(self, parent, text, command, kind="secondary", scale=1.0, min_text="", icon=None):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.command, self.kind, self.text, self.s, self.icon = command, kind, text, scale, icon
        self.m = 8 * scale  # room for the halo
        self.font = tkfont.Font(family=T.FONT, size=10, weight="bold" if kind != "secondary" else "normal")
        self.min_w = self.font.measure(min_text)
        self.enabled, self.hover, self.breathing, self.breath = True, False, False, 0.0
        self.tweens = Tweens(self)
        self.colors = ColorState(self.tweens, "color", self._draw, **self._target())
        self.glow = Value(self.tweens, "glow", self._draw)
        self.press = Value(self.tweens, "press", self._draw)
        self.flash = Value(self.tweens, "flash", self._draw)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<ButtonRelease-1>", self._up)
        T.on_accent(lambda: (self.colors.colors.update(self._target()), self._draw()))
        self._draw()

    def _target(self):
        fill, hover, fg, border = (C.get(c, c) for c in self.KINDS[self.kind])
        if not self.enabled:
            return {"fill": C["disabled_fill"], "fg": C["disabled_text"], "border": C["disabled_fill"],
                    "halo": C["bg"]}
        halo = C["accent"] if self.kind == "secondary" else fill
        if self.hover:
            fill = hover
            if self.kind == "secondary":
                border = C["border_hover"]
        return {"fill": fill, "fg": fg, "border": border if self.kind == "secondary" else fill, "halo": halo}

    def _set_hover(self, value):
        self.hover = value
        self.colors.fade(**self._target())
        self.glow.to(1.0 if value and self.enabled else 0.0, ms=220)

    def _down(self, _event):
        if self.enabled:
            self.press.to(1.0, ms=80)

    def _up(self, event):
        self.press.to(0.0, ms=280, ease=ease_back)
        if self.enabled and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.flash.v = 1.0
            self.flash.to(0.0, ms=380)
            self.command()

    def set(self, text=None, kind=None, enabled=None, breathing=None):
        changed = False
        if text is not None and text != self.text:
            self.text, changed = text, True
        if kind is not None and kind != self.kind:
            self.kind = kind
            self.font.configure(weight="bold" if kind != "secondary" else "normal")
        if enabled is not None and enabled != self.enabled:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            if not enabled:
                self.glow.to(0.0)
        if breathing is not None and breathing != self.breathing:
            self.breathing = breathing
            key = f"breathe{id(self)}"
            if breathing:
                t0 = time.perf_counter()

                def breathe(now):
                    self.breath = 0.5 - 0.5 * math.cos((now - t0) * 2.6)
                    self._draw()

                ticker(self).add(key, breathe)
            else:
                ticker(self).remove(key)
                start = self.breath
                self.tweens.run("breath", 300, lambda t: (setattr(self, "breath", start * (1 - t)), self._draw()))
        self.colors.fade(ms=260, **self._target())
        if changed:
            self._draw()

    def _draw(self):
        s, m = self.s, self.m
        bw = max(self.font.measure(self.text), self.min_w) + 40 * s
        bh = self.font.metrics("linespace") + 18 * s
        W, H = int(bw + 2 * m), int(bh + 2 * m)
        if getattr(self, "_size", None) != (W, H):
            self._size = (W, H)
            self.configure(width=W, height=H)
        self.delete("all")
        r = 9 * s
        glow = max(self.glow.v, 0.75 * self.breath if self.enabled else 0)
        if glow > 0.01:
            strength = 0.55 if self.kind == "secondary" else 1.0
            for grow, alpha in ((7, 0.10), (4.5, 0.18), (2.2, 0.30)):
                o = grow * s * glow
                rounded_rect(self, m - o, m - o, m + bw + o, m + bh + o, r + o, outline="",
                             fill=mix(C["bg"], self.colors["halo"], alpha * glow * strength))
        inset = self.press.v * 1.8 * s
        fill = mix(self.colors["fill"], "#FFFFFF", 0.28 * self.flash.v)
        rounded_rect(self, m + inset, m + inset, m + bw - inset, m + bh - inset, r,
                     fill=fill, outline=self.colors["border"])
        lift = self.glow.v * 1.2 * s - self.press.v * 0.8 * s
        self.create_text(m + bw / 2, m + bh / 2 - lift, text=self.text, fill=self.colors["fg"], font=self.font)


class Check(tk.Frame):
    """Checkbox with a hover halo, a fill-and-draw tick, and a ripple when toggled."""

    def __init__(self, parent, text, variable, command=None, scale=1.0):
        super().__init__(parent, bg=parent["bg"], cursor="hand2")
        self.var, self.command, self.s = variable, command, scale
        self.tweens = Tweens(self)
        self.value = Value(self.tweens, "value", self._draw, 1.0 if variable.get() else 0.0)
        self.hover = Value(self.tweens, "hover", self._draw)
        self.ripple = Value(self.tweens, "ripple", self._draw, 1.0)
        self.n, self.m = int(17 * scale), int(10 * scale)
        size = self.n + 2 * self.m
        self.box = tk.Canvas(self, width=size, height=size, highlightthickness=0, bd=0, bg=parent["bg"])
        self.box.pack(side="left")
        self.label = tk.Label(self, text=text, bg=parent["bg"], fg=C["text"], font=(T.FONT, 10))
        self.label.pack(side="left")
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: self._set_hover(True))
            w.bind("<Leave>", lambda e: self._set_hover(False))
        T.on_accent(self._draw)
        self._draw()

    def _set_hover(self, value):
        self.hover.to(1.0 if value else 0.0, ms=180)
        self.label.configure(fg=mix(C["text"], "#FFFFFF", 0.6) if value else C["text"])

    def _toggle(self, _event):
        self.var.set(not self.var.get())
        self.value.to(1.0 if self.var.get() else 0.0, ms=260, ease=ease_in_out)
        self.ripple.v = 0.0
        self.ripple.to(1.0, ms=520)
        if self.command:
            self.command()

    def _draw(self):
        c, n, m, s = self.box, self.n, self.m, self.s
        v, h, rp = self.value.v, self.hover.v, self.ripple.v
        c.delete("all")
        cx = cy = m + n / 2
        if h > 0.01:
            rad = n * 0.5 + 5 * s * h
            c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, outline="",
                          fill=mix(C["bg"], C["accent"], 0.16 * h))
        if rp < 1:
            rad = n * 0.45 + (m - 1) * ease_out(rp)
            c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, width=max(1, int(2 * s * (1 - rp))),
                          outline=mix(C["accent"], C["bg"], rp))
        squash = math.sin(v * math.pi) * 1.5 * s  # the box squashes a little mid-toggle
        fill = mix(C["field"], C["accent"], v)
        outline = mix(mix(C["border_hover"], C["accent"], h), C["accent"], v)
        rounded_rect(c, m + 1 + squash, m + 1 + squash, m + n - 2 - squash, m + n - 2 - squash, 4.5 * s,
                     fill=fill, outline=outline)
        if v > 0.05:
            pts = [(m + n * 0.26, m + n * 0.52), (m + n * 0.44, m + n * 0.70), (m + n * 0.76, m + n * 0.33)]
            c.create_line(*partial_path(pts, v), fill=C["ink"], width=max(2, int(2.2 * s)),
                          capstyle="round", joinstyle="round")


class Slider(tk.Canvas):
    """Track with a knob that grows on hover, a ripple on click, and a value bubble above."""

    def __init__(self, parent, from_, to, value, command, fmt=str, scale=1.0):
        self.s = scale
        super().__init__(parent, height=int(58 * scale), highlightthickness=0, bd=0,
                         bg=parent["bg"], cursor="hand2")
        self.lo, self.hi, self.value, self.command, self.fmt = from_, to, value, command, fmt
        self.hovering, self.dragging = False, False
        self.tweens = Tweens(self)
        self.shown = Value(self.tweens, "move", self._draw, value)
        self.grow = Value(self.tweens, "grow", self._draw)
        self.bubble = Value(self.tweens, "bubble", self._draw)
        self.ripple = Value(self.tweens, "ripple", self._draw, 1.0)
        self.bubble_font = tkfont.Font(family=T.FONT, size=9, weight="bold")
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: self._set(dragging=False))
        self.bind("<Enter>", lambda e: self._set(hovering=True))
        self.bind("<Leave>", lambda e: self._set(hovering=False))
        self.bind("<MouseWheel>", self._wheel)
        T.on_accent(self._draw)

    def _set(self, hovering=None, dragging=None):
        if hovering is not None:
            self.hovering = hovering
        if dragging is not None:
            self.dragging = dragging
        active = self.hovering or self.dragging
        self.grow.to(1.0 if active else 0.0, ms=180)
        self.bubble.to(1.0 if active else 0.0, ms=280 if active else 180, ease=ease_back if active else ease_out)

    def _geom(self):
        pad = 20 * self.s  # knob halo stays inside the canvas at both ends
        return pad, self.winfo_width() - pad, self.winfo_height() - 18 * self.s

    def _value_at(self, x):
        x0, x1, _ = self._geom()
        frac = clamp01((x - x0) / max(x1 - x0, 1))
        return round(self.lo + frac * (self.hi - self.lo))

    def _click(self, event):
        self._set(dragging=True)
        target = self._value_at(event.x)
        self.shown.to(target, ms=220)
        self.ripple.v = 0.0
        self.ripple.to(1.0, ms=520)
        self._commit(target)

    def _drag(self, event):
        self.tweens.cancel("move")
        target = self._value_at(event.x)
        self.shown.v = target
        self._draw()
        self._commit(target)

    def _wheel(self, event):
        target = min(max(self.value + (5 if event.delta > 0 else -5), self.lo), self.hi)
        self.shown.to(target, ms=160)
        self._commit(target)

    def _commit(self, value):
        if value != self.value:
            self.value = value
            self.command(value)

    def _draw(self):
        self.delete("all")
        s = self.s
        x0, x1, y = self._geom()
        if x1 <= x0:
            return
        x = x0 + (self.shown.v - self.lo) / (self.hi - self.lo) * (x1 - x0)
        g, b = self.grow.v, self.bubble.v
        t = (4 + 1.5 * g) * s
        self.create_line(x0, y, x1, y, fill=mix(C["track"], C["border_hover"], g * 0.6), width=t, capstyle="round")
        self.create_line(x0, y, x, y, fill=mix(C["accent"], C["accent_hover"], g), width=t, capstyle="round")
        # Tick marks every 50 wpm.
        for v in range(50, self.hi + 1, 50):
            tx = x0 + (v - self.lo) / (self.hi - self.lo) * (x1 - x0)
            self.create_line(tx, y + 8 * s, tx, y + 11 * s, fill=mix(C["bg"], C["faint"], 0.5 + 0.5 * g))
        if self.ripple.v < 1:
            rp = self.ripple.v
            rad = (8 + 8 * ease_out(rp)) * s
            self.create_oval(x - rad, y - rad, x + rad, y + rad, outline=mix(C["accent"], C["bg"], rp),
                             width=max(1, int(2 * s * (1 - rp))))
        r = (6.5 + 2.5 * g) * s
        if g > 0.01:
            halo = r + 5 * s * g
            self.create_oval(x - halo, y - halo, x + halo, y + halo, outline="",
                             fill=mix(C["bg"], C["accent"], 0.22 * g))
        self.create_oval(x - r, y - r, x + r, y + r, fill=C["text"], outline=C["accent"], width=2 * s)
        if b > 0.01:
            label = self.fmt(round(self.shown.v))
            w = self.bubble_font.measure(label) + 16 * s
            h = 20 * s
            by = y - 9 * s - 8 * s - h + (1 - b) * 8 * s
            bx = min(max(x - w / 2, 2), self.winfo_width() - w - 2)
            fill = mix(C["bg"], C["accent"], b)
            rounded_rect(self, bx, by, bx + w, by + h, 6 * s, fill=fill, outline=fill)
            self.create_polygon(x - 4 * s, by + h - 1, x + 4 * s, by + h - 1, x, by + h + 4 * s, fill=fill, outline=fill)
            self.create_text(bx + w / 2, by + h / 2, text=label, font=self.bubble_font, fill=mix(C["bg"], C["ink"], b))


class Segmented(tk.Canvas):
    """A pill of options with an indicator that slides between them."""

    def __init__(self, parent, options, value, command, scale=1.0):
        self.s, self.options, self.command = scale, options, command
        self.font = tkfont.Font(family=T.FONT, size=9, weight="bold")
        self.seg_w = max(self.font.measure(o) for o in options) + 26 * scale
        self.m = 4 * scale
        w = int(self.seg_w * len(options) + 2 * self.m)
        h = int(30 * scale)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.w, self.h = w, h
        self.index = options.index(value)
        self.tweens = Tweens(self)
        self.pos = Value(self.tweens, "pos", self._draw, float(self.index))
        self.hover_i = None
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._hover(None))
        T.on_accent(self._draw)
        self._draw()

    def _at(self, x):
        return int(min(max((x - self.m) // self.seg_w, 0), len(self.options) - 1))

    def _motion(self, e):
        self._hover(self._at(e.x))

    def _hover(self, i):
        if i != self.hover_i:
            self.hover_i = i
            self._draw()

    def _click(self, e):
        i = self._at(e.x)
        if i != self.index:
            self.index = i
            self.pos.to(float(i), ms=320, ease=ease_back)
            self.command(self.options[i])

    def _draw(self):
        self.delete("all")
        s, m, sw = self.s, self.m, self.seg_w
        rounded_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=C["field"], outline=C["border"])
        x = m + self.pos.v * sw
        rounded_rect(self, x, m, x + sw, self.h - m, (self.h - 2 * m) / 2, fill=C["accent"], outline=C["accent"])
        for i, opt in enumerate(self.options):
            cx = m + (i + 0.5) * sw
            near = clamp01(1 - abs(self.pos.v - i))
            base = C["text"] if self.hover_i == i else C["muted"]
            self.create_text(cx, self.h / 2, text=opt, font=self.font, fill=mix(base, C["ink"], near))


class Swatches(tk.Canvas):
    """Accent color dots; the chosen one wears a ring, hovered ones grow."""

    def __init__(self, parent, colors, value, command, scale=1.0):
        self.s, self.colors, self.command = scale, colors, command
        self.d, self.gap, self.m = 14 * scale, 10 * scale, 6 * scale
        w = int(len(colors) * self.d + (len(colors) - 1) * self.gap + 2 * self.m)
        h = int(self.d + 2 * self.m)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.h = h
        self.index = [c for _, c in colors].index(value)
        self.tweens = Tweens(self)
        self.grow = [Value(self.tweens, f"g{i}", self._draw) for i in range(len(colors))]
        self.ring = Value(self.tweens, "ring", self._draw, float(self.index))
        self.hover_i = None
        self.aqua = self.tk.call("tk", "windowingsystem") == "aqua"
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda e: self._hover(self._at(e.x)))
        self.bind("<Leave>", lambda e: self._hover(None))
        self._draw()

    def _cx(self, i):
        return self.m + i * (self.d + self.gap) + self.d / 2

    def _at(self, x):
        for i in range(len(self.colors)):
            if abs(x - self._cx(i)) <= (self.d + self.gap) / 2:
                return i
        return None

    def _hover(self, i):
        if i != self.hover_i:
            if self.hover_i is not None:
                self.grow[self.hover_i].to(0.0, ms=160)
            if i is not None:
                self.grow[i].to(1.0, ms=220, ease=ease_back)
            self.hover_i = i

    def _click(self, e):
        i = self._at(e.x)
        if i is not None and i != self.index:
            self.index = i
            self.ring.to(float(i), ms=360, ease=ease_back)
            self.command(self.colors[i][1])

    def _draw(self):
        self.delete("all")
        # Tk on macOS snaps ovals to whole points, leaves out a filled oval's right and bottom edge,
        # and strokes a 1pt outline half a point down-right. Unless everything sits on whole points
        # and fills get that edge back, the dot lands off-center inside its ring.
        snap = (lambda v: int(v + 0.5)) if self.aqua else (lambda v: v)
        pad = 1 if self.aqua else 0
        cy = snap(self.h / 2)
        for i, (_, col) in enumerate(self.colors):
            r = snap(self.d / 2 + self.grow[i].v * 2 * self.s)
            cx = snap(self._cx(i))
            self.create_oval(cx - r, cy - r, cx + r + pad, cy + r + pad, fill=col, outline="")
        rx = snap(self._cx(0) + self.ring.v * (self.d + self.gap))
        r = snap(self.d / 2 + 3.5 * self.s)
        self.create_oval(rx - r, cy - r, rx + r, cy + r, outline=C["text"], width=max(1, int(1.5 * self.s)))


class Progress(tk.Canvas):
    """A divider line that doubles as a progress bar, with a shimmer while working."""

    def __init__(self, parent, scale=1.0):
        self.s = scale
        super().__init__(parent, height=max(4, int(4 * scale)), highlightthickness=0, bd=0, bg=parent["bg"])
        self.color_key, self.tweens, self.shimmer = "accent", Tweens(self), None
        self.value = Value(self.tweens, "value", self._draw)
        self.bind("<Configure>", lambda e: self._draw())
        T.on_accent(self._draw)

    def to(self, value, ms=320, ease=ease_out, color=None):
        if color:
            self.color_key = color
        self.value.to(value, ms=ms, ease=ease)
        self._draw()

    def set_shimmer(self, on):
        key = f"shimmer{id(self)}"
        if on:
            t0 = time.perf_counter()

            def tick(now):
                self.shimmer = ((now - t0) * 0.55) % 1.3 - 0.15
                self._draw()

            ticker(self).add(key, tick)
        else:
            ticker(self).remove(key)
            self.shimmer = None
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self["height"])
        color = C[self.color_key]
        rounded_rect(self, 0, 0, w, h, h / 2, fill=C["border"], outline="")
        filled = w * self.value.v
        if filled > 1:
            rounded_rect(self, 0, 0, filled, h, h / 2, fill=color, outline="")
            if self.shimmer is not None:
                band = 80 * self.s
                cx = self.shimmer * filled
                for i in range(8):
                    f = 1 - abs(i - 3.5) / 4
                    x = cx - band / 2 + i * band / 8
                    x2 = min(x + band / 8, filled - 1)
                    if x2 > max(x, 1):
                        self.create_rectangle(max(x, 1), 0, x2, h, outline="", fill=mix(color, "#FFFFFF", 0.5 * f))


class Pulse(tk.Canvas):
    """A dot that breathes, with a soft ring that radiates outward."""

    def __init__(self, parent, scale=1.0):
        self.s = scale
        n = self.n = int(16 * scale)
        super().__init__(parent, width=n, height=n, highlightthickness=0, bd=0, bg=parent["bg"])
        self.color_key, self.running = "accent", False

    def start(self, color_key="accent"):
        self.color_key = color_key
        if not self.running:
            self.running = True
            t0 = time.perf_counter()
            ticker(self).add(f"pulse{id(self)}", lambda now: self._frame(now - t0))

    def stop(self):
        self.running = False
        ticker(self).remove(f"pulse{id(self)}")
        self.delete("all")

    def _frame(self, e):
        n, s = self.n, self.s
        color = C[self.color_key]
        self.delete("all")
        c = n / 2
        ring = (e * 0.9) % 1.0
        rad = 3 * s + ring * (n / 2 - 3.5 * s)
        self.create_oval(c - rad, c - rad, c + rad, c + rad, outline=mix(color, C["bg"], ring), width=1)
        phase = (math.sin(e * 5) + 1) / 2
        rad = (2.6 + 0.8 * phase) * s
        self.create_oval(c - rad, c - rad, c + rad, c + rad, outline="", fill=mix(C["bg"], color, 0.55 + 0.45 * phase))


class Title(tk.Canvas):
    """The app name with a blinking caret; letters ride a wave when hovered."""

    def __init__(self, parent, text, scale=1.0):
        self.s, self.text = scale, text
        self.font = tkfont.Font(family=T.TITLE_FONT, size=20)
        self.widths = [self.font.measure(ch) for ch in text]
        self.pad_top = 10 * scale  # headroom for the wave
        w = int(sum(self.widths) + 20 * scale)
        h = int(self.font.metrics("linespace") + self.pad_top + 6 * scale)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=parent["bg"])
        self.tweens = Tweens(self)
        self.wave = Value(self.tweens, "wave", self._draw, 1.0)
        self.caret = 1.0
        self.items = []
        base = self.pad_top + self.font.metrics("ascent")
        x = 0
        for ch, cw in zip(text, self.widths):
            self.items.append(self.create_text(x, base, text=ch, font=self.font, fill=C["text"], anchor="sw"))
            x += cw
        lh = self.font.metrics("linespace")
        cx = x + 5 * scale
        self.base = base
        self.caret_item = self.create_line(cx, base - lh * 0.78, cx, base - 2 * scale, width=max(2, int(2.5 * scale)),
                                           fill=C["accent"])
        self.bind("<Enter>", lambda e: self.do_wave())
        self.bind("<Button-1>", lambda e: self.do_wave())
        t0 = time.perf_counter()
        ticker(self).add(f"caret{id(self)}", lambda now: self._blink(now - t0))
        T.on_accent(self._draw)

    def do_wave(self):
        if self.wave.v >= 1:
            self.wave.v = 0.0
            self.wave.to(1.0, ms=950, ease=linear)

    def _blink(self, e):
        self.caret = (math.cos(e * 3.6) + 1) / 2
        self.itemconfigure(self.caret_item, fill=mix(C["bg"], C["accent"], self.caret))

    def _draw(self):
        n = len(self.text)
        x = 0
        for i, (item, cw) in enumerate(zip(self.items, self.widths)):
            p = self.wave.v * (1 + 0.08 * (n - 1)) - i * 0.08  # the last letter lands as the wave ends
            lift = math.sin(clamp01(p) * math.pi) * 6 * self.s if 0 < p < 1 else 0
            self.coords(item, x, self.base - lift)
            self.itemconfigure(item, fill=mix(C["text"], C["accent"], lift / (6 * self.s)))
            x += cw


class KeyStrip(tk.Canvas):
    """A little keyboard that lights up each key as it's typed. Slides open while typing."""

    ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]

    def __init__(self, parent, scale=1.0):
        self.s = scale
        super().__init__(parent, height=1, highlightthickness=0, bd=0, bg=parent["bg"])
        self.full_h = int(112 * scale)
        self.tweens = Tweens(self)
        self.open = Value(self.tweens, "open", self._resize)
        self.heat = {}
        self.keys = {}
        self.font = tkfont.Font(family=T.FONT, size=8, weight="bold")
        self.bind("<Configure>", lambda e: self._build())
        T.on_accent(self._paint)

    def show(self, on):
        self.open.to(1.0 if on else 0.0, ms=380, ease=ease_in_out)
        key = f"keys{id(self)}"
        if on:
            ticker(self).add(key, self._cool)
        else:
            ticker(self).remove(key)

    def _resize(self):
        self.configure(height=max(1, int(self.full_h * self.open.v)))

    def _build(self):
        self.delete("all")
        self.keys.clear()
        s = self.s
        kw, gap = 26 * s, 4 * s
        top = 10 * s
        width = self.winfo_width()
        rows = self.ROWS + [" "]
        for r, row in enumerate(rows):
            if row == " ":
                w = kw * 6 + gap * 5
                x0 = (width - w) / 2
                y0 = top + r * (kw * 0.8 + gap)
                self._key(" ", x0, y0, w, kw * 0.8)
                continue
            total = len(row) * kw + (len(row) - 1) * gap
            x0 = (width - total) / 2 + r * kw * 0.25
            for i, ch in enumerate(row):
                self._key(ch, x0 + i * (kw + gap), top + r * (kw * 0.8 + gap), kw, kw * 0.8)
        self._paint()

    def _key(self, ch, x, y, w, h):
        body = rounded_rect(self, x, y, x + w, y + h, 5 * self.s, fill=C["raised"], outline=C["border"])
        label = self.create_text(x + w / 2, y + h / 2, text=ch.upper() if ch != " " else "", font=self.font,
                                 fill=C["faint"])
        self.keys[ch] = (body, label, y)

    def press(self, ch):
        ch = (ch or "").lower()
        if ch in ("\n", "\t"):
            ch = " "
        if ch in self.keys:
            self.heat[ch] = 1.0

    def _cool(self, now):
        if not self.heat:
            return
        for ch in list(self.heat):
            self.heat[ch] -= 0.06
            if self.heat[ch] <= 0:
                del self.heat[ch]
        self._paint()

    def _paint(self):
        for ch, (body, label, y) in self.keys.items():
            h = self.heat.get(ch, 0.0)
            self.itemconfigure(body, fill=mix(C["raised"], C["accent"], h), outline=mix(C["border"], C["accent_hover"], h))
            self.itemconfigure(label, fill=mix(C["faint"], C["ink"], h))
