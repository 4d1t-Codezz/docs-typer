#!/bin/bash
# Installs Docs Typer on a Mac. Paste this into Terminal:
#   curl -fsSL https://raw.githubusercontent.com/4d1t-Codezz/docs-typer/main/install.sh | bash
# It downloads the latest version, gets a Python that works (if this Mac doesn't have one), builds
# the app, puts it in Applications and opens it. Run it again any time to update.
# "Install on Mac.command" runs this from a downloaded copy instead.
#
# For testing: DOCSTYPER_REF picks the branch to download, DOCSTYPER_APP_DIR the folder to install
# into, and DOCSTYPER_NO_OPEN=1 skips opening the app at the end.
set -euo pipefail

REPO_URL="https://github.com/4d1t-Codezz/docs-typer"
REF="${DOCSTYPER_REF:-main}"

echo "Installing Docs Typer..."
echo

# Use the copy this script sits in, or download one when it's run straight from the web.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
if [ -f "$here/docstyper/__init__.py" ]; then
  SRC="$here"
else
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  echo "Downloading..."
  curl -fsSL "$REPO_URL/archive/refs/heads/$REF.tar.gz" | tar -xz -C "$tmp" --strip-components=1
  SRC="$tmp"
fi

status=0
"$SRC/scripts/build-mac-app.sh" || status=$?
if [ $status -eq 2 ]; then
  # No usable Python. uv installs one just for this user (no password, nothing else changes).
  echo
  echo "Getting a copy of Python for Docs Typer (about a minute)..."
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  if [ ! -x "$UV" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh >/dev/null
    UV="$HOME/.local/bin/uv"
  fi
  UV_PYTHON_INSTALL_BIN=0 "$UV" python install 3.12
  echo
  status=0
  "$SRC/scripts/build-mac-app.sh" "$("$UV" python find 3.12)" || status=$?
fi
if [ $status -ne 0 ]; then
  echo
  echo "Install failed (see the message above)."
  exit 1
fi

if [ -n "${DOCSTYPER_APP_DIR:-}" ]; then
  DEST="$DOCSTYPER_APP_DIR"
elif [ -w /Applications ]; then
  DEST=/Applications
else
  DEST="$HOME/Applications"
fi
mkdir -p "$DEST"
pkill -f "$DEST/Docs Typer.app/Contents/MacOS/" 2>/dev/null || true  # quit the old version
rm -rf "$DEST/Docs Typer.app"
cp -R "$SRC/dist/Docs Typer.app" "$DEST/"

echo
echo "Done! Docs Typer is in $DEST."
echo
echo "The first time you press Start, macOS asks for two permissions:"
echo "  - Accessibility (so it can type)"
echo "  - Input Monitoring (so it stops when you touch anything)"
echo "Turn both on for Docs Typer in System Settings > Privacy & Security, then quit and reopen it."
echo "Updating from an older version? Remove the old Docs Typer entries with - and allow it again."
if [ -z "${DOCSTYPER_NO_OPEN:-}" ]; then
  open "$DEST/Docs Typer.app"
fi
