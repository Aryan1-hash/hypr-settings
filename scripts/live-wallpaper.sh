#!/usr/bin/env bash
# live-wallpaper.sh — manage a low-resource mpvpaper live wallpaper.
#
#   live-wallpaper.sh start <video>   start mpvpaper (hwdec, no-audio, loop) + power-save
#   live-wallpaper.sh stop            stop it and restore the static wallpaper
#   live-wallpaper.sh status          print running/stopped
#
# Power-save pauses decoding whenever a window covers the desktop (≈0% CPU).
set -u

DIR="${XDG_DATA_HOME:-$HOME/.local/share}/hypr-settings"
SOCK="${XDG_RUNTIME_DIR:-/tmp}/mpvpaper.sock"
STATEFILE="${XDG_CONFIG_HOME:-$HOME/.config}/hypr-settings/live-wallpaper.conf"
LOG="$DIR/logs/live-wallpaper.log"
log() { mkdir -p "$(dirname "$LOG")"; printf '%s  %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

if [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
  hd="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
  [ -d "$hd" ] && export HYPRLAND_INSTANCE_SIGNATURE="$(ls -t "$hd" 2>/dev/null | head -1)"
fi
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"

stop_live() {
  pkill -f mpvpaper-powersave.sh 2>/dev/null
  pkill -x mpvpaper 2>/dev/null
  rm -f "$SOCK"
}

case "${1:-}" in
  start)
    video="${2:-}"
    [ -f "$video" ] || { echo "no such video: $video" >&2; exit 1; }
    command -v mpvpaper >/dev/null || { echo "mpvpaper not installed" >&2; exit 2; }
    stop_live; sleep 0.4
    mpvpaper --fork \
      --mpv-options "no-audio loop hwdec=auto-safe panscan=1.0 input-ipc-server=$SOCK" \
      '*' "$video"
    sleep 1
    setsid -f bash "$DIR/mpvpaper-powersave.sh" >/dev/null 2>&1 < /dev/null || true
    mkdir -p "$(dirname "$STATEFILE")"
    printf 'ENABLED=1\nVIDEO=%q\n' "$video" > "$STATEFILE"
    log "start $video"
    echo "live wallpaper started"
    ;;
  stop)
    stop_live
    mkdir -p "$(dirname "$STATEFILE")"
    printf 'ENABLED=0\n' > "$STATEFILE"
    # restore the HyDE static wallpaper
    "$HOME/.local/bin/hyde-shell" wallpaper --start >/dev/null 2>&1 || true
    log "stop"
    echo "live wallpaper stopped; static restored"
    ;;
  status)
    if pgrep -x mpvpaper >/dev/null; then echo "running"; else echo "stopped"; fi
    ;;
  *)
    echo "usage: $0 start <video> | stop | status" >&2; exit 1 ;;
esac
