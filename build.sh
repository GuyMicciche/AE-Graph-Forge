#!/usr/bin/env bash
# ============================================================================
#  build.sh -- build a standalone AE Graph Forge binary on macOS or Linux.
#
#    ./build.sh            one-folder build (fast to start)
#    ./build.sh onefile    single executable
#    ./build.sh clean      remove build artefacts and exit
#
#  macOS produces dist/AEGraphForge.app, Linux produces dist/AEGraphForge/.
# ============================================================================
set -euo pipefail

APPNAME=AEGraphForge
ENTRY=run.py
PY=${PYTHON:-python3}

if [[ "${1:-}" == "clean" ]]; then
    echo "Cleaning..."
    rm -rf build dist "${APPNAME}.spec"
    echo "Done."
    exit 0
fi

command -v "$PY" >/dev/null 2>&1 || {
    echo "ERROR: $PY not found. Install Python 3.9+ or set PYTHON=..." >&2
    exit 1
}

echo "=== Installing build dependencies ==="
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt pyinstaller

MODE="--onedir"
[[ "${1:-}" == "onefile" ]] && MODE="--onefile"

EXTRA=()
case "$(uname -s)" in
    Darwin)
        # A .app bundle needs an identifier, and universal2 wheels are not
        # always available, so build for the host architecture.
        EXTRA+=(--osx-bundle-identifier "com.miccichestudios.aegraphforge")
        ;;
esac

echo "=== Building $APPNAME ($MODE) ==="
"$PY" -m PyInstaller \
    --noconfirm \
    --clean \
    $MODE \
    --windowed \
    --name "$APPNAME" \
    --add-data "presets:presets" \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module PySide6.QtWebEngineCore \
    --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.Qt3DCore \
    --exclude-module PySide6.QtMultimedia \
    --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtQml \
    "${EXTRA[@]}" \
    "$ENTRY"

echo
echo "=== Build complete ==="
case "$(uname -s)" in
    Darwin) echo "  dist/${APPNAME}.app" ;;
    *)      echo "  dist/${APPNAME}/${APPNAME}" ;;
esac
