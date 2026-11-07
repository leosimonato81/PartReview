#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Links this repository into FreeCAD's Mod folder so the workbench shows up
# without installing. Usage: ./tools/link_to_freecad.sh [MOD_DIR]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLATPAK_MOD="$HOME/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod"
NATIVE_MOD="$HOME/.local/share/FreeCAD/v1-1/Mod"

if [[ $# -ge 1 ]]; then
    MOD_DIR="$1"
elif [[ -d "$FLATPAK_MOD" ]]; then
    MOD_DIR="$FLATPAK_MOD"
else
    MOD_DIR="$NATIVE_MOD"
fi

mkdir -p "$MOD_DIR"
TARGET="$MOD_DIR/PartReview"

if [[ -L "$TARGET" ]]; then
    echo "Replacing existing link: $TARGET -> $(readlink "$TARGET")"
    rm "$TARGET"
elif [[ -e "$TARGET" ]]; then
    echo "ERROR: $TARGET exists and is not a link. Remove it manually." >&2
    exit 1
fi

ln -s "$REPO_DIR" "$TARGET"
echo "Linked: $TARGET -> $REPO_DIR"

if [[ "$MOD_DIR" == "$FLATPAK_MOD" ]]; then
    echo
    echo "Flatpak note: FreeCAD needs permission to read the repository folder."
    echo "If the workbench does not appear, run once:"
    echo "  flatpak override --user --filesystem=\"$REPO_DIR\":ro org.freecad.FreeCAD"
fi
echo "Restart FreeCAD to load the workbench."
