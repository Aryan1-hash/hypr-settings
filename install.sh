#!/usr/bin/env bash
# Install Hyprland Settings into ~/.local/share and add a launcher.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
SHARE="$HOME/.local/share/hypr-settings"
APPS="$HOME/.local/share/applications"

echo ":: Installing to $SHARE"
mkdir -p "$SHARE" "$APPS"
install -Dm644 "$SRC/hypr-settings.py" "$SHARE/hypr-settings.py"
install -Dm755 "$SRC/scripts/waybar-autohide.sh"   "$SHARE/waybar-autohide.sh"
install -Dm755 "$SRC/scripts/mpvpaper-powersave.sh" "$SHARE/mpvpaper-powersave.sh"
install -Dm755 "$SRC/scripts/live-wallpaper.sh"     "$SHARE/live-wallpaper.sh"

echo ":: Adding launcher"
cat > "$APPS/hypr-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Hyprland Settings
Comment=Waybar, appearance, battery, connectivity and more for HyDE/Hyprland
Exec=python3 $SHARE/hypr-settings.py
Icon=preferences-system
Terminal=false
Categories=Settings;DesktopSettings;GTK;
Keywords=waybar;hyprland;hyde;autohide;theme;wallpaper;battery;
StartupNotify=true
EOF
update-desktop-database "$APPS" 2>/dev/null || true

echo ":: Done."
echo "   Launch from your app menu as \"Hyprland Settings\""
echo "   or run: python3 $SHARE/hypr-settings.py"
