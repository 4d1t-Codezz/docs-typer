#!/bin/bash
# Builds "dist/Docs Typer.app", a double-clickable app that bundles the code and runs it with
# the Python you build it with. Most people should double-click "Install on Mac.command" instead,
# which runs this and puts the app in Applications.
# Usage:  ./scripts/build-mac-app.sh  [path/to/python3]
# Exits with status 2 when no suitable Python is found.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
# A usable Python is 3.10+ with Tk 8.6+, a working XML parser (needed for .docx/.odt) and a shared
# library for the app's launcher to load. Homebrew's Python can fail the XML check on some macOS
# versions (pyexpat links the system libexpat), and pyenv builds often have no shared library.
LIBPY_EXPR='os.path.join(s.get_config_var("PYTHONFRAMEWORKPREFIX") or s.get_config_var("LIBDIR"), s.get_config_var("LDLIBRARY"))'
CHECK="import os, sys, sysconfig as s, tkinter, pyexpat; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6 and os.path.isfile($LIBPY_EXPR); print(sys.executable)"

if [ $# -ge 1 ]; then
  if ! PY="$("$1" -c "$CHECK" 2>/dev/null)"; then
    echo "The Python at $1 needs to be 3.10+ with Tk 8.6+, pyexpat and a shared library." >&2
    exit 1
  fi
else
  PY=""
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  for c in \
      "$("$UV" python find '>=3.10' 2>/dev/null || true)" \
      /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
      python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] || continue
    if PY="$("$c" -c "$CHECK" 2>/dev/null)"; then break; fi
    PY=""
  done
  if [ -z "$PY" ]; then
    echo "No suitable Python found (needs 3.10+ with Tk 8.6+, pyexpat and a shared library)." >&2
    echo "Install one from https://www.python.org/downloads/macos/, or: brew install uv && uv python install 3.12" >&2
    exit 2
  fi
fi
echo "Using $PY"

APP="$REPO/dist/Docs Typer.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
cp -R "$REPO/docstyper" "$REPO/assets" "$APP/Contents/Resources/app/"
find "$APP/Contents/Resources/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$REPO/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

# The launcher runs Python inside the app's own process, so macOS files the Accessibility and
# Input Monitoring permissions under Docs Typer (see mac-launcher.c). It reads which Python to use
# from python.txt. With Apple's command line tools it's compiled fresh; otherwise the prebuilt
# universal copy in scripts/ is used, so no Xcode download is needed.
LIBPY="$("$PY" -c "import os, sysconfig as s; print($LIBPY_EXPR)")"
PYHOME="$("$PY" -c 'import sys; print(sys.base_prefix)')"
printf '%s\n%s\n' "$LIBPY" "$PYHOME" > "$APP/Contents/Resources/python.txt"
if xcode-select -p >/dev/null 2>&1 && xcrun --find cc >/dev/null 2>&1; then
  cc -O2 -Wall -o "$APP/Contents/MacOS/DocsTyper" "$REPO/scripts/mac-launcher.c"
else
  cp "$REPO/scripts/mac-launcher" "$APP/Contents/MacOS/DocsTyper"
fi

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key><string>DocsTyper</string>
	<key>CFBundleIconFile</key><string>AppIcon</string>
	<key>CFBundleIdentifier</key><string>local.docstyper</string>
	<key>CFBundleName</key><string>Docs Typer</string>
	<key>CFBundleDisplayName</key><string>Docs Typer</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>2.0</string>
	<key>LSMinimumSystemVersion</key><string>11.0</string>
	<key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

xattr -cr "$APP" 2>/dev/null || true  # drop the download quarantine copied from a zipped repo
# Sign it (ad hoc) so macOS can tell it's the same app when you grant it permissions.
codesign --force --sign - --identifier local.docstyper "$APP" >/dev/null 2>&1 || true
echo "Built: $APP"
