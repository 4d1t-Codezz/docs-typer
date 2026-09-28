"""Windows backend: SendInput for typing, low-level hooks to notice the user, Win32 clipboard."""

import ctypes
import math
import re
import threading
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Windows input: SendInput, low-level hooks, foreground window
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
MAGIC = 0x0D0C5717  # tags our own synthetic input so the watcher ignores it

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_RETURN, VK_TAB, VK_BACK = 0x0D, 0x09, 0x08
MOD_VK = {"ctrl": VK_CONTROL, "alt": VK_MENU, "shift": VK_SHIFT}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _key_input(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=MAGIC)
    return inp


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _vk(vk, up=False):
    return _key_input(vk=vk, scan=user32.MapVirtualKeyW(vk, 0), flags=KEYEVENTF_KEYUP if up else 0)


def type_char(ch):
    units = ch.encode("utf-16-le")
    inputs = []
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i:i + 2], "little")
        inputs.append(_key_input(scan=code, flags=KEYEVENTF_UNICODE))
        inputs.append(_key_input(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    _send(inputs)


def press(vk, mods=()):
    downs = [_vk(MOD_VK[m]) for m in mods]
    ups = [_vk(MOD_VK[m], up=True) for m in reversed(mods)]
    _send(downs + [_vk(vk), _vk(vk, up=True)] + ups)


def foreground():
    return user32.GetForegroundWindow() or 0


class InputWatcher:
    """Calls on_user_input(reason) on the first real key, click, scroll or mouse move."""

    MOUSE_TRAVEL = 24  # pixels of movement allowed before we treat it as "hands on"

    def __init__(self, on_user_input):
        self.on_user_input = on_user_input
        self.thread = None
        self.thread_id = None
        self.armed = False

    def start(self):
        self.armed = True
        self.travel = 0.0
        self.last_pt = None
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self.thread.start()
        ready.wait(2)

    def stop(self):
        self.armed = False
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
        self.thread_id = None

    def _fire(self, reason):
        if self.armed:
            self.armed = False
            self.on_user_input(reason)

    def _run(self, ready):
        self.thread_id = kernel32.GetCurrentThreadId()

        def kb(code, wparam, lparam):
            if code == 0 and wparam in (0x100, 0x104):  # WM_KEYDOWN, WM_SYSKEYDOWN
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.dwExtraInfo != MAGIC:
                    self._fire("you pressed a key")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def mouse(code, wparam, lparam):
            if code == 0:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if info.dwExtraInfo != MAGIC:
                    if wparam == 0x200:  # WM_MOUSEMOVE
                        pt = (info.pt.x, info.pt.y)
                        if self.last_pt is not None:
                            self.travel += math.hypot(pt[0] - self.last_pt[0], pt[1] - self.last_pt[1])
                        self.last_pt = pt
                        if self.travel > self.MOUSE_TRAVEL:
                            self._fire("you moved the mouse")
                    elif wparam in (0x20A, 0x20E):
                        self._fire("you scrolled")
                    elif wparam in (0x201, 0x204, 0x207, 0x20B):
                        self._fire("you clicked")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        # Keep references alive for the lifetime of the hooks.
        self._kb_proc, self._mouse_proc = HOOKPROC(kb), HOOKPROC(mouse)
        hmod = kernel32.GetModuleHandleW(None)
        hooks = [user32.SetWindowsHookExW(13, self._kb_proc, hmod, 0),  # WH_KEYBOARD_LL
                 user32.SetWindowsHookExW(14, self._mouse_proc, hmod, 0)]  # WH_MOUSE_LL
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        for h in hooks:
            if h:
                user32.UnhookWindowsHookEx(h)


# ---------------------------------------------------------------------------
# Clipboard (rich paste)
# ---------------------------------------------------------------------------

user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
CF_HTML = user32.RegisterClipboardFormatW("HTML Format")


def clipboard_html():
    if not user32.IsClipboardFormatAvailable(CF_HTML) or not user32.OpenClipboard(None):
        return None
    try:
        h = user32.GetClipboardData(CF_HTML)
        if not h:
            return None
        ptr = kernel32.GlobalLock(h)
        try:
            raw = ctypes.string_at(ptr, kernel32.GlobalSize(h))
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()
    raw = raw.split(b"\0", 1)[0]
    s = re.search(rb"StartFragment:(\d+)", raw)
    e = re.search(rb"EndFragment:(\d+)", raw)
    frag = raw[int(s.group(1)):int(e.group(1))] if s and e else raw
    return frag.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

# Google Docs keyboard shortcuts on Windows.
SHORTCUTS = {
    "bold": (("ctrl",), 0x42), "italic": (("ctrl",), 0x49), "underline": (("ctrl",), 0x55),
    "strike": (("alt", "shift"), 0x35), "superscript": (("ctrl",), 0xBE), "subscript": (("ctrl",), 0xBC),
    "bullet": (("ctrl", "shift"), 0x38), "numbered": (("ctrl", "shift"), 0x37),
    "align_left": (("ctrl", "shift"), 0x4C), "align_center": (("ctrl", "shift"), 0x45),
    "align_right": (("ctrl", "shift"), 0x52), "align_justify": (("ctrl", "shift"), 0x4A),
    "outdent": (("shift",), VK_TAB),
    **{f"heading{n}": (("ctrl", "alt"), 0x30 + n) for n in range(7)},
}


class Backend:
    name = "windows"
    mod_label = "Ctrl"  # shown in the UI
    accel = "Control"  # Tk event modifier for app shortcuts
    ui_font = "Segoe UI"
    title_font = "Georgia"
    mono_font = "Consolas"
    InputWatcher = InputWatcher
    shortcuts = SHORTCUTS

    def setup_process(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    def scale(self, root):
        return root.winfo_fpixels("1i") / 96

    def style_window(self, root, bg, fg):
        """Dark title bar on Windows 10/11 so the frame matches the app."""
        try:
            root.update_idletasks()
            hwnd = int(root.wm_frame(), 16)
            dwm = ctypes.windll.dwmapi

            def colorref(hex_color):
                h = hex_color.lstrip("#")
                r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
                return ctypes.c_int(b << 16 | g << 8 | r)

            on = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)  # immersive dark mode
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref(bg)), 4)  # caption color
            dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(colorref(fg)), 4)  # caption text
        except (AttributeError, OSError, ValueError):
            pass

    def set_icon(self, root, assets):
        import os
        ico = os.path.join(assets, "DocsTyper.ico")
        if os.path.exists(ico):
            root.iconbitmap(default=ico)

    # -- typing
    def type_char(self, ch):
        type_char(ch)

    def press_enter(self, shift=False):
        press(VK_RETURN, ("shift",) if shift else ())

    def press_tab(self):
        press(VK_TAB)

    def press_backspace(self):
        press(VK_BACK)

    def shortcut(self, action):
        mods, vk = SHORTCUTS[action]
        press(vk, mods)

    # -- focus
    def foreground(self):
        return foreground()

    def is_own(self, token, root):
        own = int(root.wm_frame(), 16)
        return not token or token in (own, user32.GetAncestor(root.winfo_id(), 2))

    # -- permissions (none needed on Windows)
    def permission_problem(self):
        return None

    def open_permission_settings(self, which=None):
        pass

    def clipboard_html(self):
        try:
            return clipboard_html()
        except OSError:
            return None
