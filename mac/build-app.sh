#!/bin/bash
# Builds "dist/Docs Typer.app", a double-clickable app that bundles the code and runs it with
# the Python you build it with. Usage:  ./mac/build-app.sh  [path/to/python3]
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
# A usable Python is 3.10+ with Tk 8.6+ and a working XML parser (needed for .docx/.odt).
# Homebrew's Python can fail the last check on some macOS versions (pyexpat links the system libexpat).
CHECK='import sys, tkinter, pyexpat; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6; print(sys.executable)'

if [ $# -ge 1 ]; then
  if ! PY="$("$1" -c "$CHECK" 2>/dev/null)"; then
    echo "The Python at $1 needs to be 3.10+ with Tk 8.6+ and a working pyexpat module." >&2
    exit 1
  fi
else
  PY=""
  for c in \
      "$(command -v uv >/dev/null && uv python find '>=3.10' 2>/dev/null || true)" \
      /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
      python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] || continue
    if PY="$("$c" -c "$CHECK" 2>/dev/null)"; then break; fi
    PY=""
  done
  if [ -z "$PY" ]; then
    echo "No suitable Python found (needs 3.10+ with Tk 8.6+ and pyexpat)." >&2
    echo "Install one from https://www.python.org/downloads/macos/, or: brew install uv && uv python install 3.12" >&2
    exit 1
  fi
fi
echo "Using $PY"

APP="$REPO/dist/Docs Typer.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
cp -R "$REPO/docstyper" "$REPO/assets" "$APP/Contents/Resources/app/"
find "$APP/Contents/Resources/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$REPO/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/MacOS/DocsTyper" <<EOF
#!/bin/bash
cd "\$(dirname "\$0")/../Resources/app"
exec "$PY" -m docstyper
EOF
chmod +x "$APP/Contents/MacOS/DocsTyper"

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

echo "Built: $APP"
echo "Drag it to Applications. On first Start, macOS asks for Accessibility and Input Monitoring access."
