#!/usr/bin/env bash
# waybar-autohide.sh — reveal Waybar when the pointer hits the top edge,
# hide it again (after a short delay) when the pointer moves away.
# Windows-style taskbar auto-hide, with a slide animation provided by a
# Hyprland layer rule (see hypr_settings_autostart.lua).
#
# Tunables come from ~/.config/hypr-settings/autohide.conf:
#   ENABLED     1 to run, 0 to stay out of the way (daemon shows bar and exits)
#   REVEAL_AT   px from the top that triggers a reveal        (default 3)
#   HIDE_BELOW  px below which the bar is allowed to hide      (default 45)
#   HIDE_DELAY  seconds to wait after leaving before hiding    (default 0.5)
#   POLL        seconds between cursor checks                  (default 0.06)
set -u

CONF="${XDG_CONFIG_HOME:-$HOME/.config}/hypr-settings/autohide.conf"
LOG="${XDG_DATA_HOME:-$HOME/.local/share}/hypr-settings/logs/autohide.log"
ENABLED=1
REVEAL_AT=3
HIDE_BELOW=45
HIDE_DELAY=0.5
POLL=0.06
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"

log() { mkdir -p "$(dirname "$LOG")"; printf '%s  %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

# Make hyprctl work even when launched from Hyprland's startup before the
# session environment is fully propagated.
if [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
  hd="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
  [ -d "$hd" ] && export HYPRLAND_INSTANCE_SIGNATURE="$(ls -t "$hd" 2>/dev/null | head -1)"
fi
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"

PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/waybar-autohide.pid"

# Single instance: if another daemon is alive, exit.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  exit 0
fi

bar_visible() {
  local r
  r=$(hyprctl monitors -j 2>/dev/null | jq '[.[].reserved[1]] | max' 2>/dev/null)
  [ "${r:-0}" -gt 0 ] && echo 1 || echo 0
}
show_bar() { [ "$(bar_visible)" = 0 ] && killall -SIGUSR1 waybar 2>/dev/null; }
toggle()   { killall -SIGUSR1 waybar 2>/dev/null; }

# Disabled → make sure the bar is shown, then leave.
if [ "${ENABLED}" != "1" ]; then
  show_bar
  log "disabled; bar shown; exiting"
  exit 0
fi

echo $$ >"$PIDFILE"
cleanup() { rm -f "$PIDFILE"; exit 0; }
trap cleanup TERM INT EXIT

delay_ms=$(awk "BEGIN{printf \"%d\", $HIDE_DELAY*1000}")
now_ms() { date +%s%3N; }

# Force-hide at start, retrying in case Waybar is mid-restart and ignores the
# first signal (HyDE restarts the bar on config changes).
tries=0
while [ "$(bar_visible)" = 1 ] && [ "$tries" -lt 8 ]; do
  toggle; sleep 0.25; tries=$((tries + 1))
done
visible=0
log "started (reveal<=$REVEAL_AT hide>$HIDE_BELOW delay=${HIDE_DELAY}s)"

# Resync tracked state against reality roughly once a second so an external
# Waybar restart can't leave us stuck.
resync_every=$(awk "BEGIN{n=int(1/$POLL); if(n<5)n=5; print n}")
leave_at=0
resync=0
while :; do
  pos=$(hyprctl cursorpos 2>/dev/null)   # "X, Y"
  y="${pos##*, }"
  if [[ "$y" =~ ^-?[0-9]+$ ]]; then
    if [ "$y" -le "$REVEAL_AT" ]; then
      [ "$visible" = 0 ] && { toggle; visible=1; }
      leave_at=0
    elif [ "$y" -le "$HIDE_BELOW" ]; then
      # Pointer is over the (revealed) bar: keep it, cancel any pending hide.
      leave_at=0
    else
      if [ "$visible" = 1 ]; then
        if [ "$leave_at" = 0 ]; then
          leave_at=$(now_ms)
        elif [ "$(( $(now_ms) - leave_at ))" -ge "$delay_ms" ]; then
          toggle; visible=0; leave_at=0
        fi
      fi
    fi
  fi
  resync=$((resync + 1))
  if [ "$resync" -ge "$resync_every" ]; then
    actual=$(bar_visible)
    # If reality drifted from what we think (e.g. bar was restarted shown),
    # adopt it; the cursor logic will re-hide on the next pass if needed.
    [ "$actual" != "$visible" ] && visible=$actual
    resync=0
  fi
  sleep "$POLL"
done
