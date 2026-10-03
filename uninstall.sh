#!/usr/bin/env bash
# Remove Hyprland Settings. Keeps your config in ~/.config/hypr-settings
# unless you pass --purge.
set -euo pipefail

rm -rf "$HOME/.local/share/hypr-settings"
rm -f "$HOME/.local/share/applications/hypr-settings.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$HOME/.config/hypr-settings"
  echo ":: Removed app and config."
else
  echo ":: Removed app. Config kept in ~/.config/hypr-settings (use --purge to delete)."
fi
