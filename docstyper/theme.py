"""Colors, fonts and the live accent color."""

from .motion import mix

# Warm dark palette.
C = {
    "bg": "#262624", "field": "#1F1E1D", "raised": "#30302E", "raised_hover": "#3A3A37",
    "border": "#3D3C38", "border_hover": "#55534E", "text": "#ECEAE3", "muted": "#A5A299",
    "faint": "#6E6B64", "danger": "#C9544E", "danger_hover": "#D86A64", "warn": "#E2A55C",
    "ok": "#8DBF7F", "track": "#3A3936", "disabled_fill": "#34332F", "disabled_text": "#6E6B64",
    "ink": "#141413",
}

ACCENTS = [("Clay", "#D97757"), ("Sky", "#5FA8E8"), ("Sage", "#7DB88A"), ("Lilac", "#A98BE0"),
           ("Gold", "#E2B04F")]
CONFETTI = ("#D97757", "#E2A55C", "#8DBF7F", "#ECEAE3", "#5FA8E8", "#A98BE0")

FONT = "Segoe UI"
TITLE_FONT = "Georgia"
MONO_FONT = "Consolas"

_listeners = []


def configure_fonts(backend):
    global FONT, TITLE_FONT, MONO_FONT
    FONT, TITLE_FONT, MONO_FONT = backend.ui_font, backend.title_font, backend.mono_font


def set_accent(color, notify=True):
    C["accent"] = color
    C["accent_hover"] = mix(color, "#FFFFFF", 0.16)
    C["accent_dark"] = mix(color, "#000000", 0.25)
    C["select"] = mix(C["field"], color, 0.35)
    if notify:
        for fn in list(_listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001 - a destroyed widget shouldn't break the others
                _listeners.remove(fn)


def on_accent(fn):
    _listeners.append(fn)


set_accent(ACCENTS[0][1], notify=False)
