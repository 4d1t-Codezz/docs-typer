#!/bin/bash
# Double-click this file to install Docs Typer on your Mac.
# It builds the app, puts it in your Applications folder and opens it.
# Run it again any time to update after downloading a newer version.

cd "$(dirname "$0")" || exit 1

echo "Installing Docs Typer..."
echo

./scripts/build-mac-app.sh
status=$?

if [ $status -eq 2 ]; then
  echo
  echo "Docs Typer needs Python 3.10 or newer, and this Mac doesn't have a version that works."
  read -r -p "Download and install it now? This takes about a minute. [Y/n] " answer
  case "$answer" in
    [nN]*)
      echo "Okay. Install Python from https://www.python.org/downloads/macos/ and run this again."
      exit 1
      ;;
  esac
  if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh || exit 1
  fi
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  "$UV" python install 3.12 || exit 1
  echo
  ./scripts/build-mac-app.sh
  status=$?
fi
[ $status -eq 0 ] || { echo; echo "Install failed (see the message above)."; exit 1; }

if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; fi
mkdir -p "$DEST"
rm -rf "$DEST/Docs Typer.app"
cp -R "dist/Docs Typer.app" "$DEST/"

echo
echo "Done! Docs Typer is in $DEST. Opening it now..."
echo
echo "The first time you press Start, macOS asks for two permissions:"
echo "  - Accessibility (so it can type)"
echo "  - Input Monitoring (so it stops when you touch anything)"
echo "Turn both on in System Settings > Privacy & Security, then press Start again."
open "$DEST/Docs Typer.app"
