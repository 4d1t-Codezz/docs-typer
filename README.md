# Docs Typer

Types a document into Google Docs one keystroke at a time, with formatting. Paste text or open a
file, press **Start**, click into your Google Doc before the countdown ends, and keep your hands
off the keyboard and mouse. Touching anything stops it, and **Resume** picks up where it left off.

Works the same on **Windows** and **macOS**. The file readers, the typing plan and the whole UI are
shared, and only the part that sends keystrokes is platform-specific.

<p align="center">
  <img src="docs/screenshots/intro.png" width="30%" alt="Intro: Tappy types the app's name">
  <img src="docs/screenshots/main.png" width="30%" alt="Main window with a document loaded">
  <img src="docs/screenshots/typing.png" width="30%" alt="Typing, with the live key strip">
</p>

## Features

- **Opens** `.docx`, `.rtf`, `.odt`, `.html` and `.txt` files. You can also paste rich text straight
  from Google Docs or Word.
- **Keeps formatting:** bold, italic, underline, strikethrough, superscript and subscript,
  headings 1–6, bullet and numbered lists with nesting, and alignment. These are recreated with
  Google Docs' own keyboard shortcuts (Ctrl-based on Windows, ⌘-based on Mac).
- **Speed from 10 to 200 wpm**, with an optional *vary pace* mode that adds natural pauses.
- **Hands-off safety:** any real key, click, scroll or mouse movement stops typing, and so does
  switching to another app.
- **Live view:** the text in the window lights up as it's typed, a key strip shows each key, and
  the status shows live speed and an estimated finish time.
- **Tappy**, a pixel critter who types along, follows your mouse with its eyes, reacts when you
  stop it and celebrates when it's done.
- A choice of 3, 5 or 10 second countdown, five accent colors, and remembered settings.

## Install

You need **Python 3.10+ with Tk 8.6**. The installers from
[python.org](https://www.python.org/downloads/) include it. No other packages are needed.

### Windows

1. Install Python from python.org and tick **Add python.exe to PATH**.
2. Download or clone this repo.
3. Double-click `windows\Docs Typer.bat`.
   - For Start menu and desktop shortcuts, run
     `powershell -ExecutionPolicy Bypass -File windows\install-shortcuts.ps1`.
     Then search Start for **Docs Typer**, right-click it and choose **Pin to taskbar**.

### macOS

1. Install Python from python.org. The Python that ships with macOS has an old Tk, so don't use it.
2. Download or clone this repo.
3. Build the app: `./mac/build-app.sh`. Then drag `dist/Docs Typer.app` to Applications.
   - Or run it straight from the repo: double-click `mac/Docs Typer.command`.
4. The first time you press Start, macOS asks for two permissions, the same ones the original
   Swift app needed:
   - **Accessibility**, so it can type.
   - **Input Monitoring**, so it can stop when you touch anything.

   Allow both in **System Settings → Privacy & Security**, then press Start again. If you run it
   from Terminal, the permission goes to Terminal instead.

## Using it

1. Paste text into the box (Ctrl/⌘+V), or **Open file…** (Ctrl/⌘+O).
2. Press **Start** (Ctrl/⌘+Enter).
3. Click into your Google Doc where the text should go, before the countdown ends.
4. Hands off. If it stops, put your cursor back where it left off and press **Resume**.

Tips:
- Google Docs turns lines starting with `- ` or `1. ` into lists automatically. You can turn that
  off under **Tools → Preferences → Automatically detect lists**.
- To paste without formatting, use Ctrl/⌘+Shift+V.

## How it works

```
docstyper/
  readers.py      .docx / .odt / .html / .rtf / .txt  →  paragraphs with formatting
  keystrokes.py   paragraphs → a platform-neutral plan of keystrokes and named actions
                  ("bold", "heading2", "bullet", ...), plus the Typer that plays it
  platforms/
    windows.py    SendInput, low-level keyboard/mouse hooks, Win32 clipboard
    macos.py      Quartz CGEventPost, a listen-only CGEventTap, NSPasteboard (via ctypes)
  ui.py           the window; widgets.py, mascot.py, intro.py and motion.py do the animation
```

Each backend maps the named actions to that platform's Google Docs shortcuts. The keystrokes it
sends are tagged, so the input watcher can ignore them and only react to you.

## Tests

```
python -m unittest discover -s tests -t . -v
```

The tests cover the file readers, the keystroke plan, the typing loop (with a fake backend), and
each platform's shortcut table. They also include a UI smoke test that plays the intro and every
animation without sending any input. GitHub Actions runs them on Windows and macOS.
