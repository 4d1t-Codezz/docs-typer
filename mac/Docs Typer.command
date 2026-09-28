#!/bin/bash
# Double-click to run Docs Typer from the repo (macOS). Uses python3 from your PATH.
cd "$(dirname "$0")/.." || exit 1
exec python3 -m docstyper
