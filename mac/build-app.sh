#!/bin/bash
# Builds "dist/Docs Typer.app", a double-clickable app that bundles the code and runs it with
# the Python you build it with. Usage:  ./mac/build-app.sh  [path/to/python3]
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
PY="${1:-$(command -v python3 || true)}"

if [ -z "$PY" ]; then
  echo "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/macos/" >&2
  exit 1
fi
PY="$("$PY" -c 'import sys; print(sys.executable)')"

TK=$("$PY" -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || echo "none")
case "$TK" in
  8.6*|9.*) ;;
  *)
    echo "The Python at $PY has Tk $TK. Docs Typer needs Tk 8.6 or newer." >&2
    echo "Use the python.org installer (or: brew install python-tk) and pass its python3 to this script." >&2
    exit 1
    ;;
esac

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
