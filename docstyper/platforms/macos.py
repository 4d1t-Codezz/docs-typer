"""macOS backend: Quartz events for typing, an event tap to notice the user, NSPasteboard.

Uses only ctypes and system frameworks, like the original Swift app: CGEventPost to
type (needs Accessibility access) and a listen-only CGEventTap to stop on any user
input (needs Input Monitoring access).
"""

import ctypes
import ctypes.util
import math
import os
import subprocess
import threading

_cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_objc = ctypes.CDLL(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")  # registers NSWorkspace, NSPasteboard

MAGIC = 0x0D0C5717  # tags our own synthetic events so the watcher ignores them
kCGEventSourceUserData = 42
kCGHIDEventTap = 0
kCGSessionEventTap = 1
kCGHeadInsertEventTap = 0
kCGEventTapOptionListenOnly = 1
kCGEventSourceStatePrivate = -1

FLAG_SHIFT, FLAG_CONTROL, FLAG_OPTION, FLAG_COMMAND = 0x20000, 0x40000, 0x80000, 0x100000
MOD_FLAGS = {"shift": FLAG_SHIFT, "ctrl": FLAG_CONTROL, "option": FLAG_OPTION, "cmd": FLAG_COMMAND}

# ANSI virtual key codes.
KC = {"a": 0, "b": 11, "e": 14, "i": 34, "j": 38, "l": 37, "r": 15, "u": 32, "x": 7,
      "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28,
      ".": 47, ",": 43, "return": 36, "tab": 48}


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


TAPCALLBACK = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)

_cg.CGEventSourceCreate.argtypes = [ctypes.c_int32]
_cg.CGEventSourceCreate.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
_cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
_cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
_cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
_cg.CGEventGetLocation.restype = CGPoint
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CGEventTapCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64,
                                 TAPCALLBACK, ctypes.c_void_p]
_cg.CGEventTapCreate.restype = ctypes.c_void_p
_cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
_cg.CGPreflightListenEventAccess.restype = ctypes.c_bool
_cg.CGRequestListenEventAccess.restype = ctypes.c_bool
_cg.AXIsProcessTrusted.restype = ctypes.c_bool
_cg.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
_cg.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool

_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
_cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
_cf.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
_cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
_cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_cf.CFRunLoopRun.restype = None
_cf.CFRunLoopStop.argtypes = [ctypes.c_void_p]
_cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
_cf.CFDictionaryCreate.restype = ctypes.c_void_p
kCFRunLoopCommonModes = ctypes.c_void_p.in_dll(_cf, "kCFRunLoopCommonModes").value
kCFBooleanTrue = ctypes.c_void_p.in_dll(_cf, "kCFBooleanTrue").value
kAXTrustedCheckOptionPrompt = ctypes.c_void_p.in_dll(_cg, "kAXTrustedCheckOptionPrompt").value

_objc.objc_getClass.argtypes = [ctypes.c_char_p]
_objc.objc_getClass.restype = ctypes.c_void_p
_objc.sel_registerName.argtypes = [ctypes.c_char_p]
_objc.sel_registerName.restype = ctypes.c_void_p
_MSG = ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value


def _send(restype, obj, selector, *args, argtypes=()):
    """objc_msgSend with an explicit signature (required on Apple Silicon)."""
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(_MSG)
    return fn(obj, _objc.sel_registerName(selector.encode()), *args)


def _cls(name):
    return _objc.objc_getClass(name.encode())


def _nsstring(s):
    return _send(ctypes.c_void_p, _cls("NSString"), "stringWithUTF8String:", s.encode(), argtypes=(ctypes.c_char_p,))


def _pystring(ns):
    if not ns:
        return None
    raw = _send(ctypes.c_char_p, ns, "UTF8String")
    return raw.decode("utf-8", errors="replace") if raw else None


_source = _cg.CGEventSourceCreate(kCGEventSourceStatePrivate)


def _post_key(keycode, flags=0, text=None):
    for down in (True, False):
        ev = _cg.CGEventCreateKeyboardEvent(_source, keycode, down)
        if text is not None:
            units = text.encode("utf-16-le")
            arr = (ctypes.c_uint16 * (len(units) // 2)).from_buffer_copy(units)
            _cg.CGEventKeyboardSetUnicodeString(ev, len(arr), arr)
        _cg.CGEventSetFlags(ev, flags)
        _cg.CGEventSetIntegerValueField(ev, kCGEventSourceUserData, MAGIC)
        _cg.CGEventPost(kCGHIDEventTap, ev)
        _cf.CFRelease(ev)


def type_char(ch):
    _post_key(0, 0, ch)


def frontmost_pid():
    ws = _send(ctypes.c_void_p, _cls("NSWorkspace"), "sharedWorkspace")
    app = _send(ctypes.c_void_p, ws, "frontmostApplication")
    return _send(ctypes.c_int, app, "processIdentifier") if app else 0


# Event types we watch.
KEY_DOWN, FLAGS_CHANGED = 10, 12
MOUSE_DOWN = (1, 3, 25)
MOUSE_MOVE = (5, 6, 7, 27)
SCROLL = 22
TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)


class InputWatcher:
    """Calls on_user_input(reason) on the first real key, click, scroll or mouse move."""

    MOUSE_TRAVEL = 24

    def __init__(self, on_user_input):
        self.on_user_input = on_user_input
        self.armed = False
        self.loop = None
        self.tap = None
        self.failed = False

    def start(self):
        self.armed = True
        self.travel = 0.0
        self.last_pt = None
        self.failed = False
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True).start()
        ready.wait(2)
        return not self.failed

    def stop(self):
        self.armed = False
        if self.tap:
            _cg.CGEventTapEnable(self.tap, False)
        if self.loop:
            _cf.CFRunLoopStop(self.loop)
        self.loop = None

    def _fire(self, reason):
        if self.armed:
            self.armed = False
            self.on_user_input(reason)

    def _run(self, ready):
        def callback(proxy, etype, event, user):
            if etype in TAP_DISABLED:
                if self.tap:
                    _cg.CGEventTapEnable(self.tap, True)
                return event
            if _cg.CGEventGetIntegerValueField(event, kCGEventSourceUserData) == MAGIC:
                return event
            if etype in (KEY_DOWN, FLAGS_CHANGED):
                self._fire("you pressed a key")
            elif etype in MOUSE_DOWN:
                self._fire("you clicked")
            elif etype == SCROLL:
                self._fire("you scrolled")
            elif etype in MOUSE_MOVE:
                p = _cg.CGEventGetLocation(event)
                if self.last_pt is not None:
                    self.travel += math.hypot(p.x - self.last_pt[0], p.y - self.last_pt[1])
                self.last_pt = (p.x, p.y)
                if self.travel > self.MOUSE_TRAVEL:
                    self._fire("you moved the mouse")
            return event

        self._callback = TAPCALLBACK(callback)  # keep a reference
        mask = 0
        for t in (KEY_DOWN, FLAGS_CHANGED, SCROLL) + MOUSE_DOWN + MOUSE_MOVE:
            mask |= 1 << t
        tap = _cg.CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly,
                                   mask, self._callback, None)
        if not tap:
            self.failed = True  # no Input Monitoring permission
            ready.set()
            return
        self.tap = tap
        src = _cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        self.loop = _cf.CFRunLoopGetCurrent()
        _cf.CFRunLoopAddSource(self.loop, src, kCFRunLoopCommonModes)
        _cg.CGEventTapEnable(tap, True)
        ready.set()
        _cf.CFRunLoopRun()
        _cf.CFMachPortInvalidate(tap)
        _cf.CFRelease(src)
        _cf.CFRelease(tap)
        self.tap = None


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

def _k(key, *mods):
    return tuple(mods), KC[key]


# Google Docs keyboard shortcuts on macOS.
SHORTCUTS = {
    "bold": _k("b", "cmd"), "italic": _k("i", "cmd"), "underline": _k("u", "cmd"),
    "strike": _k("x", "cmd", "shift"), "superscript": _k(".", "cmd"), "subscript": _k(",", "cmd"),
    "bullet": _k("8", "cmd", "shift"), "numbered": _k("7", "cmd", "shift"),
    "align_left": _k("l", "cmd", "shift"), "align_center": _k("e", "cmd", "shift"),
    "align_right": _k("r", "cmd", "shift"), "align_justify": _k("j", "cmd", "shift"),
    "outdent": _k("tab", "shift"),
    **{f"heading{n}": _k(str(n), "cmd", "option") for n in range(7)},
}

SETTINGS_URLS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}


class Backend:
    name = "macos"
    mod_label = "⌘"
    accel = "Command"
    ui_font = "Helvetica Neue"
    title_font = "Georgia"
    mono_font = "Menlo"
    InputWatcher = InputWatcher
    shortcuts = SHORTCUTS

    def setup_process(self):
        pass

    def scale(self, root):
        return 1.0  # Tk on macOS already works in points

    def style_window(self, root, bg, fg):
        try:
            root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", root._w, "darkaqua")
        except Exception:  # noqa: BLE001 - older Tk versions lack this
            pass

    def set_icon(self, root, assets):
        pass  # the .app bundle carries the icon

    # -- typing
    def type_char(self, ch):
        type_char(ch)

    def press_enter(self, shift=False):
        _post_key(KC["return"], FLAG_SHIFT if shift else 0)

    def press_tab(self):
        _post_key(KC["tab"])

    def shortcut(self, action):
        mods, keycode = SHORTCUTS[action]
        flags = 0
        for m in mods:
            flags |= MOD_FLAGS[m]
        _post_key(keycode, flags)

    # -- focus
    def foreground(self):
        return frontmost_pid()

    def is_own(self, token, root):
        return not token or token == os.getpid()

    # -- permissions
    def permission_problem(self):
        """Returns (message, which) if typing can't work yet, prompting macOS to ask the user."""
        if not _cg.AXIsProcessTrusted():
            keys = (ctypes.c_void_p * 1)(kAXTrustedCheckOptionPrompt)
            vals = (ctypes.c_void_p * 1)(kCFBooleanTrue)
            opts = _cf.CFDictionaryCreate(None, keys, vals, 1, None, None)
            _cg.AXIsProcessTrustedWithOptions(opts)
            _cf.CFRelease(opts)
            return ("Docs Typer needs Accessibility access to type. Allow it in System Settings → "
                    "Privacy & Security → Accessibility, then press Start again.", "accessibility")
        if not _cg.CGPreflightListenEventAccess():
            _cg.CGRequestListenEventAccess()
            return ("Docs Typer needs Input Monitoring access so it can stop when you touch anything. "
                    "Allow it in System Settings → Privacy & Security → Input Monitoring, then press "
                    "Start again.", "input")
        return None

    def open_permission_settings(self, which=None):
        url = SETTINGS_URLS.get(which or "accessibility")
        subprocess.Popen(["open", url])

    def clipboard_html(self):
        pb = _send(ctypes.c_void_p, _cls("NSPasteboard"), "generalPasteboard")
        ns = _send(ctypes.c_void_p, pb, "stringForType:", _nsstring("public.html"), argtypes=(ctypes.c_void_p,))
        return _pystring(ns)
