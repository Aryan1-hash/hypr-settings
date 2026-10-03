#!/usr/bin/env bash
# mpvpaper-powersave.sh — pause the live wallpaper only when an OPAQUE window
# covers the desktop. Keep it animating when the covering windows are
# transparent (terminal, file manager, the settings app…), because you can see
# the wallpaper through them. Pausing drops CPU to ~0; RAM stays resident so
# resume is instant.
set -u

SOCK="${XDG_RUNTIME_DIR:-/tmp}/mpvpaper.sock"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/mpvpaper-powersave.pid"
# One class-name regex per line; a window whose class matches is treated as
# see-through, so it does NOT pause the wallpaper. Edit to taste.
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/hypr-settings/transparent-apps.conf"
POLL=1.0

if [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
  hd="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
  [ -d "$hd" ] && export HYPRLAND_INSTANCE_SIGNATURE="$(ls -t "$hd" 2>/dev/null | head -1)"
fi

# Default transparent-app patterns (case-insensitive, matched as substrings).
default_patterns='kitty
alacritty
foot
wezterm
org.hyde.HyprSettings
dolphin
thunar
nautilus
pcmanfm
nemo'
if [ -f "$CONF" ]; then
  patterns="$(grep -vE '^\s*#|^\s*$' "$CONF")"
else
  mkdir -p "$(dirname "$CONF")"
  printf '# Windows whose class matches a line here are treated as transparent,\n# so the live wallpaper keeps animating behind them (you can see through).\n# One case-insensitive substring per line.\n%s\n' "$default_patterns" > "$CONF"
  patterns="$default_patterns"
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then exit 0; fi
echo $$ >"$PIDFILE"
trap 'rm -f "$PIDFILE"; exit 0' TERM INT EXIT

set_pause() {  # true|false
  [ -S "$SOCK" ] || return 1
  printf '{"command":["set_property","pause",%s]}\n' "$1" | socat - "$SOCK" >/dev/null 2>&1
}

is_transparent() {  # class -> 0 if matches a transparent pattern
  local c="${1,,}" p
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    case "$c" in *"${p,,}"*) return 0;; esac
  done <<< "$patterns"
  return 1
}

state="none"
while :; do
  pgrep -x mpvpaper >/dev/null || exit 0
  active=$(hyprctl activeworkspace -j 2>/dev/null | jq -r '.id')
  # classes of windows on the focused workspace
  mapfile -t classes < <(hyprctl clients -j 2>/dev/null | jq -r --argjson ws "${active:-0}" '.[] | select(.workspace.id==$ws) | .class')

  want=false   # default: play
  if [ "${#classes[@]}" -eq 0 ]; then
    want=false                      # empty desktop -> play
  else
    want=false
    for c in "${classes[@]}"; do
      if ! is_transparent "$c"; then want=true; break; fi   # an opaque window -> pause
    done
  fi

  if [ "$want" != "$state" ]; then
    set_pause "$want" && state="$want"
  fi
  sleep "$POLL"
done
